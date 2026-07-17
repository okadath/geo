# ADR-004 — Mapa de rutas: el front comercial toma `/`, el laboratorio se muda a `/lab`

**Estado:** aceptada · 2026-07-17

## Contexto

Hoy `/` sirve el panel científico (`web.html`) con todos los diales de
tectónica — la peor primera impresión posible para un cliente. Las cuatro
páginas actuales viven en rutas planas sin jerarquía ni navegación común.

## Decisión

Rutas nuevas (servidas por `web.py` desde `frontend/`):

| Ruta | Página | Público |
|---|---|---|
| `GET /` | `frontend/index.html` — landing comercial | Todos |
| `GET /estudio` | `frontend/estudio.html` — galería de mundos + crear mundo | Usuarios |
| `GET /estudio/mundo?sello&d` | `frontend/mundo.html` — workspace (fantasía + battlemaps + jugar) | Usuarios |
| `GET /app/*` | estáticos de `frontend/assets/` (allowlist de extensiones) | — |
| `GET /lab` | `web.html` — el panel científico completo, sin cambios | Solo el dueño |

Rutas viejas **intactas** (`/juego`, `/fantasia`, `/batalla`, `/regiones`,
`/api/*`, `/salidas/*`): el workspace las consume o enlaza; nada se rompe.
El juego se abre en su página actual (`/juego?sello&d`) porque «ya está bien
como funciona» — solo cambia cómo se llega a él.

**Único cambio al back:** el montaje estático de estas rutas en `web.py`
(~30 líneas de routing de archivos, sin lógica de negocio). Es la excepción
mínima inevitable para servir mismo-origen; queda señalada aquí.

## Consecuencias

- El usuario final nunca ve el generador científico ni sus rutas.
- `/lab` no aparece en ninguna navegación; solo un enlace pequeño en el pie de
  `/estudio` («laboratorio») para el dueño.
- Deep-links compartibles: `/estudio/mundo?sello=…&d=…` identifica un mundo,
  base futura del «juega el mundo #4217» viral (NEGOCIO §2).
