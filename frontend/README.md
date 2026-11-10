# Pergamundi — front comercial

Front comercial del proyecto de geología procedural. Vende **una herramienta
creativa**: eliges (o generas) un planeta con geología real, lo ves como mapa
de fantasía, haces clic en un punto y obtienes el battlemap coherente. Pitch:
*«del planeta al encuentro»* (ADR-001).

Stack vanilla, sin build (ADR-003): HTML + CSS custom properties + ES modules,
servido estáticamente por `web.py` (mismo origen que la API, sin CORS). Toda la
lógica (gating, resolución de mundo, lugares, cuentas) vive en `servidor/`; el
front solo presenta.

## Cómo correr

```bash
python web.py                  # http://127.0.0.1:8000
python web.py -p 8123          # otro puerto
python web.py --sin-recarga    # sin autorecarga al editar .py
```

No hay paso de build: `python web.py` y listo.

### Variables de entorno

| Variable | Uso | Por defecto |
|---|---|---|
| `SMTP_HOST` | servidor SMTP del enlace mágico | sin definir → **modo dev**: el enlace se escribe en el log y la API responde `"modo": "dev"` |
| `SMTP_PORT` | puerto SMTP (465 = SSL, 587 = STARTTLS) | `587` |
| `SMTP_USER`, `SMTP_PASS` | credenciales SMTP | vacías |
| `SMTP_FROM` | remitente | `SMTP_USER` o `no-responder@pergamundi.com` |
| `BASE_URL` | origen absoluto de los enlaces del correo y de las metas OG | el de la petición |
| `PADDLE_TOKEN`, `PADDLE_WEBHOOK_SECRET` | pasarela de pago | sin definir → checkout en modo beta (lista de espera) |
| `TECTO_SALIDAS` | directorio de corridas | `salidas/` |
| `TECTO_DB` | BD SQLite de cuentas y límites | `cuentas.db` |
| `TECTO_PUBLICOS` | lista de mundos públicos | `publicos.json` |

Las tres `TECTO_*` existen sobre todo para las pruebas (apuntan a un
directorio temporal).

### Pruebas

```bash
pip install pytest httpx       # dependencias de desarrollo (ver requirements.txt)
python -m pytest -q
```

Las pruebas ejercitan la app FastAPI completa por HTTP (`TestClient`) sobre una
corrida falsa en un directorio temporal: rutas de páginas y redirecciones, OG
de la ficha, endpoints de mundo, enlace mágico y guardados.

## Rutas (ADR-010)

Fuente de verdad: `servidor/rutas_paginas.py` (páginas) y
[`ESPECIFICACION_RUTAS.md`](../ESPECIFICACION_RUTAS.md).

| Ruta | Sirve | Quién |
|---|---|---|
| `GET /` | `explorar.html` — mundo del día, tira de públicos, buscador | Todos |
| `GET /w/<sello>` | `ficha.html` — ficha compartible (metas OG rellenadas en servidor) | Todos |
| `GET /w/<sello>/detail` | `mapa.html` — visor detallado de fantasía; clic → battlemap (`/mapa` redirige aquí) | Todos |
| `GET /w/<sello>/<x>,<y>?tema=…` | `battlemap.html` — battlemap a pantalla completa con minimapa | Todos |
| `GET /w/<sello>/jugar` | `juego.html` (raíz del repo) — conquista por turnos | Todos |
| `GET /nuevo` | `nuevo.html` — asistente de creación (genera solo Pro) | Todos |
| `GET /yo` | `yo.html` — cuenta única: entrar, plan, uso, guardados, planes | Todos |
| `GET /entrar/<token>` | enlace mágico: crea sesión y 302 a `volver` | Quien tenga el enlace |
| `GET /app/<rel>` | estáticos de `frontend/assets/` (allowlist) | — |
| `GET /lab` | `web.html` — panel científico (motor) | Solo el dueño |
| `GET /regiones` | `regiones.html` — inspección de subregiones | Solo el dueño |

Todas las rutas `/w/...` aceptan `?d=<stem>` para fijar el detalle; sin él, el
servidor usa el más reciente con capas. Un sello mal formado responde 404.

Redirecciones 302 (conservan `d`; sin `sello` válido van a `/`):

| Vieja | Nueva |
|---|---|
| `/estudio` | `/` |
| `/estudio/mundo?sello&d[&modo=battlemap\|conquistar]` | `/w/<sello>` (`/detail`, `/jugar`) |
| `/fantasia?sello&d`, `/batalla?sello&d`, `/w/<sello>/mapa?d=` | `/w/<sello>/detail?d=` |
| `/juego?sello&d` | `/w/<sello>/jugar?d=` |
| `/cuenta`, `/entrar` | `/yo` |
| `/pro` | `/yo#pro` |

API que consume el front además de la existente (`/api/fantasia/*`,
`/api/batalla/*`, `/api/pagos/*`, `/api/corridas`…):

| Endpoint | Para |
|---|---|
| `GET /api/w?orden=nuevos\|azar&q=` | lista de mundos públicos |
| `GET /api/w/dia` | mundo del día (y `?desde=` para «siguiente») |
| `GET /api/w/{sello}` | ficha del mundo (nombre, `d`, meta, visibilidad, lugares) |
| `POST /api/w/{sello}/visibilidad` | publicar/ocultar (solo el dueño) |
| `POST /api/cuenta/enlace` | pedir enlace mágico `{email, volver}` |
| `GET /api/cuenta`, `POST /api/cuenta/salir` | estado de la cuenta, cerrar sesión |
| `GET\|POST\|DELETE /api/yo/guardados` | guardados (requiere sesión) |

## Estructura

```
frontend/
├── ADR/                   decisiones de arquitectura (ADR-001 … ADR-010)
├── assets/
│   ├── css/
│   │   ├── tokens.css     custom properties «atlas nocturno» + reset
│   │   ├── base.css       sistema de componentes (.btn, .tarjeta, …)
│   │   └── explorar.css, ficha.css, mapa.css, battlemap.css,
│   │       nuevo.css, yo.css          layout propio de cada página
│   └── js/
│       ├── marca.js       nombre/tagline/logo (único lugar del nombre)
│       ├── nav.js         montarNav() (barra o migas de pan) / montarPie()
│       ├── api.js         cliente de la API (una función por endpoint)
│       ├── ui.js          aviso, modal, cuadroCorreo, muroPro
│       ├── visor.js       visor pan/zoom del mapa de fantasía
│       ├── battlemap.js   controles, render y export del battlemap
│       └── explorar.js, ficha.js, mapa.js, battlemap-pagina.js,
│           nuevo.js, yo.js        arranque de cada página
├── explorar.html          /
├── ficha.html             /w/<sello>
├── mapa.html              /w/<sello>/detail
├── battlemap.html         /w/<sello>/<x>,<y>
├── nuevo.html             /nuevo
├── yo.html                /yo
├── _pendiente.html        reserva si falta el HTML de una ruta
└── README.md
```

Los estáticos se enlazan desde el HTML vía `/app/...` (p. ej.
`/app/css/tokens.css`, `import ... from "/app/js/api.js"`). `juego.html`,
`web.html` y `regiones.html` viven en la raíz del repo; `fantasia.html` y
`batalla.html` también, pero sin ruta (código muerto).

## ADRs

Las decisiones que rigen este front están en [`ADR/`](./ADR/): qué se vende,
nombre, stack, asistente de creación, monetización, estética y rutas públicas
(ADR-010, que sustituye a ADR-004, 006 y 009). Léelos antes de tocar la
estructura.
