// ficha.js — ficha compartible del mundo `/w/<sello>` (T08). Lee el sello del
// path, pide la ficha al servidor (GET /api/w/<sello>) y la pinta: imagen,
// datos, Abrir mapa / Jugar, copiar enlace, ★ Guardar, Remezclar semilla,
// conmutador de visibilidad (solo dueño), lugares destacados y muro Pro.
// Solo presentación: nombre, datos, lugares, visibilidad y gating los decide
// el servidor. Las metas OG ya vienen rellenas en el HTML servido.

import { montarNav, montarPie } from "/app/js/nav.js";
import {
  RE_SELLO, RE_STEM, mundo, visibilidad, cuenta, esPro, conSesion, guardar,
  urlMundo, urlMapa, urlJugar, urlBattlemap,
} from "/app/js/api.js";
import { aviso, modal, cuadroCorreo, muroPro } from "/app/js/ui.js";

// textos visibles de la página (agrupados para la localización, ADR-008)
const TXT = {
  titulo: (n) => `${n} — Mundaria`,
  noExiste: "Este mundo no existe",
  noExisteTexto: "Puede que el enlace esté mal copiado o que el mundo se haya borrado.",
  errCarga: "No se pudo cargar el mundo",
  errCargaTexto: "El servidor no respondió. Recarga la página en un momento.",
  imagen: (n) => `Mapa de fantasía de ${n}`,
  publico: "Público",
  privado: "Privado",
  tuyo: "Tuyo",
  copiado: "Enlace copiado.",
  errCopiar: "No se pudo copiar; copia la dirección de la barra.",
  guardado: "Guardado en tus mundos.",
  yaGuardado: "Ya estaba en tus guardados.",
  guardadoBoton: "★ Guardado",
  errGuardar: "No se pudo guardar el mundo.",
  guardarTitulo: "Guarda este mundo",
  guardarTexto: "Escribe tu correo y te enviamos un enlace para entrar; sin contraseñas. Al volver, pulsa ★ Guardar de nuevo.",
  remezclarMuro: "Remezclar una semilla genera un mundo nuevo y propio: es parte del plan Pro.",
  publicadoSi: "Aparece en Explorar para todo el mundo.",
  publicadoNo: "No aparece en Explorar; el enlace sigue funcionando para quien lo tenga.",
  errVisibilidad: "No se pudo cambiar la visibilidad.",
  proFinal: "Con Pro descargas sin marca de agua (mapa 8K, battlemap 140 px), exportas a Foundry y Roll20, y generas y remezclas tus propios mundos.",
  reglas: {
    cruce: "Cruce de río y camino",
    paso: "Paso de montaña",
    costa: "Costa",
    capital: "Capital",
    bosque: "Bosque denso",
    desierto: "Desierto",
  },
  abrirBattlemap: "Abrir battlemap ▸",
};

function _num(v) {
  return typeof v === "number"
    ? v.toLocaleString("es", { maximumFractionDigits: 2 }) : String(v);
}
function _fecha(v) {
  const f = new Date(v);
  return isNaN(f) ? String(v) : f.toLocaleDateString("es", {
    day: "numeric", month: "long", year: "numeric",
  });
}

// etiquetas y formato de los metadatos que pueda traer la ficha (orden fijo;
// solo se pintan los presentes)
const DATOS = [
  ["semilla", "Semilla", String],
  ["paises", "Países", String],
  ["asentamientos", "Asentamientos", String],
  ["placas", "Placas", String],
  ["continentes", "Continentes", _num],
  ["mar", "Mar", (v) => (typeof v === "number" && v <= 1
    ? `${Math.round(v * 100)} %` : String(v))],
  ["clima", "Clima", String],
  ["plumas", "Plumas del manto", String],
  ["tiempo", "Tiempo geológico", (v) => `${v} pasos`],
  ["resolucion", "Rejilla", (v) => `${v} × ${v}`],
  ["creado", "Creado", _fecha],
];

const $ = (sel) => document.querySelector(sel);

// ---- identidad: sello del path, d opcional en la query ---------------------
const partes = location.pathname.split("/").filter(Boolean);   // ["w", sello]
const sello = decodeURIComponent(partes[1] || "");
const dQuery = new URLSearchParams(location.search).get("d") || "";
const d = RE_STEM.test(dQuery) ? dQuery : undefined;
const q = d ? { d } : undefined;      // se propaga a mapa/jugar/battlemap

let ficha = null;

// ---- error elegante ---------------------------------------------------------
function mostrarError(titulo, texto) {
  montarNav({ migas: [{ texto: titulo }] });
  montarPie();
  document.title = TXT.titulo(titulo);
  for (const id of ["#fi-cabeza", "#fi-lugares", "#fi-pro"]) {
    $(id).classList.add("oculto");
  }
  $("#fi-error h1").textContent = titulo;
  $("#fi-error-texto").textContent = texto;
  $("#fi-error").classList.remove("oculto");
}

// ---- pintado ----------------------------------------------------------------
function pintarCabeza(f) {
  document.title = TXT.titulo(f.nombre);
  $("#fi-nombre").textContent = f.nombre;
  $("#fi-sello").textContent = `#${f.sello}`;

  const img = $("#fi-img");
  img.alt = TXT.imagen(f.nombre);
  img.addEventListener("load", () => img.classList.add("cargada"));
  img.addEventListener("error", () => {
    img.closest(".fi-imagen").classList.add("sin-imagen");
  });
  img.src = f.imagen;

  pintarInsignias(f);

  const meta = f.meta || {};
  const filas = [];
  for (const [clave, etiqueta, fmt] of DATOS) {
    const v = meta[clave];
    if (v === undefined || v === null || v === "") continue;
    const dt = document.createElement("dt");
    dt.textContent = etiqueta;
    const dd = document.createElement("dd");
    dd.textContent = fmt(v);
    if (clave === "semilla") dd.classList.add("mono");
    const fila = document.createElement("div");
    fila.append(dt, dd);
    filas.push(fila);
  }
  $("#fi-tabla").replaceChildren(...filas);

  $("#fi-mapa").href = urlMapa(f.sello, q);
  $("#fi-jugar").href = urlJugar(f.sello, q);
  $("#fi-cabeza").setAttribute("aria-busy", "false");
}

function pintarInsignias(f) {
  const ins = [];
  const pub = document.createElement("span");
  pub.className = "insignia" + (f.publico ? " insignia-mar" : "");
  pub.textContent = f.publico ? TXT.publico : TXT.privado;
  ins.push(pub);
  if (f.es_dueno) {
    const tuyo = document.createElement("span");
    tuyo.className = "insignia insignia-pro";
    tuyo.textContent = TXT.tuyo;
    ins.push(tuyo);
  }
  $("#fi-insignias").replaceChildren(...ins);
}

function pintarLugares(f) {
  const lugares = Array.isArray(f.lugares) ? f.lugares : [];
  if (!lugares.length) return;
  $("#fi-rejilla").replaceChildren(...lugares.map((l) => {
    const a = document.createElement("a");
    a.className = "tarjeta tarjeta-activable fi-lugar";
    a.href = urlBattlemap(f.sello, l.x, l.y, q);
    a.setAttribute("role", "listitem");

    const regla = document.createElement("span");
    regla.className = "insignia";
    regla.textContent = TXT.reglas[l.regla] || l.regla || "";
    const nombre = document.createElement("h3");
    nombre.className = "fi-lugar-nombre";
    nombre.textContent = l.nombre || `${l.x}, ${l.y}`;
    const det = document.createElement("p");
    det.className = "tenue fi-lugar-det";
    det.textContent = [l.bioma, `${l.x}, ${l.y}`].filter(Boolean).join(" · ");
    const ir = document.createElement("span");
    ir.className = "fi-lugar-ir";
    ir.textContent = TXT.abrirBattlemap;

    a.append(regla, nombre, det, ir);
    return a;
  }));
  $("#fi-lugares").classList.remove("oculto");
}

// ---- acciones -----------------------------------------------------------------
async function copiarEnlace() {
  const url = location.origin + urlMundo(sello, q);
  try {
    await navigator.clipboard.writeText(url);
    aviso(TXT.copiado, "ok");
  } catch (_) {
    // sin permiso de portapapeles (http no local, navegador viejo): textarea
    const ta = document.createElement("textarea");
    ta.value = url;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    ta.remove();
    aviso(ok ? TXT.copiado : TXT.errCopiar, ok ? "ok" : "error");
  }
}

async function cuentaSegura() {
  try { return await cuenta(); } catch (_) { return null; }
}

async function alGuardar(e) {
  const boton = e.currentTarget;
  const c = await cuentaSegura();
  if (!conSesion(c)) {
    const m = modal({ titulo: TXT.guardarTitulo });
    cuadroCorreo({
      volver: location.pathname + location.search,
      montarEn: m.querySelector(".modal-cuerpo"),
      titulo: "",
      texto: TXT.guardarTexto,
    });
    const campo = m.querySelector("input[type=email]");
    if (campo) campo.focus();
    return;
  }
  boton.disabled = true;
  try {
    const r = await guardar({ tipo: "mundo", sello });
    aviso(r && r.nuevo === false ? TXT.yaGuardado : TXT.guardado, "ok");
    boton.textContent = TXT.guardadoBoton;
  } catch (err) {
    aviso(err.message || TXT.errGuardar, "error");
  } finally {
    boton.disabled = false;
  }
}

async function alRemezclar() {
  const c = await cuentaSegura();
  const semilla = ficha && ficha.meta ? ficha.meta.semilla : undefined;
  if (esPro(c)) {
    location.href = "/nuevo" + (semilla !== undefined && semilla !== null
      ? `?semilla=${encodeURIComponent(semilla)}` : "");
    return;
  }
  const caja = $("#fi-muro-remezcla");
  if (!caja.firstChild) caja.append(muroPro(TXT.remezclarMuro));
  caja.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// conmutador de visibilidad: solo si el servidor dice que la sesión es la del
// dueño (es_dueno; el email del dueño solo se revela a él mismo)
function montarVisibilidad(f) {
  if (!f.es_dueno) return;
  const casilla = $("#fi-publico");
  const nota = $("#fi-visibilidad-nota");
  const pintar = (pub) => {
    casilla.checked = !!pub;
    nota.textContent = pub ? TXT.publicadoSi : TXT.publicadoNo;
  };
  pintar(f.publico);
  casilla.addEventListener("change", async () => {
    const quiere = casilla.checked;
    casilla.disabled = true;
    try {
      const r = await visibilidad(sello, quiere);
      f.publico = !!r.publico;
      pintar(f.publico);
      pintarInsignias(f);
    } catch (err) {
      pintar(f.publico);
      aviso(err.message || TXT.errVisibilidad, "error");
    } finally {
      casilla.disabled = false;
    }
  });
  $("#fi-visibilidad").classList.remove("oculto");
}

async function montarMuroFinal() {
  const c = await cuentaSegura();
  if (esPro(c)) return;
  const sec = $("#fi-pro");
  sec.replaceChildren(muroPro(TXT.proFinal));
  sec.classList.remove("oculto");
}

// ---- arranque -------------------------------------------------------------------
(async function arrancar() {
  if (!RE_SELLO.test(sello)) {
    mostrarError(TXT.noExiste, TXT.noExisteTexto);
    return;
  }
  try {
    ficha = await mundo(sello, d);
  } catch (err) {
    if (err.status === 404) mostrarError(TXT.noExiste, TXT.noExisteTexto);
    else mostrarError(TXT.errCarga, TXT.errCargaTexto);
    return;
  }

  montarNav({ migas: [{ texto: ficha.nombre }] });
  montarPie();
  pintarCabeza(ficha);
  pintarLugares(ficha);
  montarVisibilidad(ficha);
  montarMuroFinal();

  $("#fi-copiar").addEventListener("click", copiarEnlace);
  $("#fi-guardar").addEventListener("click", alGuardar);
  $("#fi-remezclar").addEventListener("click", alRemezclar);
})();
