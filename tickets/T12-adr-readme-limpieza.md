# T12 — ADR-010, README, limpieza

Depende de T08 T09 T10 T11.

## Alcance
- `frontend/ADR/ADR-010-rutas-publicas.md`: estado aceptada, fecha, «sustituye
  ADR-004, ADR-006 y ADR-009»; tabla de rutas y reglas de negocio de
  `ESPECIFICACION_RUTAS.md` resumidas; consecuencias (enlace mágico, sin
  contraseñas, mundos privados no listados).
- Marcar ADR-004, 006 y 009 como «sustituida por ADR-010» en su cabecera.
- `frontend/README.md`: tabla de rutas nueva, estructura de archivos actual,
  variables de entorno SMTP/BASE_URL.
- `PLATAFORMA.md` §1.1 y §2: nota corta remitiendo a la especificación.
- Grep: no quedan referencias a `/estudio`, `/cuenta`, `estudio.html`,
  `cuenta.html`, `mundo.html` en código vivo; `fantasia.html` y `batalla.html`
  se dejan (fuera de alcance).
- `python -m pytest -q` verde y crawl final de todas las rutas de la tabla.

## Aceptación
- Grep limpio, tests verdes, README coherente con `rutas_paginas.py`.
