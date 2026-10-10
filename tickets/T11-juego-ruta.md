# T11 — Juego en `/w/<sello>/jugar`

Depende de T06. Spec: «Juego».

## Alcance (`juego.html`, cambios mínimos)
- Leer `sello` del path (`/w/<sello>/jugar`) con fallback a `?sello=`; `d` de
  `?d=` o, si falta, de `GET /api/w/<sello>` (campo `d`).
- Enlaces de salida (`data-ir` y «elegir partida»): → `/w/<sello>`,
  `/w/<sello>/mapa`, `/w/<sello>/jugar`.
- Cualquier `location.href` interno que construya `/juego?…` pasa a
  `/w/<sello>/jugar?…`.
- No tocar motor, guardados ni UI del juego.

## Aceptación
- `/w/<sello>/jugar` con una corrida real arranca partida y «volver» lleva a
  la ficha.
- `/juego?sello&d` sigue funcionando vía 302 (T06).
