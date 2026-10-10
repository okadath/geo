# T03 — Lugares destacados por reglas

Depende de T01. Spec: «Lugares destacados».

## Alcance (`servidor/lugares.py`)
- `lugares(sello, d)` → lista de hasta 6 `{x, y, nombre, bioma, regla}` con
  coordenadas de rejilla (los `rx, ry` que consume `batalla_srv.analizar`).
- Reglas, en orden de prioridad y sin repetir celda ni regla si hay
  alternativas: cruce de río con camino; paso de montaña; costa con ciudad
  cercana; capital o ciudad mayor; bosque denso; desierto. Leer
  `batalla_srv.analizar` y `_capas.json` para saber qué datos hay; muestrear
  una malla gruesa (p. ej. cada 8 celdas) y puntuar; no recorrer cada celda.
- Nombre y bioma: los que ya devuelve `analizar` para ese punto.
- Caché en `salidas/<sello>/detalles/<stem>_lugares.json`; recalcular si falta
  o si su `version` interna es menor que la del módulo. Añadir ese sufijo a la
  allowlist de `/salidas/*` si hace falta servirlo (no es necesario: lo sirve
  el endpoint de mundo).
- Exponer `lugares(sello, d)` para que `servidor/mundos.py` (T02) lo importe.

## Aceptación
- Con la corrida falsa devuelve ≥1 lugar, sin excepciones, en < 2 s.
- Segunda llamada lee la caché (parchear `analizar` y comprobar que no se llama).
- Coordenadas dentro de `nx, ny` del detalle.
