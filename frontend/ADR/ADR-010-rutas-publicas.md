# ADR-010 — Rutas públicas: el mundo es una URL, la cuenta es un correo

**Estado:** aceptada · 2026-10-10 · sustituye ADR-004, ADR-006 y ADR-009

Fuente completa: [`ESPECIFICACION_RUTAS.md`](../../ESPECIFICACION_RUTAS.md)
(grilling de 7 rondas). Este ADR resume sus decisiones; si discrepan, mandan la
especificación y `servidor/rutas_paginas.py`.

## Contexto

El embudo de ADR-004/006/009 (landing `/` → galería `/estudio` → workspace
`/estudio/mundo?sello&d&modo` → `/juego`) describía cómo está construido el
motor, no lo que busca la persona: un mundo concreto, un lugar concreto, una
descarga. Un enlace a un mundo no era una página compartible (sin ficha ni
vista previa), el muro de pago quedaba lejos del momento de valor y cada
usuario nuevo costaba un formulario con contraseña.

## Decisión

Todo lo público es una URL que se ve sin cuenta. El identificador público de
un mundo es el **sello** de la corrida; el detalle `d` lo resuelve el servidor
(el más reciente con `_capas.json`) y `?d=<stem>` queda como anulación.

| Ruta | Pantalla (`frontend/`) | Quién la ve |
|---|---|---|
| `/` | `explorar.html` — mundo del día, tira de públicos, filtros, buscador | todos |
| `/w/<sello>` | `ficha.html` — ficha compartible con OG rellenado en servidor | todos |
| `/w/<sello>/mapa` | `mapa.html` — visor de fantasía; clic → battlemap | todos |
| `/w/<sello>/<x>,<y>?tema=…` | `battlemap.html` — pantalla completa con minimapa | todos |
| `/w/<sello>/jugar` | `juego.html` (raíz) — conquista, sin cambios funcionales | todos |
| `/nuevo` | `nuevo.html` — asistente ADR-005, deshabilitado bajo el muro si no Pro | todos; genera solo Pro |
| `/yo` | `yo.html` — cuenta única: correo + planes; con sesión, uso y guardados | todos |
| `/entrar`, `/pro` | 302 a `/yo` y `/yo#pro` | todos |
| `/entrar/<token>` | enlace mágico: crea sesión y 302 a `volver` | quien tenga el enlace |
| `/lab`, `/regiones` | panel científico e inspección, sin cambios | solo el dueño |

Rutas viejas (302, conservando `d`; sin `sello` válido → `/`): `/estudio` → `/`,
`/estudio/mundo` → `/w/<sello>` (`modo=battlemap` → `/mapa`,
`modo=conquistar` → `/jugar`), `/fantasia` y `/batalla` → `/w/<sello>/mapa`,
`/juego` → `/w/<sello>/jugar`, `/cuenta` → `/yo`.

Navegación: en `/`, `/nuevo` y `/yo`, barra de cinco (Pangeira · Explorar ·
＋ Nuevo mundo · Pro · Entrar/Yo; «Pro» se oculta si ya lo eres). Dentro de un
mundo, migas de pan (Pangeira › mundo › Mapa › lugar) en vez de «← volver».

Reglas de negocio:

- Anónimo ve y descarga con marca de agua. Free igual, pero guarda mundos y
  battlemaps. Pro descarga limpio (8K / 140 px) y exporta Foundry y Roll20.
- Generar y remezclar es Pro; «Remezclar semilla» es visible para todos con el
  muro al pulsar.
- Los mundos de un Pro nacen privados (no listados; la URL sigue funcionando)
  y se publican en Explorar con un clic; solo el dueño cambia la visibilidad.
- Mundo del día determinista en el servidor (hash de la fecha UTC sobre la
  lista de públicos).
- Lugares destacados calculados en el servidor por reglas, no curados a mano.
- Pagar como anónimo crea la cuenta con el correo del checkout de Paddle.
  Precio único, sin ofertas.
- Todo el gating (marca, px, cupos, Pro) sigue en el servidor (ADR-007).

## Consecuencias

- **Sin contraseñas.** Se eliminan `/api/cuenta/registro` y
  `/api/cuenta/entrar`; se entra con `POST /api/cuenta/enlace {email, volver}`
  y el enlace `/entrar/<token>` (15 min, un solo uso, `volver` validado, 5 por
  correo y hora). Sin `SMTP_HOST` el enlace se escribe en el log (modo dev).
- **Mundos privados no listados**, no secretos: quien tiene la URL lo ve.
- API nueva: `GET /api/w`, `GET /api/w/dia`, `GET /api/w/{sello}`,
  `POST /api/w/{sello}/visibilidad`, `GET|POST|DELETE /api/yo/guardados`.
  `/api/corridas` (lab) no cambia.
- La ficha es la única página con plantillado en servidor (metas OG); el resto
  de páginas son HTML estáticos que consumen la API.
- Se retiran `index.html`, `estudio.html`, `cuenta.html` y `mundo.html` con sus
  JS/CSS. `fantasia.html` y `batalla.html` siguen como código muerto sin ruta.
- Añadir una pantalla es un HTML en `frontend/` más una ruta en
  `rutas_paginas.py`; no toca a las demás.
