// marca.js — identidad de marca en un solo lugar (ADR-002).
// Cambiar el nombre/dominio del producto es editar este archivo y el logo.

export const MARCA = {
  nombre: "Mundaria",
  tagline: "Del planeta al encuentro",
  version: "beta",
};

// logoSVG(px) -> string con un SVG inline elegante: un planeta con meridianos
// y una rosa de vientos superpuesta. Todos los trazos usan currentColor, de
// modo que hereda el oro (o el color que le dé el contexto) del CSS.
export function logoSVG(px = 28) {
  const s = Number(px) || 28;
  return `<svg class="logo" width="${s}" height="${s}" viewBox="0 0 48 48"
    fill="none" stroke="currentColor" stroke-width="1.6"
    stroke-linecap="round" stroke-linejoin="round" role="img"
    aria-label="${MARCA.nombre}">
  <!-- planeta -->
  <circle cx="24" cy="24" r="18"/>
  <!-- meridianos y paralelos (líneas de un globo) -->
  <ellipse cx="24" cy="24" rx="7" ry="18"/>
  <line x1="6" y1="24" x2="42" y2="24"/>
  <path d="M9.5 14 A24 24 0 0 0 38.5 14" opacity="0.75"/>
  <path d="M9.5 34 A24 24 0 0 1 38.5 34" opacity="0.75"/>
  <!-- rosa de vientos: estrella de cuatro puntas sobre el planeta -->
  <path d="M24 9 L27 21 L39 24 L27 27 L24 39 L21 27 L9 24 L21 21 Z"
        fill="currentColor" fill-opacity="0.14"/>
  <path d="M24 9 L27 21 L39 24 L27 27 L24 39 L21 27 L9 24 L21 21 Z"/>
  <circle cx="24" cy="24" r="2.2" fill="currentColor" stroke="none"/>
</svg>`;
}
