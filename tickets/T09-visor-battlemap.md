# T09 — Visor `/w/<sello>/mapa` y battlemap `/w/<sello>/<x>,<y>`

Depende de T07. Spec: «URLs de battlemap», «Visor»; grilling ronda 4 variante 4.

## Alcance
`frontend/mapa.html` + `assets/js/mapa.js` (a partir de `mundo.html`/`mundo.js`):
- Quitar selector de modo y panel de battlemap. Queda: visor (`visor.js`),
  panel de estilo (paleta, calidad con insignia 4× Pro, países, rótulos),
  descarga PNG y ★ Guardar (mundo).
- `sello` del path; `d` del endpoint `mundo()` (o `?d=`).
- Clic en el mapa → `location.href = urlBattlemap(sello, x, y)` usando la
  conversión fantasía→rejilla ya existente en `battlemap.js`.
- Migas: `[{texto: nombre, href: urlMundo}, {texto: "Mapa"}]`.
`frontend/battlemap.html` + `assets/js/battlemap-pagina.js`:
- Lienzo grande con el render (reutilizar `battlemap.js`: controles
  tema/sub/semilla/cols/rows/px/rejilla/nums, render, export PNG; Foundry y
  Roll20 solo si plan pro, si no `muroPro`). Estado inicial desde la query;
  cada cambio → `history.replaceState` con la query nueva.
- Panel flotante de controles arriba a la derecha; «⧉ Copiar enlace» y ★
  (guardar `{tipo:"battlemap", sello, x, y, query}`) en la cabecera.
- Minimapa abajo a la izquierda: imagen del mundo con el punto actual
  marcado; clic → nueva `x,y` → `location.href`.
- Ficha del lugar (nombre, bioma, altura, río/camino) desde `batallaLugar`.
- Migas: `[nombre→ficha, "Mapa"→mapa, nombreLugar]`.
- Eliminar `frontend/mundo.html` y `mundo.js` al terminar; `visor.js` y
  `battlemap.js` se conservan (ajustar si `battlemap.js` asume el panel del
  workspace).

## Aceptación
- Ambas páginas cargan sin errores de consola con una corrida real.
- Cambiar un control reescribe la URL y recargar reproduce el mismo render.
- Clic en mapa y en minimapa navegan a la URL correcta.
