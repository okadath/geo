# ADR-008 — Estética: tema «atlas nocturno», tokens CSS, tipografía del sistema

**Estado:** aceptada · 2026-07-17

## Contexto

Las páginas actuales no comparten estilo (cada HTML trae su CSS ad-hoc). El
producto compite contra Inkarnate/Dungeondraft, cuyas UIs son oscuras y dejan
que el mapa sea el color. El público (DMs, worldbuilders) responde a la
estética cartográfica/pergamino.

## Decisión

Un solo sistema de diseño en `assets/css/tokens.css` + `base.css`, tema único
**«atlas nocturno»**: fondos azul-tinta profundos, texto marfil, **oro viejo**
como color de acción, acentos pergamino para lo cartográfico. Tipografía del
sistema (serif tipo Palatino/Georgia para display — voz «atlas antiguo»;
sans del sistema para UI) — cero webfonts, cero peticiones externas, todo
sirve offline.

Tokens principales: `--fondo #0c111c`, `--panel #161f31`, `--borde #2a3550`,
`--tinta #e9e2d0`, `--tinta-suave #98a2b3`, `--oro #d4a94e`,
`--pergamino #e8d5a8`, `--mar #4a8fb5`, radios 10px, sombras suaves.
Componentes por clase: `.btn`/`.btn-oro`/`.btn-fantasma`, `.tarjeta`,
`.insignia`, `.pestanas`, `.campo`, `.barra-progreso`, `.modal`, `.aviso`.

Idioma de la UI: **español** (mercado inicial y idioma del código); la
estructura deja los strings visibles agrupados por página para facilitar la
localización EN que el marketing exigirá (NEGOCIO §4).

## Consecuencias

- Coherencia visual inmediata entre landing, estudio y workspace; las páginas
  legacy (`/juego`, `/lab`) quedan fuera del sistema hasta que toque.
- Sin dependencias externas: la página funciona en localhost sin internet,
  igual que el resto del producto.
