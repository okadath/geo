# T05 — Guardados (mundos y battlemaps)

Depende de T01. Spec: «Cuenta: guardados».

## Alcance
- `servidor/cuentas.py`: tabla `guardados(email, tipo, sello, x, y, query,
  creado)` con UNIQUE(email,tipo,sello,x,y). `tipo ∈ {mundo, battlemap}`;
  para `mundo`, `x=y=-1`, `query=''`. Funciones listar/añadir/quitar.
- Router (en `rutas_cuentas.py`): `GET /api/yo/guardados`,
  `POST /api/yo/guardados {tipo, sello, x?, y?, query?}`,
  `DELETE /api/yo/guardados {tipo, sello, x?, y?}`. 401 sin sesión; 400 si
  sello no casa `RE_SELLO` o tipo inválido; `query` saneada a ≤ 200 chars.
- `GET /api/cuenta` añade `guardados_n` y, con sesión, `mundos_propios`
  (sellos cuyo meta tiene `dueno == email`; usar `servidor.mundos` de T02 si
  existe, si no leer metas directamente).

## Aceptación (tests HTTP)
- Sin sesión → 401 en los tres. Con sesión: añadir, listar, duplicado
  idempotente (200), quitar.
- Validación de sello y tipo → 400.
