// mapa.js — visor del mapa de fantasía en /w/<sello>/detail (ESPECIFICACION_RUTAS
// «Visor»). Heredero del antiguo workspace sin modos: visor pan/zoom +
// panel de estilo + descarga PNG + ★ Guardar. El clic en el mapa navega al
// battlemap del punto (/w/<sello>/<x>,<y>) con la conversión fantasía→rejilla
// del visor (modo puntería). Todo el render vive en el servidor (ADR-001/003).

import { montarNav, montarPie } from "./nav.js";
import {
  RE_SELLO, mundo, capas, rotulos, guardarRotulos, avisarLimite,
  cuenta, conSesion, guardar, urlMundo, urlBattlemap,
} from "./api.js";
import { crearVisor } from "./visor.js";
import { aviso, modal, cuadroCorreo } from "./ui.js";

// ---- textos visibles agrupados (ADR-008) ----
const TXT = {
  errSello: "El enlace no trae un mundo válido.",
  errMundo: "Este mundo no existe o ya no está disponible.",
  errCapas: "No se pudo leer el detalle de este mundo.",
  pista: "clic = abrir el battlemap de ese punto · rueda = zoom · arrastrar = paneo · 0 = restablecer",
  rotCargando: "cargando rótulos…",
  rotVacio: "este detalle no tiene rótulos.",
  rotGuardados: (n) => `rótulos guardados (${n} cambios).`,
  rotRestaurados: "rótulos restaurados.",
  guardado: "Mundo guardado en tu cuenta.",
  yaGuardado: "Este mundo ya estaba en tus guardados.",
  guardarTitulo: "Guarda este mundo",
  guardarTexto: "Entra con tu correo para guardarlo; sin contraseñas.",
};
const TIPO_NOMBRE = { asent: "Asentamientos", pais: "Países", mar: "Mares", rio: "Ríos" };

const $ = (sel) => document.querySelector(sel);

// /w/<sello>/detail -> sello (el servidor ya validó el path)
const sello = decodeURIComponent((location.pathname.split("/")[2] || ""));
const dQuery = new URLSearchParams(location.search).get("d") || "";

function mostrarError(msg) {
  $("#ws").classList.add("oculto");
  $("#ws-error-msg").textContent = msg;
  $("#ws-error").classList.remove("oculto");
}

montarPie({ lab: false });
if (!RE_SELLO.test(sello)) {
  montarNav({ migas: [{ texto: "Mapa" }] });
  mostrarError(TXT.errSello);
} else {
  arrancar();
}

async function arrancar() {
  let m;
  try {
    m = await mundo(sello, dQuery || undefined);
  } catch (e) {
    montarNav({ migas: [{ texto: "Mapa" }] });
    mostrarError(e.status === 404 ? TXT.errMundo : `${TXT.errMundo} (${e.message})`);
    return;
  }
  const d = m.d;
  // d explícito en la URL -> se propaga a los enlaces; si no, URLs limpias
  const qD = dQuery ? { d } : undefined;
  montarNav({ migas: [{ texto: `Mapa · ${m.nombre}`, href: urlMundo(sello, qD) }, { texto: "Detalle" }] });
  $(".ws-mundo").textContent = m.nombre;
  $("#ws-sello").textContent = sello;
  document.title = `${m.nombre} · detalle — Pangeira`;

  // resolución del detalle: la necesitan el visor y la conversión a rejilla.
  let info;
  try {
    info = await capas(sello, d);
  } catch (e) {
    mostrarError(TXT.errCapas);
    return;
  }
  $("#ws").classList.remove("oculto");

  const visor = crearVisor({ sello, d, elVisor: $("#visor") });
  visor.onEstado = (txt, err) => {
    const el = $("#ws-estado");
    el.textContent = txt || "";
    el.classList.toggle("es-error", !!err);
    $("#z-val").textContent = "×" + (visor.zoom >= 10 ? visor.zoom.toFixed(0) : visor.zoom.toFixed(1));
  };
  visor.setEstilo({ semilla: d });
  $(".ex-semilla").value = d;
  visor.cargar(info.resolucion);

  // clic (sin arrastre) -> battlemap del punto. El visor ya convierte la
  // posición de pantalla a la rejilla (rx, ry) de /api/batalla/*.
  visor.setPick(true);
  visor.onPick = (rx, ry) => {
    location.href = urlBattlemap(sello, Math.floor(rx), Math.floor(ry), qD);
  };

  cablearEstilo(visor, d);
  cablearRotulos(visor, d);
  cablearExport(visor, d);
  cablearZoom(visor);
  $("#guardar").addEventListener("click", () => guardarMundo());
  $("#vs-pista").textContent = TXT.pista;
}

// ============================================================================
//  ★ Guardar (tipo mundo). Sin sesión -> cuadro de correo (enlace mágico).
// ============================================================================
function pedirCorreo() {
  const m = modal({ titulo: TXT.guardarTitulo });
  cuadroCorreo({ montarEn: m.querySelector(".modal-cuerpo"), titulo: "", texto: TXT.guardarTexto });
}
async function guardarMundo() {
  let c = null;
  try { c = await cuenta(); } catch (_) { /* sin API: se pide correo */ }
  if (!conSesion(c)) { pedirCorreo(); return; }
  try {
    const r = await guardar({ tipo: "mundo", sello });
    aviso(r && r.nuevo === false ? TXT.yaGuardado : TXT.guardado, "ok");
  } catch (e) {
    if (e.status === 401) pedirCorreo();
    else aviso("no se pudo guardar: " + e.message, "error");
  }
}

// ============================================================================
//  estilo: paleta, calidad, capas, países, tipografías, semilla
// ============================================================================
function cablearEstilo(visor, d) {
  $(".ex-paleta").addEventListener("change", (e) => visor.setEstilo({ paleta: e.target.value }));
  $(".ex-calidad").addEventListener("change", (e) => visor.setEstilo({ calidad: parseInt(e.target.value, 10) }));

  for (const cb of document.querySelectorAll(".ex-cap")) {
    cb.addEventListener("change", () => {
      visor.setEstilo({ capas: { [cb.dataset.capa]: cb.checked } });
    });
  }
  $(".ex-deco").addEventListener("change", (e) => visor.setEstilo({ deco: e.target.checked }));

  const npCaja = $(".ex-npaises-caja");
  const sincPaises = () => {
    const modo = $(".ex-paises").value;
    npCaja.classList.toggle("oculto", modo !== "grandes");
    visor.setEstilo({ paises: modo, npaises: parseInt($(".ex-npaises").value, 10) || 8 });
  };
  $(".ex-paises").addEventListener("change", sincPaises);
  $(".ex-npaises").addEventListener("change", () =>
    visor.setEstilo({ npaises: parseInt($(".ex-npaises").value, 10) || 8 }));

  // sliders de tipografía: valor en vivo, re-render (costoso) solo al soltar.
  const slider = (sel, out, key) => {
    const s = $(sel), o = $(out);
    s.addEventListener("input", () => { o.textContent = parseFloat(s.value).toFixed(1) + "×"; });
    s.addEventListener("change", () => visor.setEstilo({ [key]: parseFloat(s.value) || 1 }));
  };
  slider(".ex-fspais", "#ex-fspais-val", "fspais");
  slider(".ex-fsciu", "#ex-fsciu-val", "fsciu");

  const aplicarSemilla = () => visor.setEstilo({ semilla: $(".ex-semilla").value || d });
  $(".ex-dado").addEventListener("click", () => {
    $(".ex-semilla").value = Math.random().toString(36).slice(2, 8);
    aplicarSemilla();
  });
  $(".ex-semilla").addEventListener("keydown", (e) => { if (e.key === "Enter") aplicarSemilla(); });
  $(".ex-semilla").addEventListener("change", aplicarSemilla);
}

// ---- rótulos editables (renombrar / ocultar; persistente en servidor) ----
function cablearRotulos(visor, d) {
  const panel = $(".ex-rot-panel"), lista = $(".ex-rot-lista");
  let rotOrig = [];

  $(".ex-rot-toggle").addEventListener("click", () => {
    panel.classList.toggle("oculto");
    if (!panel.classList.contains("oculto")) cargar();
  });

  async function cargar() {
    lista.textContent = TXT.rotCargando;
    try {
      const j = await rotulos(sello, d);
      rotOrig = j.rotulos || [];
      pintar();
    } catch (e) { lista.textContent = "no se pudo cargar: " + e.message; }
  }

  function pintar() {
    lista.textContent = "";
    if (!rotOrig.length) { lista.textContent = TXT.rotVacio; return; }
    for (const tipo of ["asent", "pais", "mar", "rio"]) {
      const items = rotOrig.filter((r) => r.tipo === tipo);
      if (!items.length) continue;
      const g = document.createElement("div");
      g.className = "rot-grupo";
      const h = document.createElement("h4");
      h.textContent = `${TIPO_NOMBRE[tipo]} (${items.length})`;
      g.appendChild(h);
      for (const it of items) {
        const ov = it.override || {};
        const fila = document.createElement("div");
        fila.className = "rot-fila" + (ov.oculto ? " rot-oculto" : "");
        fila.dataset.id = it.id;
        const inp = document.createElement("input");
        inp.type = "text"; inp.maxLength = 60; inp.className = "entrada rot-nombre";
        inp.value = ov.nombre || it.nombre;
        inp.placeholder = it.nombre; inp.dataset.orig = it.nombre;
        inp.setAttribute("aria-label", `nombre de ${it.nombre}`);
        const lab = document.createElement("label");
        const chk = document.createElement("input");
        chk.type = "checkbox"; chk.className = "rot-ocultar"; chk.checked = !!ov.oculto;
        chk.addEventListener("change", () => fila.classList.toggle("rot-oculto", chk.checked));
        lab.appendChild(chk); lab.appendChild(document.createTextNode("ocultar"));
        fila.appendChild(inp); fila.appendChild(lab);
        g.appendChild(fila);
      }
      lista.appendChild(g);
    }
  }

  function recoger() {
    const ov = {};
    for (const fila of lista.querySelectorAll(".rot-fila")) {
      const inp = fila.querySelector(".rot-nombre");
      const chk = fila.querySelector(".rot-ocultar");
      const e = {};
      const nombre = inp.value.trim().slice(0, 60);
      if (chk.checked) e.oculto = true;
      if (nombre && nombre !== inp.dataset.orig) e.nombre = nombre;
      if (e.oculto || e.nombre) ov[fila.dataset.id] = e;
    }
    return ov;
  }

  $(".ex-rot-guardar").addEventListener("click", async () => {
    try {
      const j = await guardarRotulos(sello, d, recoger());
      visor.rotverBump();
      cargar();
      visor.reRender();
      aviso(TXT.rotGuardados(j.n), "ok");
    } catch (e) { if (!e.manejado) aviso("no se pudo guardar: " + e.message, "error"); }
  });
  $(".ex-rot-restaurar").addEventListener("click", async () => {
    try {
      await guardarRotulos(sello, d, {});
      visor.rotverBump();
      cargar();
      visor.reRender();
      aviso(TXT.rotRestaurados, "ok");
    } catch (e) { if (!e.manejado) aviso("no se pudo restaurar: " + e.message, "error"); }
  });
}

// ---- descarga PNG del mapa completo ----
function cablearExport(visor, d) {
  let exportando = false;
  $(".ex-exportar").addEventListener("click", async () => {
    if (exportando) return;
    const px = Math.min(8192, Math.max(512, parseInt($(".ex-px").value, 10) || 4096));
    const deco = $(".ex-deco").checked;
    const url = visor.urlExport({ deco, px });
    exportando = true;
    const cerrar = aviso(`horneando PNG en el servidor (${px} px)… los grandes tardan`, "info", 0);
    try {
      const r = await fetch(url);
      if (r.status === 403 || r.status === 429) {
        // gating del servidor (ADR-007): aviso no intrusivo con enlace a /yo
        cerrar();
        let msg = "";
        try { msg = (await r.json()).error || ""; } catch (_) { /* */ }
        avisarLimite(r.status, msg);
        return;
      }
      if (!r.ok) throw new Error("HTTP " + r.status);
      const blob = await r.blob();
      const sem = (visor.semilla || d).replace(/[^0-9a-zA-Z_-]+/g, "_").slice(0, 24);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `fantasia_${d}_${sem}_${px}px.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      cerrar();
      aviso(`PNG descargado (${px} px).`, "ok");
    } catch (e) {
      cerrar();
      aviso("no se pudo descargar: " + e.message, "error");
    } finally { exportando = false; }
  });
}

// ============================================================================
//  zoom: botones + atajos de teclado (+/- zoom, 0 reset)
// ============================================================================
function cablearZoom(visor) {
  $("#z-mas").addEventListener("click", () => visor.zoomBoton(1.2));
  $("#z-menos").addEventListener("click", () => visor.zoomBoton(1 / 1.2));
  $("#z-reset").addEventListener("click", () => visor.reset());
  window.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) return;
    if (e.key === "+" || e.key === "=") { visor.zoomBoton(1.2); e.preventDefault(); }
    else if (e.key === "-" || e.key === "_") { visor.zoomBoton(1 / 1.2); e.preventDefault(); }
    else if (e.key === "0") { visor.reset(); e.preventDefault(); }
  });
}
