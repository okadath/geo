// battlemap.js — panel del modo Battlemap (la estrella, ADR-006). Portado de
// batalla.html e integrado al lienzo de fantasía: el punto del encuentro se
// elige haciendo clic en el mapa (visor.onPick), y este panel muestra la ficha
// del lugar, la escena y una vista previa del battlemap con export.
// Toda la generación vive en el servidor (batalla_srv.py); esto es solo UI.

import {
  batallaInfo, batallaLugar, batallaEscena, batallaVTT, urlBatallaMapa,
} from "./api.js";
import { aviso, modal } from "./ui.js";

// ---- textos visibles agrupados (ADR-008) ----
const TXT = {
  sinPunto: "Haz clic en cualquier punto del mapa para elegir el lugar del encuentro.",
  cargando: "consultando el lugar…",
  generando: "generando…",
  errLugar: "no se pudo leer el lugar",
  errInfo: "no se pudo cargar el catálogo de battlemaps",
  notaExport: "PNG a 70 px/casilla · HD a 140 · el export respeta la rejilla",
  genFoundry: "generando escena de Foundry…",
  genRoll20: "generando PNG para Roll20…",
};
const PREVIEW_MAX = 1200;

// crearBattlemap({sello, d, panel, visor}) -> {activar, desactivar}
export function crearBattlemap({ sello, d, panel, visor }) {
  const $ = (sel) => panel.querySelector(sel);
  const st = {
    cargado: false, temas: [], subAuto: "✨ automático",
    punto: null, lugar: null,
  };

  const nombreTema = (c) => (st.temas.find((t) => t.clave === c) || {}).nombre || c;

  function llenarSubs(tema) {
    const s = $(".bm-sub"), prev = s.value;
    s.innerHTML = "";
    const t = st.temas.find((x) => x.clave === tema);
    const lst = (t && t.subs) || [];
    const oa = document.createElement("option");
    oa.value = "auto"; oa.textContent = st.subAuto; s.appendChild(oa);
    for (const sc of lst) {
      const o = document.createElement("option");
      o.value = sc.clave; o.textContent = sc.nombre; s.appendChild(o);
    }
    s.value = lst.some((x) => x.clave === prev) ? prev : "auto";
    s.disabled = !lst.length;
  }

  // ---- carga perezosa del catálogo (una sola vez) ----
  async function asegurarCargado() {
    if (st.cargado) return true;
    try {
      const inf = await batallaInfo(sello, d);
      st.temas = inf.temas || [];
      st.subAuto = inf.sub_auto || st.subAuto;
      const s = $(".bm-tema");
      for (const t of st.temas) {
        const o = document.createElement("option");
        o.value = t.clave; o.textContent = t.nombre; s.appendChild(o);
      }
      llenarSubs(s.value);
      st.cargado = true;
      return true;
    } catch (e) {
      aviso(TXT.errInfo + ": " + e.message, "error");
      return false;
    }
  }

  // ---- ficha del lugar (datos ya cocinados por el servidor) ----
  const fila = (rot, val) =>
    `<div class="bm-dato"><span>${rot}</span><b>${val}</b></div>`;

  function pintarFicha(g) {
    let h = "";
    if (g.es_mar) {
      h += fila("terreno", "mar abierto");
    } else if (g.bioma) {
      h += `<div class="bm-bioma"><i class="bm-cuad" style="background:rgb(${g.bioma.rgb.join(",")})"></i>${g.bioma.nombre}</div>`;
    }
    h += fila("altitud", `${g.alt_pct} % · ${g.alt_desc}`);
    h += fila("temperatura", `${g.temp_desc} (${g.temp.toFixed(2)})`);
    h += fila("precipitación", `${g.precip_pct} %`);
    if (g.hielo_pct) h += fila("hielo", `${g.hielo_pct} %`);

    const cerca = [];
    if (g.rio) cerca.push(`río <b>${g.rio.nombre}</b> a ${g.rio.dist} px` +
      (g.rio.cerca ? ` <span class="insignia insignia-mar">cerca</span>` : ""));
    if (g.costa) cerca.push(`costa (${g.costa.frac_pct}% de mar en la zona)`);
    if (g.camino) cerca.push(`camino a ${g.camino.dist} px` +
      (g.camino.cerca ? ` <span class="insignia insignia-mar">cerca</span>` : ""));
    if (g.asent) cerca.push(`asentamiento <b>${g.asent.nombre}</b> a ${g.asent.dist} px` +
      (g.asent.aqui ? ` <span class="insignia insignia-mar">aquí</span>` : "") +
      (g.asent.pais ? `<br><span class="tenue">${g.asent.pais}</span>` : ""));
    if (cerca.length) {
      h += `<div class="bm-cerca"><span class="tenue">alrededores</span><ul>` +
        cerca.map((x) => `<li>${x}</li>`).join("") + `</ul></div>`;
    }
    h += `<div class="bm-sug tenue">tema sugerido: <b>${g.tema_nombre}</b></div>`;
    if (g.interiores)
      h += `<div class="tenue">variantes de interior: taberna, cripta, mazmorra</div>`;
    $(".bm-ficha").innerHTML = h;
  }

  // ---- parámetros de la escena ----
  function leerParams() {
    let cols = Math.max(10, Math.min(40, parseInt($(".bm-cols").value) || 20));
    let rows = Math.max(10, Math.min(40, parseInt($(".bm-rows").value) || 20));
    $(".bm-cols").value = cols; $(".bm-rows").value = rows;
    let seed = parseInt($(".bm-seed").value);
    if (!Number.isFinite(seed) || seed < 0) seed = 1;
    return {
      cols, rows, seed, tema: $(".bm-tema").value, sub: $(".bm-sub").value || "auto",
      grid: $(".bm-grid").checked, nums: $(".bm-nums").checked,
      momento: $(".bm-momento").value, estacion: $(".bm-estacion").value,
    };
  }

  function qMapa(p, px, numsOverride) {
    const nums = numsOverride === undefined ? p.nums : numsOverride;
    const q = {
      tema: p.tema, sub: p.sub, cols: p.cols, rows: p.rows, semilla: p.seed,
      px, rejilla: p.grid ? 1 : 0, nums: nums ? 1 : 0,
      momento: p.momento, estacion: p.estacion,
    };
    if (st.punto) { q.rx = st.punto.rx.toFixed(2); q.ry = st.punto.ry.toFixed(2); }
    return q;
  }
  function qVtt(p, formato) {
    const q = {
      tema: p.tema, sub: p.sub, cols: p.cols, rows: p.rows, semilla: p.seed,
      formato, momento: p.momento, estacion: p.estacion,
    };
    if (st.punto) { q.rx = st.punto.rx.toFixed(2); q.ry = st.punto.ry.toFixed(2); }
    return q;
  }

  // ---- vista previa (con debounce) + título narrativo ----
  const imgB = $(".bm-preview");
  let tmrPrev = 0;
  function regenerar() {
    clearTimeout(tmrPrev);
    tmrPrev = setTimeout(regenerarYa, 180);
  }
  function regenerarYa() {
    const p = leerParams();
    const S = Math.max(24, Math.min(64, Math.round(PREVIEW_MAX / Math.max(p.cols, p.rows))));
    const t0 = performance.now();
    imgB.classList.add("bm-preview-cargando");
    imgB.onload = () => {
      imgB.classList.remove("bm-preview-cargando");
      const ms = Math.round(performance.now() - t0);
      const b = $(".bm-sub-esc").dataset.base || "";
      $(".bm-sub-esc").textContent = b + ` · ${ms} ms`;
    };
    imgB.onerror = () => { imgB.classList.remove("bm-preview-cargando"); };
    $(".bm-sub-esc").dataset.base = `${p.cols}×${p.rows} casillas · ${TXT.generando}`;
    $(".bm-sub-esc").textContent = $(".bm-sub-esc").dataset.base;
    imgB.src = urlBatallaMapa(sello, d, qMapa(p, S));

    batallaEscena(sello, d, {
      rx: st.punto ? st.punto.rx.toFixed(2) : undefined,
      ry: st.punto ? st.punto.ry.toFixed(2) : undefined,
      tema: p.tema, sub: p.sub, semilla: p.seed,
      momento: p.momento, estacion: p.estacion,
    }).then((e) => {
      $(".bm-titulo").textContent = e.titulo || nombreTema(p.tema);
      $(".bm-sub-esc").dataset.base =
        `${p.cols}×${p.rows} casillas · tema: ${e.tema_nombre}` +
        (e.tiene_subs ? ` · ${e.sub_nombre}${e.auto ? " (auto)" : ""}` : "") +
        ` · semilla ${p.seed}`;
      $(".bm-sub-esc").textContent = $(".bm-sub-esc").dataset.base;
    }).catch(() => {});
  }

  // ---- elegir punto (disparado por clic en el mapa) ----
  async function elegir(rx, ry) {
    st.punto = { rx, ry };
    visor.setPin(rx, ry);
    $(".bm-ficha").innerHTML = `<p class="tenue">${TXT.cargando}</p>`;
    try {
      const g = await batallaLugar(sello, d, rx.toFixed(2), ry.toFixed(2));
      st.lugar = g;
      $(".bm-tema").value = g.tema;
      llenarSubs(g.tema);
      $(".bm-sub").value = "auto";
      pintarFicha(g);
      regenerarYa();
    } catch (e) {
      $(".bm-ficha").innerHTML = `<p class="tenue">${TXT.errLugar}: ${e.message}</p>`;
    }
  }

  // ---- exportar PNG (descarga del render del servidor) ----
  function bajar(blob, nombre) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = nombre;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2500);
  }
  function nombreBase(p, sufijo) {
    const nom = ($(".bm-titulo").textContent || "battlemap")
      .replace(/[^\w\sáéíóúñ-]/gi, "").trim().replace(/\s+/g, "_").toLowerCase();
    return `${nom || "battlemap"}_${p.cols}x${p.rows}${sufijo}`;
  }
  async function exportar(celPx) {
    const p = leerParams();
    aviso(`exportando PNG a ${celPx} px/casilla…`, "info", 2500);
    try {
      const r = await fetch(urlBatallaMapa(sello, d, qMapa(p, celPx)));
      if (!r.ok) throw new Error("HTTP " + r.status);
      bajar(await r.blob(), nombreBase(p, `_${celPx}px${p.grid ? "_grid" : ""}.png`));
      aviso("PNG exportado.", "ok");
    } catch (e) { aviso("no se pudo exportar: " + e.message, "error"); }
  }

  // ---- export Foundry / Roll20 (manifiesto JSON + instrucción en modal) ----
  async function exportFoundry() {
    const p = leerParams();
    aviso(TXT.genFoundry, "info", 2500);
    try {
      const man = await batallaVTT(sello, d, qVtt(p, "foundry"));
      const png = man.img || `battlemap_${p.cols}x${p.rows}.png`;
      const r = await fetch(urlBatallaMapa(sello, d, qMapa(p, 100, false)));
      if (!r.ok) throw new Error("png");
      bajar(await r.blob(), png);
      const limpio = Object.assign({}, man); delete limpio._archivo_png;
      const jb = new Blob([JSON.stringify(limpio, null, 2)], { type: "application/json" });
      setTimeout(() => bajar(jb, png.replace(/\.png$/i, ".json")), 350);
      modal({
        titulo: "Exportado a Foundry VTT",
        cuerpoHTML:
          `<p>Se descargaron dos archivos: el <b>PNG</b> (${man.width}×${man.height} px) y su <b>.json</b> de escena.</p>` +
          `<p class="tenue">Rejilla ${man.grid.size} px/casilla. En Foundry, arrastra el <code>.json</code> a la carpeta de escenas y sube el PNG cuando lo pida.</p>`,
      });
    } catch (e) { aviso("no se pudo exportar a Foundry: " + e.message, "error"); }
  }
  async function exportRoll20() {
    const p = leerParams();
    aviso(TXT.genRoll20, "info", 2500);
    try {
      const inf = await batallaVTT(sello, d, qVtt(p, "roll20"));
      const r = await fetch(urlBatallaMapa(sello, d, qMapa(p, 70, false)));
      if (!r.ok) throw new Error("png");
      bajar(await r.blob(), inf.archivo_png || `battlemap_${p.cols}x${p.rows}_70px.png`);
      modal({
        titulo: "Exportado a Roll20",
        cuerpoHTML:
          `<p>Se descargó el <b>PNG</b> a 70 px/casilla.</p>` +
          `<p class="tenue">${inf.nota || ""}. En la página de Roll20, ajusta el tamaño a <b>${inf.cols}×${inf.rows}</b> unidades.</p>`,
      });
    } catch (e) { aviso("no se pudo exportar a Roll20: " + e.message, "error"); }
  }

  // ---- cableado de controles ----
  $(".bm-tema").addEventListener("change", () => { llenarSubs($(".bm-tema").value); regenerar(); });
  for (const sel of [".bm-sub", ".bm-cols", ".bm-rows", ".bm-seed",
    ".bm-grid", ".bm-nums", ".bm-momento", ".bm-estacion"])
    $(sel).addEventListener("change", regenerar);
  $(".bm-dado").addEventListener("click", () => {
    $(".bm-seed").value = Math.floor(Math.random() * 1e9); regenerar();
  });
  $(".bm-regen").addEventListener("click", regenerarYa);
  $(".bm-exp70").addEventListener("click", () => exportar(70));
  $(".bm-exp140").addEventListener("click", () => exportar(140));
  $(".bm-foundry").addEventListener("click", exportFoundry);
  $(".bm-roll20").addEventListener("click", exportRoll20);

  return {
    async activar() {
      const ok = await asegurarCargado();
      if (!ok) return;
      visor.setPick(true);
      visor.onPick = elegir;
      if (!st.punto) {
        // arranque: centro del mapa, como batalla.html
        elegir(visor.nx / 2, visor.ny / 2);
      }
    },
    desactivar() {
      visor.setPick(false);
      visor.onPick = null;
    },
  };
}
