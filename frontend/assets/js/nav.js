// nav.js — cabecera sticky y pie comunes, inyectados en el DOM.
// Los estilos viven en base.css (.nav, .pie). Español en la UI (ADR-008).

import { MARCA, logoSVG } from "./marca.js";

// montarNav(activa) — inserta el header sticky al inicio de <body>.
//   activa: clave del enlace vigente ("estudio" | "precios" | ...) para
//   resaltarlo; opcional.
export function montarNav(activa = "") {
  if (document.querySelector(".nav")) return; // idempotente
  const header = document.createElement("header");
  header.className = "nav";
  header.innerHTML = `
    <div class="nav-in">
      <a class="nav-marca" href="/" aria-label="${MARCA.nombre} — inicio">
        ${logoSVG(30)}
        <span>${MARCA.nombre}</span>
        <span class="nav-tagline">${MARCA.tagline}</span>
      </a>
      <nav class="nav-enlaces">
        <a class="nav-enlace${activa === "estudio" ? " activa" : ""}"
           href="/estudio">Estudio</a>
        <a class="nav-enlace${activa === "precios" ? " activa" : ""}"
           href="/#precios">Precios</a>
        <span class="insignia insignia-beta">${MARCA.version}</span>
      </nav>
    </div>`;
  document.body.insertAdjacentElement("afterbegin", header);
}

// montarPie(opciones) — inserta el footer al final de <body>.
//   opciones.lab: true muestra el enlace discreto «laboratorio» -> /lab
//   (solo para el dueño; ADR-004: no aparece en ninguna navegación general).
export function montarPie({ lab = false } = {}) {
  if (document.querySelector(".pie")) return; // idempotente
  const pie = document.createElement("footer");
  pie.className = "pie";
  const enlaceLab = lab
    ? `<a class="pie-lab" href="/lab">laboratorio</a>`
    : "";
  pie.innerHTML = `
    <div class="pie-in">
      <span class="pie-marca">${logoSVG(22)} ${MARCA.nombre}</span>
      <span class="pie-lema">hecho con geología real</span>
      ${enlaceLab}
    </div>`;
  document.body.insertAdjacentElement("beforeend", pie);
}
