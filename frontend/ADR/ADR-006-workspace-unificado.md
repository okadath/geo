# ADR-006 — Workspace unificado: fantasía y battlemaps en una sola página

**Estado:** aceptada · 2026-07-17

## Contexto

`/fantasia` y `/batalla` son páginas separadas que comparten `?sello&d` pero
no se conocen; el enlace cruzado existe sin llevar el punto seleccionado. El
pitch entero del producto es la integración («del planeta al encuentro»,
PLATAFORMA §1.1); dos pestañas del navegador lo matan.

## Decisión

`/estudio/mundo` es **un solo workspace** con el mapa de fantasía como lienzo
principal y tres modos:

- **Explorar** — pan/zoom del mapa fantasía (sectores nítidos vía
  `/api/fantasia/sector`), estilo (paleta, capas, decoración), editor de
  rótulos, export PNG.
- **Battlemap** — el modo estrella: al activarlo, **clic en cualquier punto
  del mapa de fantasía** consulta `/api/batalla/lugar` con ese punto, muestra
  la ficha del lugar y genera el battlemap (`/api/batalla/mapa`) en un panel
  lateral con sus controles (tema, tamaño, momento, estación, rejilla) y
  export PNG / Foundry / Roll20. La conversión de coordenadas
  fantasía→rejilla usa la resolución de `_capas.json`, común a ambos módulos.
- **Conquistar** — tarjeta que lanza el juego existente (`/juego?sello&d`)
  en la misma pestaña; el juego no se toca (ADR-001).

## Consecuencias

- El flujo demo completo (mundo → mapa → clic → battlemap → export) ocurre en
  una sola página: es el video de marketing en vivo y la demo del free tier.
- `regiones.html` deja de ser el hub de navegación (queda accesible desde
  `/lab`); su rol informativo lo cubre la ficha de lugar del modo Battlemap.
- El panel lateral de battlemap duplica controles que ya existen en
  `batalla.html`; el costo de duplicación se paga una vez y compra el flujo
  integrado que ningún competidor tiene.
