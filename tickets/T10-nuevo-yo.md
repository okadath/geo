# T10 — `/nuevo` y `/yo`

Depende de T07. Spec: tabla de rutas, «Cuenta»; grilling ronda 5 variante 2.

## Alcance
`frontend/nuevo.html` + `assets/js/nuevo.js` (a partir del asistente de
`estudio.js`, ADR-005):
- Presets (Continentes, Pangea, Archipiélago, Sorpréndeme), campo semilla
  (prellenado con `?semilla=`), «Ajustes avanzados» plegado, «Forjar mundo»
  con la barra de progreso y textos de fase existentes
  (`generar`→`esperarTrabajo`→`detallar`→`esperarTrabajo`). Al terminar →
  `urlMundo(selloNuevo)`.
- Si plan no pro: formulario visible con `disabled` y opacidad, y `muroPro`
  encima («Generar mundos propios es Pro»). Nunca llamar a `generar`.
`frontend/yo.html` + `assets/js/yo.js` (a partir de `cuenta.js`):
- Anónimo: «Entra con tu correo» (`cuadroCorreo`), aviso si
  `?enlace=invalido`, y debajo `#pro` con la tabla de planes y el checkout
  existente (acepta correo tecleado).
- Con sesión: fila plan/uso/botones (Portal de Paddle si pro, «Pasar a Pro»
  si free, «Salir»); «Mundos guardados» (→ fichas); «Battlemaps guardados»
  (→ `urlBattlemap` con su query, botón quitar); «Tus mundos» para
  `mundos_propios` (pro); al final `#pro` con la tabla de planes (sin
  checkout si ya es pro).
- Eliminar `frontend/estudio.html`, `estudio.js`, `cuenta.html`, `cuenta.js`
  al terminar (la lógica reutilizable ya se movió).

## Aceptación
- Ambas páginas cargan sin errores de consola en los tres estados (anónimo,
  free, pro; crear un pro de prueba con el CLI de cuentas).
- `/yo#pro` hace scroll al bloque de planes.
