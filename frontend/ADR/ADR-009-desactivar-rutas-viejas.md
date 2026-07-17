# ADR-009 — Desactivar las rutas viejas: un solo embudo por `/estudio/mundo`

**Estado:** aceptada · 2026-07-17 · sustituye el «rutas viejas intactas» de ADR-004

## Contexto

Tras el refactor (ADR-004/006) convivían dos redes de navegación: la nueva
(`/` → `/estudio` → `/estudio/mundo`) y la vieja (`/regiones` como hub con
botones a `/fantasia`, `/batalla` y `/juego`, y cada una enlazando de vuelta a
las demás). El recorrido era confuso: dos caminos distintos llegaban a lo
mismo y las páginas viejas seguían siendo alcanzables por URL directa.

## Decisión

El embudo de marketing manda: **todo pasa por el workspace**, que es la demo
en vivo del producto («del planeta al encuentro», ADR-006).

Preponderancia de rutas (de más a menos importante para marketing):

1. `/` — landing: única puerta de entrada, CTA «Probar gratis».
2. `/estudio` — galería: retención, crear/abrir mundos.
3. `/estudio/mundo?sello&d[&modo=…]` — workspace: la demo completa; acepta
   `modo=explorar|battlemap|conquistar` como deep-link compartible.
4. `/juego?sello&d` — sigue viva (ADR-004: el juego no se toca) pero solo se
   llega a ella desde el modo Conquistar; su «volver» regresa al workspace.

Rutas desactivadas / internas:

- `/fantasia?sello&d` → **302** a `/estudio/mundo?sello&d` (modo Explorar es
  el mapa de fantasía).
- `/batalla?sello&d` → **302** a `/estudio/mundo?sello&d&modo=battlemap`.
- `/regiones` — deja de ser hub: pierde los botones a fantasía/batalla y
  queda como herramienta de inspección enlazada solo desde `/lab`.
- `fantasia.html` y `batalla.html` quedan sin ruta (código muerto, borrable
  cuando el panel battlemap del workspace esté a la par).

## Consecuencias

- Un solo recorrido: landing → estudio → workspace → (juego). Nadie cae en
  una página vieja: los marcadores/enlaces antiguos aterrizan en el workspace
  con el mundo y el modo correctos gracias a las redirecciones con query.
- El menú «⚔ Conquistar» de la galería y el «volver» del juego usan el
  deep-link `&modo=conquistar`, reforzando el workspace como único hub.
