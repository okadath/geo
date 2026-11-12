// battlemap-pagina.js — página /w/<sello>/<x>,<y> (ESPECIFICACION_RUTAS «URLs
// de battlemap»). x,y son enteros de la rejilla del mundo (los rx,ry de
// /api/batalla/*). El estilo viaja en la query con los nombres de la API de
// batalla (tema, sub, semilla, cols, rows, px, rejilla, nums, momento,
// estacion); cada cambio la reescribe con history.replaceState, así recargar
// reproduce el mismo render. Reutiliza battlemap.js (controles, render,
// export) sin visor y añade minimapa, copiar enlace y ★ Guardar.
// Todo el render y el gating viven en el servidor; esto es presentación.

import { montarNav, montarPie } from "./nav.js";
import {
  RE_SELLO, mundo, cuenta, esPro, conSesion, guardar,
  urlMundo, urlBattlemap,
} from "./api.js";
import { crearBattlemap, CLAVES_QUERY } from "./battlemap.js";
import { aviso, modal, cuadroCorreo, muroPro } from "./ui.js";

// ---- textos visibles agrupados (ADR-008) ----
const TXT = {
  errUrl: "El enlace no trae un mundo y un punto válidos.",
  errMundo: "Este mundo no existe o ya no está disponible.",
  errCatalogo: "No se pudo cargar el battlemap de este mundo.",
  copiado: "Enlace copiado.",
  noCopiado: "No se pudo copiar; copia la URL de la barra del navegador.",
  guardado: "Battlemap guardado en tu cuenta.",
  yaGuardado: "Este battlemap ya estaba en tus guardados.",
  guardarTitulo: "Guarda este battlemap",
  guardarTexto: "Entra con tu correo para guardarlo; sin contraseñas.",
  muroVTT: "Exportar a Foundry VTT y Roll20 es parte del plan Pro.",
  lugarMar: "mar abierto",
};

const $ = (sel) => document.querySelector(sel);

// ---- path y query: /w/<sello>/<x>,<y>?d=&tema=&… ----
const partes = location.pathname.split("/");
const sello = decodeURIComponent(partes[2] || "");
const m = /^([0-9]+),([0-9]+)$/.exec(partes[3] || "");
let x = m ? parseInt(m[1], 10) : NaN;
let y = m ? parseInt(m[2], 10) : NaN;
const qIni = new URLSearchParams(location.search);
const dQuery = qIni.get("d") || "";
const inicial = {};
for (const k of CLAVES_QUERY) if (qIni.has(k)) inicial[k] = qIni.get(k);

function mostrarError(msg) {
  $("#ws").classList.add("oculto");
  $("#ws-error-msg").textContent = msg;
  $("#ws-error").classList.remove("oculto");
}

montarPie({ lab: false });
if (!RE_SELLO.test(sello) || !Number.isFinite(x) || !Number.isFinite(y)) {
  montarNav({ migas: [{ texto: "Battlemap" }] });
  mostrarError(TXT.errUrl);
} else {
  arrancar();
}

async function arrancar() {
  let mu;
  try {
    mu = await mundo(sello, dQuery || undefined);
  } catch (e) {
    montarNav({ migas: [{ texto: "Battlemap" }] });
    mostrarError(e.status === 404 ? TXT.errMundo : `${TXT.errMundo} (${e.message})`);
    return;
  }
  const d = mu.d;
  // d explícito en la URL -> se conserva en los enlaces; si no, URLs limpias
  const qD = dQuery ? { d } : undefined;
  // «Mapa» es la página del mundo (/w/<sello>): desde ahí se vuelve al rol
  const nav = montarNav({
    migas: [
      { texto: `Mapa · ${mu.nombre}`, href: urlMundo(sello, qD) },
      { texto: `${x}, ${y}` },
    ],
  });
  document.title = `${mu.nombre} · ${x}, ${y} — Pangeira`;
  $("#ws").classList.remove("oculto");

  // URL de la página para un punto y una query de estilo
  const urlPara = (px, py, estilo) =>
    urlBattlemap(sello, px, py, { ...(qD || {}), ...(estilo || {}) });

  const bm = crearBattlemap({
    sello, d,
    panel: $("#ws"),          // cabecera (título) + lienzo + panel flotante
    imagen: $(".bp-render"),
    inicial,
    onCambio: (q) => history.replaceState(null, "", urlPara(x, y, q)),
    onLugar: (g) => {
      const nombre = nombreLugar(mu.lugares, g);
      const miga = nav.querySelector(".nav-miga-actual");
      if (miga) miga.textContent = nombre;
      document.title = `${nombre} · ${mu.nombre} — Pangeira`;
    },
    antesVTT: async () => {
      if (await pro()) return true;
      const mo = modal({ titulo: "Plan Pro" });
      mo.querySelector(".modal-cuerpo").appendChild(muroPro(TXT.muroVTT));
      return false;
    },
  });

  // catálogo + resolución; el punto se acota a la rejilla real del detalle
  const ok = await bm.cargarCatalogo();
  if (!ok) { mostrarError(TXT.errCatalogo); return; }
  const [nx, ny] = bm.resolucion || [1, 1];
  x = Math.min(Math.max(0, x), nx - 1);
  y = Math.min(Math.max(0, y), ny - 1);
  bm.elegir(x, y);

  montarMinimapa(mu.imagen, nx, ny, (nxp, nyp) => {
    location.href = urlPara(nxp, nyp, bm.query());
  });
  gatingVTT();
  cablearCabecera();
  cablearPlegar();
}

// nombre del lugar para la miga: lugar destacado exacto, asentamiento aquí,
// bioma o mar; si no, las coordenadas.
function nombreLugar(lugares, g) {
  const dest = (lugares || []).find((l) => l.x === x && l.y === y);
  if (dest && dest.nombre) return dest.nombre;
  if (g && g.asent && g.asent.aqui && g.asent.nombre) return g.asent.nombre;
  if (g && g.es_mar) return TXT.lugarMar;
  if (g && g.bioma && g.bioma.nombre) return g.bioma.nombre;
  return `${x}, ${y}`;
}

// ---- plan: Foundry/Roll20 solo con Pro (el servidor manda; aquí solo UI) ----
async function pro() {
  try { return esPro(await cuenta()); } catch (_) { return false; }
}
async function gatingVTT() {
  if (await pro()) return;
  for (const sel of [".bm-foundry", ".bm-roll20"]) $(sel).classList.add("oculto");
  $(".bp-muro").appendChild(muroPro(TXT.muroVTT));
}

// ---- minimapa: imagen del mundo + punto; clic -> otro x,y ----
function montarMinimapa(src, nx, ny, alElegir) {
  const caja = $("#mini"), img = caja.querySelector(".bp-mini-img");
  const punto = caja.querySelector(".bp-mini-punto");
  caja.style.setProperty("--ar", `${nx} / ${ny}`);
  img.src = src;
  punto.style.left = `${((x + 0.5) / nx) * 100}%`;
  punto.style.top = `${((y + 0.5) / ny) * 100}%`;
  punto.style.display = "block";
  caja.addEventListener("click", (e) => {
    const r = img.getBoundingClientRect();   // sin el borde de la caja
    const fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
    const px = Math.min(nx - 1, Math.max(0, Math.floor(fx * nx)));
    const py = Math.min(ny - 1, Math.max(0, Math.floor(fy * ny)));
    alElegir(px, py);
  });
}

// ---- cabecera: ⧉ Copiar enlace y ★ Guardar (tipo battlemap) ----
function cablearCabecera() {
  $("#copiar").addEventListener("click", async () => {
    const url = location.href;
    try {
      await navigator.clipboard.writeText(url);
      aviso(TXT.copiado, "ok");
    } catch (_) {
      // sin permiso de portapapeles (http, iframes): copia clásica
      const ta = document.createElement("textarea");
      ta.value = url; ta.setAttribute("readonly", "");
      ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { /* */ }
      ta.remove();
      aviso(ok ? TXT.copiado : TXT.noCopiado, ok ? "ok" : "error");
    }
  });

  const pedirCorreo = () => {
    const mo = modal({ titulo: TXT.guardarTitulo });
    cuadroCorreo({ montarEn: mo.querySelector(".modal-cuerpo"), titulo: "", texto: TXT.guardarTexto });
  };
  $("#guardar").addEventListener("click", async () => {
    let c = null;
    try { c = await cuenta(); } catch (_) { /* sin API: se pide correo */ }
    if (!conSesion(c)) { pedirCorreo(); return; }
    try {
      const r = await guardar({ tipo: "battlemap", sello, x, y, query: location.search });
      aviso(r && r.nuevo === false ? TXT.yaGuardado : TXT.guardado, "ok");
    } catch (e) {
      if (e.status === 401) pedirCorreo();
      else aviso("no se pudo guardar: " + e.message, "error");
    }
  });
}

// ---- plegar el panel flotante (deja ver el render entero) ----
function cablearPlegar() {
  const panel = $(".bp-panel"), boton = $("#plegar");
  boton.addEventListener("click", () => {
    const plegado = panel.classList.toggle("plegado");
    boton.setAttribute("aria-expanded", plegado ? "false" : "true");
  });
}
