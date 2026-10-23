// nav.js — cabecera sticky y pie comunes, inyectados en el DOM.
// Los estilos viven en base.css (.nav, .nav-migas, .pie). Español en la UI
// (ADR-008). Spec: ESPECIFICACION_RUTAS.md «Páginas y navegación».
//
// API PÚBLICA
//   montarNav(opciones?) -> HTMLElement <header class="nav">
//     opciones: { activa?: string, migas?: [{texto, href?}] }  (o un string,
//     equivalente a {activa}: compatibilidad con montarNav("estudio")).
//     · Sin migas -> barra de cinco:
//         Mundaria -> /  ·  Explorar -> /  ·  ＋ Nuevo mundo -> /nuevo  ·
//         Pro · $29/año -> /yo#pro  ·  Entrar | email+insignia -> /yo
//       activa resalta uno: "explorar" | "nuevo" | "pro" | "yo"
//       (alias viejos: "estudio"->explorar, "precios"->pro, "cuenta"->yo).
//     · Siempre que la página no sea la portada, la barra empieza con «‹ Volver»
//       al nivel superior (la miga anterior con href, o / si no hay).
//     · Con migas -> Mundaria › miga › … › última (la última va sin enlace,
//       aria-current="page"; también va sin enlace cualquier miga sin href)
//       y a la derecha solo Entrar/Yo.
//     La sesión se pinta después con GET /api/cuenta (api.cuenta(), memoizada:
//     la página puede llamar cuenta() sin duplicar la petición). «Pro» se
//     oculta si el plan vigente es pro o comercial. Si la API falla, queda
//     «Entrar» y «Pro» visibles (falla en silencio).
//     El header devuelto lleva `.sesion`: Promise<cuenta|null> (null si falló).
//     Idempotente: si ya hay un .nav en la página, lo devuelve sin tocarlo.
//   refrescarNav() -> Promise<cuenta|null>
//     Vuelve a pedir /api/cuenta (fresca) y repinta Entrar/Yo y «Pro»
//     (p. ej. tras salir() en /yo sin recargar).
//   montarPie({lab?}) -> HTMLElement <footer class="pie">
//     lab:true añade el enlace discreto «laboratorio» -> /lab (solo dueño).

import { MARCA, logoSVG } from "./marca.js";
import { cuenta, esPro, conSesion } from "./api.js";

const ALIAS = { estudio: "explorar", precios: "pro", cuenta: "yo" };

// escape mínimo para interpolar texto en el HTML de la barra.
function _esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function _enlace(clave, activa, href, texto, extra = "") {
  const act = clave === activa;
  return `<a class="nav-enlace${act ? " activa" : ""}" href="${href}"` +
    `${act ? ' aria-current="page"' : ""} ${extra}>${texto}</a>`;
}

function _marca(conTagline) {
  return `<a class="nav-marca" href="/" aria-label="${_esc(MARCA.nombre)} — inicio">
        ${logoSVG(30)}
        <span>${_esc(MARCA.nombre)}</span>
        ${conTagline ? `<span class="nav-tagline">${_esc(MARCA.tagline)}</span>` : ""}
      </a>`;
}

// «← Volver»: a la miga anterior con enlace (nivel superior); sin ninguna, a /.
// Es el único control de retroceso de todas las páginas: corto y siempre en
// el mismo sitio (primer elemento de la barra).
function _htmlVolver(migas) {
  let href = "/";
  for (let i = migas.length - 2; i >= 0; i--) {
    if (migas[i] && migas[i].href) { href = migas[i].href; break; }
  }
  return `<a class="nav-volver" href="${_esc(href)}" title="volver al nivel anterior">‹ Volver</a>`;
}

function _htmlMigas(migas) {
  const partes = migas.map((m, i) => {
    const ultima = i === migas.length - 1;
    const texto = _esc(m && m.texto);
    const pieza = (!ultima && m && m.href)
      ? `<a class="nav-miga" href="${_esc(m.href)}">${texto}</a>`
      : `<span class="nav-miga nav-miga-actual"${ultima ? ' aria-current="page"' : ""}>${texto}</span>`;
    return `<span class="nav-miga-sep" aria-hidden="true">›</span>${pieza}`;
  });
  return `<nav class="nav-migas" aria-label="migas de pan">
      ${_htmlVolver(migas)}
      ${_marca(false)}
      ${partes.join("")}
    </nav>`;
}

export function montarNav(opciones = {}) {
  const previa = document.querySelector(".nav");
  if (previa) return previa; // idempotente
  const op = typeof opciones === "string" ? { activa: opciones } : (opciones || {});
  const activa = ALIAS[op.activa] || op.activa || "";
  const migas = Array.isArray(op.migas) && op.migas.length ? op.migas : null;

  const sesion = _enlace("yo", activa, "/yo", "Entrar", "data-sesion");
  let cuerpo;
  if (migas) {
    cuerpo = `${_htmlMigas(migas)}
      <nav class="nav-enlaces" aria-label="cuenta">${sesion}</nav>`;
  } else {
    // páginas de primer nivel (/nuevo, /yo): volver a la portada
    const volver = activa && activa !== "explorar"
      ? `<a class="nav-volver" href="/" title="volver a Explorar">‹ Volver</a>` : "";
    cuerpo = `${volver}${_marca(true)}
      <nav class="nav-enlaces" aria-label="principal">
        ${_enlace("explorar", activa, "/", "Explorar")}
        ${_enlace("nuevo", activa, "/nuevo", "＋ Nuevo mundo")}
        ${_enlace("pro", activa, "/yo#pro", "Pro · $29/año", "data-pro")}
        ${sesion}
      </nav>`;
  }

  const header = document.createElement("header");
  header.className = migas ? "nav nav-con-migas" : "nav";
  header.innerHTML = `<div class="nav-in">${cuerpo}</div>`;
  document.body.insertAdjacentElement("afterbegin", header);
  header.sesion = _pintarSesion(header, false);
  return header;
}

export function refrescarNav() {
  const header = document.querySelector(".nav");
  if (!header) return Promise.resolve(null);
  header.sesion = _pintarSesion(header, true);
  return header.sesion;
}

// _pintarSesion(header, fresca) — refleja GET /api/cuenta en la barra:
// anónimo -> «Entrar»; con sesión -> email + insignia del plan (ambos a /yo);
// plan pro/comercial -> oculta «Pro». Devuelve la cuenta o null si falló.
async function _pintarSesion(header, fresca) {
  let c = null;
  try {
    c = await cuenta({ fresca });
  } catch (_) {
    return null; // sin API: se queda «Entrar» y «Pro» visibles
  }
  const pro = header.querySelector("[data-pro]");
  if (pro) pro.classList.toggle("oculto", esPro(c));

  const enlace = header.querySelector("[data-sesion]");
  if (!enlace) return c;
  if (!conSesion(c)) {
    enlace.classList.remove("nav-sesion-activa");
    enlace.removeAttribute("title");
    enlace.textContent = "Entrar";
    return c;
  }
  const plan = String(c.plan || "free");
  const nombre = plan.charAt(0).toUpperCase() + plan.slice(1);
  enlace.classList.add("nav-sesion-activa");
  enlace.setAttribute("title", `${c.email} · plan ${nombre}`);
  enlace.innerHTML =
    `<span class="nav-sesion-email">${_esc(c.email)}</span>` +
    `<span class="insignia insignia-pro nav-sesion-plan">${_esc(nombre)}</span>`;
  return c;
}

export function montarPie({ lab = false } = {}) {
  const previo = document.querySelector(".pie");
  if (previo) return previo; // idempotente
  const pie = document.createElement("footer");
  pie.className = "pie";
  const enlaceLab = lab
    ? `<a class="pie-lab" href="/lab">laboratorio</a>`
    : "";
  pie.innerHTML = `
    <div class="pie-in">
      <span class="pie-marca">${logoSVG(22)} ${_esc(MARCA.nombre)}</span>
      <span class="pie-lema">hecho con geología real</span>
      ${enlaceLab}
    </div>`;
  document.body.insertAdjacentElement("beforeend", pie);
  return pie;
}
