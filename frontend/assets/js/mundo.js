// mundo.js — orquestador del workspace unificado /estudio/mundo (ADR-006).
// Un solo lienzo (el visor de fantasía) y tres modos: Explorar, Battlemap y
// Conquistar. Valida ?sello&d, monta la navegación, arranca el visor con la
// resolución de _capas.json y cablea los paneles laterales por modo.
// Todo el render vive en el servidor; esto es presentación (ADR-001/003).

import { montarNav, montarPie } from "./nav.js";
import {
  RE_SELLO, RE_STEM, capas, rotulos, guardarRotulos, avisarLimite,
} from "./api.js";
import { crearVisor } from "./visor.js";
import { crearBattlemap } from "./battlemap.js";
import { aviso } from "./ui.js";

// ---- textos visibles agrupados (ADR-008) ----
const TXT = {
  errQuery: "El enlace no trae un mundo válido. Vuelve al Estudio y abre un mundo desde la galería.",
  errCapas: "No se pudo leer el detalle de este mundo (¿fue borrado?). Vuelve al Estudio.",
  pistaExplorar: "rueda = zoom · arrastrar = paneo · +/− = zoom · 0 = restablecer",
  pistaBattlemap: "clic en el mapa = elegir el lugar del encuentro · rueda = zoom · arrastrar = paneo",
  rotCargando: "cargando rótulos…",
  rotVacio: "este detalle no tiene rótulos.",
  rotGuardados: (n) => `rótulos guardados (${n} cambios).`,
  rotRestaurados: "rótulos restaurados.",
};
const TIPO_NOMBRE = { asent: "Asentamientos", pais: "Países", mar: "Mares", rio: "Ríos" };

const $ = (sel) => document.querySelector(sel);

montarNav("estudio");
montarPie({ lab: false });

// ============================================================================
//  validación de la query (mismas reglas que el servidor, via api.js)
// ============================================================================
const q = new URLSearchParams(location.search);
const sello = q.get("sello") || "", d = q.get("d") || "";

function mostrarError(msg) {
  $("#ws").classList.add("oculto");
  $("#ws-error-msg").textContent = msg;
  $("#ws-error").classList.remove("oculto");
}

// ============================================================================
// Nombre sintético del mundo — mismo generador determinista que la galería
// (estudio.js), para que el usuario vea el mismo nombre en ambas páginas.
const SIL_INI = ["Val", "Mor", "Thal", "Ker", "Ael", "Dun", "Bra", "Isla", "Or", "Vey", "Cal", "Nym", "Ther", "Gal", "Rho", "Zan"];
const SIL_MED = ["do", "ra", "ve", "mi", "sha", "lu", "ta", "ri", "go", "en", "ka", "so", "dre", "va", "ni", "or"];
const SIL_FIN = ["ria", "gard", "mar", "thia", "dor", "heim", "una", "eth", "os", "ara", "wyn", "il", "onte", "ath", "ur", "ia"];
function nombreMundo(clave) {
  let h = 0;
  for (const c of clave) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return SIL_INI[h % 16] + SIL_MED[(h >>> 4) % 16] + SIL_FIN[(h >>> 8) % 16];
}

if (!RE_SELLO.test(sello) || !RE_STEM.test(d)) {
  mostrarError(TXT.errQuery);
} else {
  arrancar();
}

async function arrancar() {
  $(".ws-mundo").textContent = nombreMundo(d);
  $("#ws-sello").textContent = `${sello} · ${d}`;
  document.title = `${nombreMundo(d)} — Mundaria`;

  // resolución del detalle: la necesita el visor y la conversión de coordenadas.
  let info;
  try {
    info = await capas(sello, d);
  } catch (e) {
    mostrarError(TXT.errCapas);
    return;
  }
  $("#ws").classList.remove("oculto");

  const elVisor = $("#visor");
  const visor = crearVisor({ sello, d, elVisor });
  visor.onEstado = (txt, err) => {
    const el = $("#ws-estado");
    el.textContent = txt || "";
    el.classList.toggle("es-error", !!err);
    $("#z-val").textContent = "×" + (visor.zoom >= 10 ? visor.zoom.toFixed(0) : visor.zoom.toFixed(1));
  };
  visor.setEstilo({ semilla: d });
  $(".ex-semilla").value = d;
  visor.cargar(info.resolucion);

  cablearExplorar(visor);
  const battlemap = crearBattlemap({ sello, d, panel: $('[data-panel="battlemap"]'), visor });
  cablearModos(visor, battlemap);
  cablearZoom(visor);
  $("#vs-pista").textContent = TXT.pistaExplorar;
}

// ============================================================================
//  modos (pestañas)
// ============================================================================
function cablearModos(visor, battlemap) {
  const pestanas = document.querySelectorAll(".pestanas .pestana");
  const paneles = document.querySelectorAll(".ws-modo-panel");
  const pistas = {
    explorar: TXT.pistaExplorar, battlemap: TXT.pistaBattlemap,
  };
  let actual = "explorar";

  function ir(modo) {
    // conquistar ya no es un panel: es el videojuego, otra página (misma
    // pestaña del navegador). Salimos de aquí sin marcar pestaña activa.
    if (modo === "conquistar") {
      location.href = `/juego?sello=${encodeURIComponent(sello)}&d=${encodeURIComponent(d)}`;
      return;
    }
    if (modo === actual) return;
    // salir del modo anterior
    if (actual === "battlemap") battlemap.desactivar();
    actual = modo;
    for (const p of pestanas) {
      const on = p.dataset.modo === modo;
      p.classList.toggle("activa", on);
      p.setAttribute("aria-selected", on ? "true" : "false");
    }
    for (const pan of paneles)
      pan.classList.toggle("oculto", pan.dataset.panel !== modo);
    document.body.dataset.modo = modo;
    $("#vs-pista").textContent = pistas[modo] || "";
    if (modo === "battlemap") battlemap.activar();
  }

  for (const p of pestanas) p.addEventListener("click", () => ir(p.dataset.modo));
  document.body.dataset.modo = "explorar";

  // deep-link: ?modo=battlemap abre el workspace en ese modo; ?modo=conquistar
  // redirige al videojuego (así los enlaces viejos siguen funcionando)
  const inicial = q.get("modo");
  if (inicial === "conquistar" || inicial in pistas) ir(inicial);
}

// ============================================================================
//  MODO EXPLORAR: estilo, capas, semilla, rótulos, export
// ============================================================================
function cablearExplorar(visor) {
  $(".ex-paleta").addEventListener("change", (e) => visor.setEstilo({ paleta: e.target.value }));
  $(".ex-calidad").addEventListener("change", (e) => visor.setEstilo({ calidad: parseInt(e.target.value, 10) }));

  const capasCbs = document.querySelectorAll(".ex-cap");
  for (const cb of capasCbs) {
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

  cablearRotulos(visor);
  cablearExport(visor);
}

// ---- rótulos editables (renombrar / ocultar; persistente en servidor) ----
function cablearRotulos(visor) {
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
    } catch (e) { aviso("no se pudo guardar: " + e.message, "error"); }
  });
  $(".ex-rot-restaurar").addEventListener("click", async () => {
    try {
      await guardarRotulos(sello, d, {});
      visor.rotverBump();
      cargar();
      visor.reRender();
      aviso(TXT.rotRestaurados, "ok");
    } catch (e) { aviso("no se pudo restaurar: " + e.message, "error"); }
  });
}

// ---- export PNG del mapa completo ----
function cablearExport(visor) {
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
        // gating del servidor (ADR-007): aviso no intrusivo con enlace a /cuenta
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
      aviso(`PNG exportado (${px} px).`, "ok");
    } catch (e) {
      cerrar();
      aviso("no se pudo exportar: " + e.message, "error");
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
