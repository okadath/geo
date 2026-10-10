// battlemap.js — controles del battlemap (la estrella, ADR-006). Portado de
// batalla.html. Dos formas de montarlo:
//   · con `visor` (workspace): el punto se elige con clic en el mapa
//     (visor.onPick) y se usa activar()/desactivar();
//   · sin visor (página /w/<sello>/<x>,<y>): el punto es fijo, se arranca con
//     iniciar(rx, ry), el estado inicial llega en `inicial` (la query) y cada
//     render avisa por `onCambio(query)` para reescribir la URL.
// Muestra la ficha del lugar, la escena y el render del battlemap con export.
// Toda la generación vive en el servidor (batalla_srv.py); esto es solo UI.
//
// La conversión clic-de-pantalla → rejilla (rx, ry) vive en visor.js
// (pantallaARender, expuesta como visor.aRejilla).

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
  errRender: "el servidor no pudo generar el battlemap (¿límite de renders?); prueba ↻ regenerar en un momento",
  notaExport: "PNG a 70 px/casilla · HD a 140 · el export respeta la rejilla",
  genFoundry: "generando escena de Foundry…",
  genRoll20: "generando PNG para Roll20…",
};
const PREVIEW_MAX = 1200;

// Claves de la query de página (mismos nombres que /api/batalla/mapa, para
// que el servidor cachee por URL sin traducir).
export const CLAVES_QUERY = [
  "tema", "sub", "semilla", "cols", "rows", "px", "rejilla", "nums",
  "momento", "estacion",
];

// crearBattlemap(opciones) -> {activar, desactivar, iniciar, elegir, query,
//                              resolucion, lugar, titulo}
//   sello, d    mundo y detalle
//   panel       raíz donde viven los controles (.bm-*); los que falten se omiten
//   visor?      visor de fantasía (modo workspace: pin + clic elige punto)
//   imagen?     <img> del render (por defecto .bm-preview del panel)
//   inicial?    {tema, sub, semilla, cols, rows, px, rejilla, nums, momento,
//               estacion} (strings de la query). Se aplica al cargar el
//               catálogo; un tema inicial válido no se pisa con el sugerido.
//   onCambio?   fn(query) tras cada render (query con claves CLAVES_QUERY)
//   onLugar?    fn(ficha) cuando llega /api/batalla/lugar
//   antesVTT?   async fn(formato) -> bool; false cancela el export VTT
export function crearBattlemap({
  sello, d, panel, visor = null, imagen = null, inicial = null,
  onCambio = null, onLugar = null, antesVTT = null,
}) {
  const $ = (sel) => panel.querySelector(sel);
  const st = {
    cargado: false, temas: [], subAuto: "✨ automático",
    punto: null, lugar: null, resolucion: null,
    inicial: inicial ? { ...inicial } : null,
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

  // ---- estado inicial desde la query (valores inválidos se ignoran) ----
  const hay = (v) => v !== undefined && v !== null && v !== "";
  function aplicarInicial() {
    const q = st.inicial;
    if (!q) return;
    if (!(hay(q.tema) && st.temas.some((t) => t.clave === q.tema))) delete q.tema;
    else $(".bm-tema").value = q.tema;
    const poner = (sel, v) => { const el = $(sel); if (el && hay(v)) el.value = v; };
    const marcar = (sel, v) => { const el = $(sel); if (el && hay(v)) el.checked = String(v) !== "0"; };
    const opcion = (sel, v) => {
      const el = $(sel);
      if (el && hay(v) && [...el.options].some((o) => o.value === String(v))) el.value = String(v);
    };
    poner(".bm-cols", q.cols); poner(".bm-rows", q.rows); poner(".bm-seed", q.semilla);
    const pxSel = $(".bm-px");
    const px = parseInt(q.px, 10);
    if (pxSel && Number.isFinite(px)) {
      const v = String(Math.max(8, Math.min(160, px)));
      if (![...pxSel.options].some((o) => o.value === v)) {
        const o = document.createElement("option");
        o.value = v; o.textContent = `${v} px`;
        pxSel.appendChild(o);
      }
      pxSel.value = v;
    }
    marcar(".bm-grid", q.rejilla); marcar(".bm-nums", q.nums);
    opcion(".bm-momento", q.momento); opcion(".bm-estacion", q.estacion);
  }
  // el subtipo inicial solo vale si existe para el tema elegido
  function aplicarSubInicial() {
    const q = st.inicial;
    const s = $(".bm-sub");
    if (q && hay(q.sub) && [...s.options].some((o) => o.value === q.sub)) s.value = q.sub;
  }

  // ---- carga perezosa del catálogo (una sola vez) ----
  async function asegurarCargado() {
    if (st.cargado) return true;
    try {
      const inf = await batallaInfo(sello, d);
      st.temas = inf.temas || [];
      st.subAuto = inf.sub_auto || st.subAuto;
      st.resolucion = inf.resolucion || null;
      const s = $(".bm-tema");
      for (const t of st.temas) {
        const o = document.createElement("option");
        o.value = t.clave; o.textContent = t.nombre; s.appendChild(o);
      }
      aplicarInicial();
      llenarSubs(s.value);
      aplicarSubInicial();
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
  // px por casilla del render: el selector .bm-px si existe; si no, la vista
  // previa del workspace (cabe en PREVIEW_MAX).
  function pxRender(cols, rows) {
    const sel = $(".bm-px");
    const v = sel ? parseInt(sel.value, 10) : NaN;
    if (Number.isFinite(v)) return Math.max(8, Math.min(160, v));
    return Math.max(24, Math.min(64, Math.round(PREVIEW_MAX / Math.max(cols, rows))));
  }

  function leerParams() {
    let cols = Math.max(10, Math.min(40, parseInt($(".bm-cols").value) || 20));
    let rows = Math.max(10, Math.min(40, parseInt($(".bm-rows").value) || 20));
    $(".bm-cols").value = cols; $(".bm-rows").value = rows;
    let seed = parseInt($(".bm-seed").value);
    if (!Number.isFinite(seed) || seed < 0) seed = 1;
    return {
      cols, rows, seed, tema: $(".bm-tema").value, sub: $(".bm-sub").value || "auto",
      grid: $(".bm-grid").checked, nums: $(".bm-nums").checked,
      momento: $(".bm-momento") ? $(".bm-momento").value : "dia",
      estacion: $(".bm-estacion") ? $(".bm-estacion").value : "verano",
      px: pxRender(cols, rows),
    };
  }

  // query de página (claves CLAVES_QUERY) del estado actual.
  function queryPagina(p = leerParams()) {
    return {
      tema: p.tema, sub: p.sub, semilla: p.seed, cols: p.cols, rows: p.rows,
      px: p.px, rejilla: p.grid ? 1 : 0, nums: p.nums ? 1 : 0,
      momento: p.momento, estacion: p.estacion,
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

  // ---- render (con debounce) + título narrativo ----
  const imgB = imagen || $(".bm-preview");
  const subEsc = () => $(".bm-sub-esc") || { dataset: {}, textContent: "" };
  let tmrPrev = 0;
  function regenerar() {
    clearTimeout(tmrPrev);
    tmrPrev = setTimeout(regenerarYa, 180);
  }
  function regenerarYa() {
    clearTimeout(tmrPrev);
    const p = leerParams();
    const t0 = performance.now();
    imgB.classList.add("bm-preview-cargando");
    imgB.onload = () => {
      imgB.classList.remove("bm-preview-cargando");
      const ms = Math.round(performance.now() - t0);
      const b = subEsc().dataset.base || "";
      subEsc().textContent = b + ` · ${ms} ms`;
    };
    imgB.onerror = () => {
      imgB.classList.remove("bm-preview-cargando");
      subEsc().textContent = TXT.errRender;
    };
    subEsc().dataset.base = `${p.cols}×${p.rows} casillas · ${TXT.generando}`;
    subEsc().textContent = subEsc().dataset.base;
    imgB.src = urlBatallaMapa(sello, d, qMapa(p, p.px));
    if (typeof onCambio === "function") onCambio(queryPagina(p));

    batallaEscena(sello, d, {
      rx: st.punto ? st.punto.rx.toFixed(2) : undefined,
      ry: st.punto ? st.punto.ry.toFixed(2) : undefined,
      tema: p.tema, sub: p.sub, semilla: p.seed,
      momento: p.momento, estacion: p.estacion,
    }).then((e) => {
      const tit = $(".bm-titulo");
      if (tit) tit.textContent = e.titulo || nombreTema(p.tema);
      subEsc().dataset.base =
        `${p.cols}×${p.rows} casillas · tema: ${e.tema_nombre}` +
        (e.tiene_subs ? ` · ${e.sub_nombre}${e.auto ? " (auto)" : ""}` : "") +
        ` · semilla ${p.seed}`;
      subEsc().textContent = subEsc().dataset.base;
    }).catch(() => {});
  }

  // ---- elegir punto (clic en el mapa del workspace, o punto fijo) ----
  async function elegir(rx, ry) {
    st.punto = { rx, ry };
    if (visor) visor.setPin(rx, ry);
    // un tema que llega en la query manda solo en el primer punto
    const temaFijo = !!(st.inicial && st.inicial.tema);
    st.inicial = null;
    $(".bm-ficha").innerHTML = `<p class="tenue">${TXT.cargando}</p>`;
    try {
      const g = await batallaLugar(sello, d, rx.toFixed(2), ry.toFixed(2));
      st.lugar = g;
      if (!temaFijo) {
        $(".bm-tema").value = g.tema;
        llenarSubs(g.tema);
        $(".bm-sub").value = "auto";
      }
      pintarFicha(g);
      if (typeof onLugar === "function") onLugar(g);
    } catch (e) {
      $(".bm-ficha").innerHTML = `<p class="tenue">${TXT.errLugar}: ${e.message}</p>`;
    }
    regenerarYa();              // el render no depende de la ficha
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
    const nom = (($(".bm-titulo") || {}).textContent || "battlemap")
      .replace(/[^\w\sáéíóúñ-]/gi, "").trim().replace(/\s+/g, "_").toLowerCase();
    return `${nom || "battlemap"}_${p.cols}x${p.rows}${sufijo}`;
  }
  // celPx = 0 -> px actual del render
  async function exportar(celPx) {
    const p = leerParams();
    if (!celPx) celPx = p.px;
    aviso(`exportando PNG a ${celPx} px/casilla…`, "info", 2500);
    try {
      const r = await fetch(urlBatallaMapa(sello, d, qMapa(p, celPx)));
      if (!r.ok) throw new Error("HTTP " + r.status);
      bajar(await r.blob(), nombreBase(p, `_${celPx}px${p.grid ? "_grid" : ""}.png`));
      aviso("PNG exportado.", "ok");
    } catch (e) { aviso("no se pudo exportar: " + e.message, "error"); }
  }

  // ---- export Foundry / Roll20 (manifiesto JSON + instrucción en modal) ----
  async function puedeVTT(formato) {
    if (typeof antesVTT !== "function") return true;
    try { return !!(await antesVTT(formato)); } catch (_) { return false; }
  }
  async function exportFoundry() {
    if (!(await puedeVTT("foundry"))) return;
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
    if (!(await puedeVTT("roll20"))) return;
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

  // ---- cableado de controles (los que no existan en el panel se omiten) ----
  const en = (sel, ev, fn) => { const el = $(sel); if (el) el.addEventListener(ev, fn); };
  en(".bm-tema", "change", () => { llenarSubs($(".bm-tema").value); regenerar(); });
  for (const sel of [".bm-sub", ".bm-cols", ".bm-rows", ".bm-seed", ".bm-px",
    ".bm-grid", ".bm-nums", ".bm-momento", ".bm-estacion"])
    en(sel, "change", regenerar);
  en(".bm-dado", "click", () => {
    $(".bm-seed").value = Math.floor(Math.random() * 1e9); regenerar();
  });
  en(".bm-regen", "click", regenerarYa);
  en(".bm-exp", "click", () => exportar(0));
  en(".bm-exp70", "click", () => exportar(70));
  en(".bm-exp140", "click", () => exportar(140));
  en(".bm-foundry", "click", exportFoundry);
  en(".bm-roll20", "click", exportRoll20);

  return {
    // modo workspace (con visor): clic en el mapa elige el punto
    async activar() {
      const ok = await asegurarCargado();
      if (!ok || !visor) return;
      visor.setPick(true);
      visor.onPick = elegir;
      if (!st.punto) {
        // arranque: centro del mapa, como batalla.html
        elegir(visor.nx / 2, visor.ny / 2);
      }
    },
    desactivar() {
      if (!visor) return;
      visor.setPick(false);
      visor.onPick = null;
    },
    // modo página (sin visor): punto fijo (rx, ry) en la rejilla del mundo.
    // Resuelve false si el catálogo no cargó.
    async iniciar(rx, ry) {
      const ok = await asegurarCargado();
      if (!ok) return false;
      await elegir(rx, ry);
      return true;
    },
    // catálogo de temas + resolución (una sola vez). Resuelve false si falla.
    cargarCatalogo: asegurarCargado,
    elegir,
    query: () => queryPagina(),
    get resolucion() { return st.resolucion; },
    get lugar() { return st.lugar; },
  };
}
