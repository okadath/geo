# Mundaria — front comercial

Front comercial del proyecto de geología procedural. Vende **una herramienta
creativa**: generas un planeta con geología real, lo ves como mapa de fantasía,
haces clic en un punto y obtienes el battlemap coherente. Pitch: *«del planeta
al encuentro»* (ADR-001).

Stack vanilla, sin build (ADR-003): HTML + CSS custom properties + ES modules,
servido estáticamente por `web.py` (mismo origen que la API, sin CORS).

## Cómo correr

```bash
python3 web.py            # http://127.0.0.1:8000
python3 web.py -p 8123    # otro puerto
python3 web.py --sin-recarga   # sin autorecarga al editar .py
```

No hay paso de instalación ni build: `python3 web.py` y listo.

## Rutas (ADR-004)

| Ruta | Sirve | Público |
|---|---|---|
| `GET /` | `frontend/index.html` — landing | Todos |
| `GET /estudio` | `frontend/estudio.html` — galería + crear mundo | Usuarios |
| `GET /estudio/mundo?sello&d` | `frontend/mundo.html` — workspace | Usuarios |
| `GET /app/<rel>` | estáticos de `frontend/assets/` (allowlist) | — |
| `GET /lab` | `web.html` — panel científico (motor) | Solo el dueño |

Rutas viejas (ADR-009): `/fantasia` y `/batalla` **redirigen** al workspace
(`/estudio/mundo`, con `&modo=battlemap` en el caso de batalla). Siguen vivas
solo `/juego?sello&d` (lo lanza el modo Conquistar del workspace), `/regiones`
(herramienta interna, enlazada únicamente desde `/lab`), `/api/*` y
`/salidas/*`. El workspace acepta `?modo=explorar|battlemap|conquistar` como
deep-link.

## Estructura

```
frontend/
├── ADR/                 decisiones de arquitectura (ADR-001 … ADR-008)
├── assets/
│   ├── css/
│   │   ├── tokens.css   custom properties «atlas nocturno» + reset
│   │   └── base.css     sistema de componentes (.btn, .tarjeta, …)
│   └── js/
│       ├── marca.js     nombre/tagline/logo (único lugar del nombre)
│       ├── nav.js       montarNav() / montarPie()
│       └── api.js       cliente de la API existente
├── index.html           landing
├── estudio.html         galería + asistente de creación
├── mundo.html           workspace (fantasía + battlemap + jugar)
└── README.md
```

Los estáticos se enlazan desde el HTML vía `/app/...` (p. ej.
`/app/css/tokens.css`, `import ... from "/app/js/api.js"`).

## ADRs

Las decisiones que rigen este front están en [`ADR/`](./ADR/): qué se vende,
nombre, stack, rutas, asistente de creación, workspace unificado, monetización
y estética. Léelos antes de tocar la estructura.

## QA 2026-07-17

- `/`, `/estudio`, `/estudio/mundo?sello&d` y `/estudio/mundo` (sin query → error
  elegante) cargan **sin errores de consola JS ni peticiones 4xx/5xx** (Chromium headless/CDP).
- Mapa de fantasía se pinta con datos reales; modo **Battlemap** genera ficha del
  lugar + vista previa al activarse (auto-centro) y al hacer clic en el lienzo.
- Crawl de enlaces de las 3 páginas: 33 rutas internas → todas 200 (solo `mailto:`
  y ancla `#precios` omitidas); cabecera/nav y pie comunes vía `montarNav`/`montarPie`.
- Coherencia OK: `lang="es"`, viewport, `<meta description>` y `<title>` en las 3
  (se añadió la description que faltaba en `mundo.html`); tokens sin colores que choquen.

