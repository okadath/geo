# T06 — Rutas de páginas nuevas, redirecciones, OG de la ficha

Depende de T02 T03 T04 T05. Spec: tabla de rutas, «Redirecciones», «Páginas y navegación» (servidor).

## Alcance (`servidor/rutas_paginas.py`)
- Nuevas: `GET /` → `frontend/explorar.html`; `GET /w/{sello}` → `ficha.html`
  con plantillado OG; `GET /w/{sello}/mapa` → `mapa.html`;
  `GET /w/{sello}/{x},{y}` (`[0-9]+,[0-9]+`) → `battlemap.html`;
  `GET /w/{sello}/jugar` → `juego.html` (raíz del repo); `GET /nuevo` →
  `nuevo.html`; `GET /yo` → `yo.html`.
  Mientras un HTML no exista (T08–T10), servir `frontend/_pendiente.html`
  mínimo (crearlo) para que la ruta responda 200; T08–T10 lo sustituyen.
- Validar `sello` con `RE_SELLO` → 404 JSON si no casa.
- OG en la ficha: el HTML lleva marcadores `{{og_titulo}}`, `{{og_imagen}}`,
  `{{og_descripcion}}`, `{{og_url}}`; el servidor los sustituye con datos de
  `servidor.mundos` (escape HTML). Mundo inexistente → ficha con marcadores
  vacíos (el front muestra el error), no 404 HTML.
- Redirecciones 302 según la tabla de la spec, conservando `d` como query:
  `/estudio`→`/`; `/estudio/mundo`→`/w/<sello>` (`modo=battlemap`→`/mapa`,
  `modo=conquistar`→`/jugar`); `/fantasia`,`/batalla`→`/w/<sello>/mapa`;
  `/juego`→`/w/<sello>/jugar`; `/cuenta`→`/yo`; `/entrar`→`/yo`;
  `/pro`→`/yo#pro`. Sin `sello` válido → `/`.
- Eliminar las rutas de página `/estudio`, `/estudio/mundo`, `/cuenta`.
- `/lab`, `/regiones`, `/app/*`, `/detallar/*`, `/salidas/*` intactos.

## Aceptación (tests HTTP)
- Cada ruta nueva → 200 `text/html`.
- Ficha de la corrida falsa contiene `og:title` con el nombre y `og:image`.
- Tabla completa de redirecciones: `Location` exacta para cada caso, incluido
  `modo=battlemap|conquistar` y ausencia de sello.
