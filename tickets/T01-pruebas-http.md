# T01 — Infraestructura de pruebas HTTP

## Alcance
Crear `tests/` con pytest y `TestClient` de Starlette sobre `servidor.app:app`.
Añadir `httpx` y `pytest` a `requirements.txt` (sección de desarrollo, comentada).

## Detalle
- `tests/conftest.py` con fixture `cliente` que, ANTES de importar
  `servidor.app`, redirige a un `tmp_path`: `servidor.config.SALIDAS`, la
  ubicación de `publicos.json` (hoy `BASE / "publicos.json"` en `rutas_lab`),
  la ruta de la BD en `servidor.cuentas` (hoy constante `DB`; hacerla
  parcheable, p. ej. leer `TECTO_DB` del entorno con fallback actual) y la BD
  de límites si existe. Hacer el cambio mínimo para que esas rutas sean
  parcheables sin alterar el comportamiento por defecto.
- Fixture `corrida_falsa(sello)` que crea en SALIDAS una corrida mínima:
  `meta.json`, `detalles/d000001_f0_abcdef.json`,
  `detalles/d000001_f0_abcdef.png` (1×1), `detalles/d000001_f0_abcdef_capas.json`
  con lo mínimo que `batalla_srv.analizar` y `corridas._detalles` necesiten
  (leer ambos; si `analizar` necesita rasters, generar arrays diminutos
  coherentes). Documentar en el conftest qué claves son obligatorias.
- Primer test: `GET /lab` → 200, `GET /api/corridas` → lista con la corrida
  falsa, `GET /noexiste` → 404 JSON `{"error":"no existe"}`.

## Aceptación
- `python -m pytest -q` pasa en limpio desde la raíz, sin tocar `salidas/` ni
  `cuentas.db` reales.
- El servidor sigue arrancando igual con `python web.py`.
