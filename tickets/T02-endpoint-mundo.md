# T02 — Endpoint de mundo, públicos, mundo del día, visibilidad

Depende de T01. Spec: «Identidad del mundo», «Visibilidad y propiedad», «Mundo del día».

## Alcance (todo en `servidor/`: módulo `mundos.py` + router `rutas_mundos.py`)
- `resolver_detalle(sello, d=None)`: stem del detalle más reciente con
  `_capas.json` (preferir el que tenga `_civ.png`); `d` explícito válido gana;
  None si no hay.
- `nombre_mundo(sello, meta)`: del meta si existe `nombre`; si no, determinista
  desde la semilla (reutilizar el generador de nombres de civ si es importable
  sin coste; si no, sílabas deterministas). Persistir en meta la primera vez.
- Meta de corrida: campos nuevos `publico` (bool) y `dueno` (email|None).
  `es_publico(sello, meta)`: `meta.publico` si está definido; si no, compat con
  `publicos.json` (listado → público; archivo ausente → público).
- `GET /api/w/<sello>[?d=]` → `{sello, nombre, d, meta:{semilla,...},
  publico, dueno, imagen, lugares:[...]}`. `imagen` = URL del render de
  fantasía 1× ya existente para ese sello/d. `lugares` lo provee T03 (hasta
  entonces lista vacía; dejar el punto de enganche `mundos.lugares(sello,d)`
  que intente importar `servidor.lugares`). 404 si el sello no existe o no
  tiene detalle usable.
- `GET /api/w?orden=nuevos|azar&q=<texto>&n=24` → lista pública (solo
  `publico=true`) con campos resumidos. `q` casa por sello exacto o por nombre
  (sin acentos, minúsculas).
- `GET /api/w/dia?desde=<sello>` → mundo del día: índice = hash(fecha UTC) mod
  N sobre la lista pública ordenada por sello; con `desde`, el siguiente en
  esa lista (circular). Sin públicos → 404 `{"error":"sin mundos"}`.
- `POST /api/w/<sello>/visibilidad {publico: bool}` → solo el dueño con
  sesión (403 si no); actualiza meta.
- Las corridas nuevas creadas vía `/api/generar` por un Pro nacen con
  `dueno=email, publico=false` (tocar el punto donde se escribe el meta,
  cambio mínimo).
- Montar el router en `app.py` antes del catch-all. Ojo: `/api/w/dia` debe
  declararse antes de `/api/w/{sello}` o validar que `dia` no es sello.

## Aceptación (tests HTTP)
- Resolución de `d` con y sin `?d=`; 404 sin detalle.
- Lista pública respeta `publico`, `publicos.json` y su ausencia.
- Mundo del día estable para la misma fecha (parchear fecha) y `desde` circular.
- Visibilidad: 403 anónimo/no dueño, 200 dueño, refleja en `/api/w`.
