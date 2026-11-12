# Especificación: rutas y pantallas de Pangeira

Fecha: 2026-10-10 · Origen: sesión de grill-design (7 rondas, prototipo navegable
en https://claude.ai/artifact/Bn7gy7FbHjgJb6981hwQ9G). Sustituye a ADR-004,
ADR-006 y ADR-009 (ver «Further Notes»). Respeta ADR-001 (qué se vende), ADR-003
(sin build), ADR-005 (crear mundo con presets), ADR-007 (gating en servidor) y
ADR-008 (estética: **no se tocan estilos**).

## Problem Statement

Un visitante nuevo no puede ver un mundo sin pasar por una landing, una galería y
un workspace con tres modos, y no puede llevarse ni compartir nada sin crear una
cuenta con contraseña. Las rutas actuales (`/`, `/estudio`,
`/estudio/mundo?sello&d&modo`, `/juego?sello&d`, `/cuenta`) describen cómo está
construido el motor, no lo que la persona busca: un mundo concreto, un lugar
concreto, una descarga.

Consecuencias: el enlace a un mundo no es una página que se pueda pegar en
Discord o Reddit (no tiene ficha ni vista previa), el muro de pago aparece lejos
del momento de valor, y cada usuario nuevo cuesta un formulario con contraseña.
Para el desarrollador, añadir una pantalla implica tocar el selector de modo del
workspace y la navegación en varias páginas.

## Solution

Todo lo público es una URL que se ve sin cuenta. Un mundo es `/w/<sello>`, un
battlemap es `/w/<sello>/<x>,<y>`, y esos enlaces son el producto viral. La
cuenta Free existe solo para guardar y para el cupo diario por persona, se crea
con un correo y un enlace mágico (sin contraseña), y Pro se compra con Paddle
desde la misma página de cuenta.

| Ruta | Pantalla | Quién la ve |
|---|---|---|
| `/` | Explorar: mundo del día con mapa vivo, tira de mundos, filtros y buscador de semilla | todos |
| `/w/<sello>` | Ficha compartible del mundo: imagen, datos, Abrir mapa, Jugar, compartir, guardar, remezclar, lugares destacados | todos |
| `/w/<sello>/mapa` | Visor del mapa de fantasía: estilo, descarga, clic en un punto → battlemap | todos |
| `/w/<sello>/<x>,<y>?tema=…` | Battlemap a pantalla completa con minimapa, controles, descarga y export | todos |
| `/w/<sello>/jugar` | Conquista: el `juego.html` actual sin cambios funcionales | todos |
| `/nuevo` | Generar mundo (asistente ADR-005). Formulario visible y deshabilitado bajo el muro si no eres Pro | todos; genera solo Pro |
| `/yo` | Cuenta única: anónimo ve correo + planes; con sesión ve plan, uso, guardados y planes | todos |
| `/entrar`, `/pro` | Alias: 302 a `/yo` y `/yo#pro` | todos |
| `/entrar/<token>` | Aterrizaje del enlace mágico: crea sesión y redirige | quien tenga el enlace |
| `/lab`, `/regiones` | Panel científico e inspección, sin cambios | solo el dueño |

Barra superior: en `/`, `/nuevo` y `/yo`, cinco elementos (Pangeira · Explorar ·
＋ Nuevo mundo · Pro $29/año · Entrar/Yo; «Pro» desaparece si ya eres Pro).
Dentro de un mundo, migas de pan: Pangeira › Thalyra › Mapa › Vado de Ysra, con
Yo a la derecha; las páginas de mundo pierden sus «← volver» sueltos.

Reglas de negocio fijadas en el grilling:

- Anónimo ve y descarga con marca de agua sin cuenta. Free igual, pero puede
  guardar. Pro descarga limpio (8K / 140 px) y exporta Foundry y Roll20.
- Generar y remezclar mundos es Pro. «Remezclar semilla» es visible para todos
  con el muro al pulsar.
- Mundos generados por Pro son privados por defecto (no listados; la URL sigue
  funcionando para quien la tenga) y se publican en Explorar con un clic.
- Pagar como anónimo crea la cuenta con el correo del checkout de Paddle.
- Precio único, sin ofertas de bienvenida.
- Lugares destacados de un mundo los calcula el servidor por reglas (cruces de
  río con camino, pasos de montaña, costas, ciudades); no se curan a mano.
- Mundos públicos iniciales: los mejores de `salidas/` existentes, marcados
  públicos.
- Rutas viejas: 302 conservando la query desde `/estudio/mundo`, `/fantasia`,
  `/batalla`, `/juego`, `/estudio` y `/cuenta`. `fantasia.html` y `batalla.html`
  siguen siendo código muerto.

## User Stories

Visitante anónimo

1. Como visitante, quiero abrir `/` y ver un mundo real con el mapa interactivo sin registrarme, para entender el producto en el primer segundo.
2. Como visitante, quiero pulsar «siguiente» en el mundo del día o «al azar», para saltar de mundo sin elegir.
3. Como visitante, quiero escribir una semilla o un nombre en el buscador, para llegar al mundo que alguien me pasó por su número.
4. Como visitante, quiero que `/w/<sello>` sea una ficha con imagen y datos, para que al pegarla en Discord o Reddit se vea una vista previa.
5. Como visitante, quiero pulsar «Abrir mapa» desde la ficha, para explorar el mapa de fantasía con pan y zoom.
6. Como visitante, quiero hacer clic en cualquier punto del mapa, para obtener el battlemap de ese lugar.
7. Como visitante, quiero que el battlemap tenga su propia URL con coordenadas y estilo, para compartir exactamente lo que veo.
8. Como visitante, quiero ver un minimapa del mundo en la página del battlemap, para saltar a otro punto sin volver al visor.
9. Como visitante, quiero descargar el PNG con marca de agua sin crear cuenta, para probar el producto sin fricción.
10. Como visitante, quiero ver qué me daría Pro junto al botón de descarga, para decidir si pago.
11. Como visitante, quiero pulsar «Jugar» en la ficha, para conquistar ese mundo sin salir del flujo.
12. Como visitante, quiero que los enlaces antiguos (`/estudio/mundo?sello&d`, `/fantasia`, `/batalla`, `/juego`) me lleven al mundo correcto, para que los marcadores viejos no se rompan.
13. Como visitante, quiero copiar el enlace del mundo o del battlemap con un botón, para compartirlo.
14. Como visitante, quiero ver la lista de lugares destacados de un mundo en su ficha, para tener un battlemap bueno a un clic.
15. Como visitante, quiero saber siempre dónde estoy (Pangeira › mundo › mapa › lugar), para subir un nivel sin buscar el botón «volver».

Alta y cuenta Free

16. Como visitante, quiero pulsar «★ Guardar» y que me pida solo mi correo, para no inventar una contraseña.
17. Como visitante, quiero recibir un enlace por correo que me deje dentro al hacer clic, para entrar sin recordar nada.
18. Como visitante, quiero que `/entrar` y `/pro` me lleven a la misma página de cuenta, para que solo exista un sitio donde entrar o pagar.
19. Como usuario Free, quiero ver en `/yo` mi correo, mi plan y cuántos renders me quedan hoy, para saber mi cupo.
20. Como usuario Free, quiero ver en `/yo` mis mundos y battlemaps guardados, para volver a ellos.
21. Como usuario Free, quiero quitar algo de mis guardados, para mantener la lista limpia.
22. Como usuario Free, quiero que mi cupo diario cuente por cuenta y no por IP, para que la red compartida no me penalice.
23. Como usuario Free, quiero ver la tabla de planes al final de `/yo`, para subir a Pro cuando quiera.
24. Como usuario con sesión, quiero un botón «Salir» en `/yo`, para cerrar sesión en un equipo ajeno.
25. Como usuario, quiero que el enlace mágico caduque y sea de un solo uso, para que nadie entre con un correo viejo.
26. Como usuario, quiero que el enlace mágico me devuelva a la página donde estaba, para seguir con lo que hacía.

Pro

27. Como visitante, quiero pagar Pro desde `/yo` dando solo mi correo, para que la cuenta se cree con el pago.
28. Como usuario Pro, quiero que «Pro $29/año» desaparezca de la barra, para que no me vendan lo que ya tengo.
29. Como usuario Pro, quiero descargar el mapa a 8K y el battlemap a 140 px sin marca, para usarlos en mesa.
30. Como usuario Pro, quiero exportar a Foundry y Roll20 desde la página del battlemap, para importarlo en mi mesa virtual.
31. Como usuario Pro, quiero generar un mundo en `/nuevo` con los presets de ADR-005, para tener un mundo propio.
32. Como usuario Pro, quiero pulsar «Remezclar semilla» en la ficha de un mundo que me gusta, para obtener uno parecido pero mío.
33. Como usuario Pro, quiero que mis mundos sean privados por defecto, para que mi campaña no aparezca en Explorar.
34. Como usuario Pro, quiero publicar un mundo en Explorar con un clic desde su ficha, para compartirlo con todos.
35. Como usuario Pro, quiero ver mis mundos generados en `/yo`, para abrirlos aunque sean privados.
36. Como usuario Pro, quiero un enlace al portal de Paddle en `/yo`, para cambiar o cancelar el plan.
37. Como usuario no Pro, quiero ver el formulario de `/nuevo` deshabilitado bajo el muro, para ver lo que compro antes de pagar.

Dueño / desarrollador

38. Como dueño, quiero que `/lab` y `/regiones` sigan igual y fuera de toda navegación, para no perder el panel científico.
39. Como dueño, quiero marcar mundos de `salidas/` como públicos sin generar nada nuevo, para llenar Explorar el día uno.
40. Como dueño, quiero que el enlace mágico se imprima en el log cuando no haya SMTP configurado, para desarrollar sin correo.
41. Como desarrollador, quiero que todo el gating (marca, px, cupos, Pro) siga en el servidor, para que el front sea solo presentación.
42. Como desarrollador, quiero que cada pantalla nueva sea un HTML en `frontend/` servido por una ruta y nada más, para que añadir pantallas no toque las demás.
43. Como desarrollador, quiero que `juego.html` no cambie salvo su URL y su «volver», para no tocar el juego.
44. Como desarrollador, quiero pruebas HTTP sobre la app completa, para cambiar rutas con confianza.
45. Como desarrollador, quiero un ADR-010 que recoja estas rutas, para que el README y los ADR anteriores no contradigan al código.

## Implementation Decisions

Identidad del mundo

- El identificador público es el **sello** de la corrida (`YYYYMMDD-HHMMSS[-N]`,
  ya validado por `RE_SELLO`). El detalle `d` deja de viajar en la URL: el
  servidor lo resuelve como el detalle más reciente que tenga `_capas.json`
  (y `_civ.png` si existe). Se admite `?d=<stem>` como anulación explícita.
- Un endpoint JSON de mundo devuelve: sello, nombre, `d` resuelto, metadatos
  (semilla, placas, continentes, clima, países si están en el meta o las capas),
  visibilidad, dueño, URL de imagen de vista previa y lugares destacados. La
  ficha, la portada y `/yo` consumen este endpoint; ninguna página calcula nada.
- Nombre del mundo: del meta de la corrida si existe; si no, derivado
  determinista de la semilla (generador de nombres ya usado por civ para
  países). Se guarda en el meta la primera vez que se calcula.

Visibilidad y propiedad

- El meta de la corrida gana `publico: bool` y `dueno: email|null`. Las corridas
  nuevas de un Pro nacen con `publico=false, dueno=email`. Las corridas sin
  dueño existentes se tratan como públicas si `publicos.json` las lista o si
  `publicos.json` no existe (compatibilidad con el modo desarrollo actual).
- Explorar lista solo `publico=true`. `/w/<sello>` de un mundo privado responde
  igual que uno público (no listado, no secreto). Solo el dueño ve el
  conmutador de visibilidad y solo él puede cambiarla (endpoint POST con
  sesión).
- `/api/corridas` (lab) no cambia su contrato; la lista pública nueva es un
  endpoint aparte para Explorar con filtros `orden=nuevos|azar` y `q=<sello>`.
  «Populares» queda como filtro reservado hasta tener contadores (fuera de
  alcance).

Mundo del día

- Elegido en el servidor de forma determinista: hash de la fecha (UTC) sobre la
  lista de públicos. «Siguiente» avanza en esa misma lista ordenada. Sin
  públicos, la portada muestra el estado vacío con enlace a `/nuevo`.

Lugares destacados

- Calculados en el servidor a partir de las capas del detalle usando el
  análisis de lugar existente en el módulo de batalla: hasta 6 puntos por
  reglas (cruce de río con camino, paso de montaña entre dos cuencas, costa con
  ciudad cercana, desierto, bosque denso, capital). Resultado cacheado en el
  directorio del detalle como JSON; se recalcula si falta.
- Cada lugar lleva coordenadas de rejilla `x,y` (los `rx,ry` del módulo de
  batalla), nombre del lugar (el que ya devuelve el análisis) y bioma.

URLs de battlemap

- `/w/<sello>/<x>,<y>` con `x`, `y` enteros de rejilla. El estilo viaja en la
  query con los nombres que ya usa la API de batalla (`tema`, `sub`, `semilla`,
  `cols`, `rows`, `px`, `rejilla`, `nums`), para que el servidor cachee por URL
  sin traducir. Cambiar un control reescribe la query con `history.replaceState`.
- La página del battlemap es un HTML nuevo que reutiliza el módulo de battlemap
  del front (controles, render, export) y añade el minimapa (imagen del mundo
  con clic → nueva `x,y`).

Visor

- `/w/<sello>/mapa` es el `mundo.html` actual sin selector de modo ni panel de
  battlemap: solo visor + panel de estilo + descarga. El clic en el mapa navega
  a `/w/<sello>/<x>,<y>` (conversión fantasía→rejilla ya existente).

Juego

- `/w/<sello>/jugar` sirve `juego.html` tal cual. `juego.html` cambia solo dos
  cosas: lee `sello` del path (y `d` del endpoint de mundo si no viene en query)
  y sus enlaces de salida apuntan a `/w/<sello>` y `/w/<sello>/mapa`.
  Las partidas siguen donde están hoy (no se vinculan a la cuenta en esta
  iteración).

Cuenta: enlace mágico

- Se eliminan los endpoints de registro y login con contraseña. La tabla de
  usuarios conserva las columnas `sal` y `hash` pero pasan a ser opcionales
  (los usuarios existentes siguen entrando por enlace mágico con su correo).
- Nueva tabla de enlaces: token aleatorio (32 bytes, hex), correo, `volver`
  (ruta relativa validada, por defecto `/yo`), creado, usado. Caducidad 15
  minutos, un solo uso.
- `POST /api/cuenta/enlace {email, volver}` crea el usuario si no existe (plan
  free), genera el token y envía el correo. Responde 200 siempre que el correo
  tenga forma válida (no revela si existía). Limitado a 5 por correo y hora.
- `GET /entrar/<token>`: valida, marca usado, crea sesión con la cookie actual
  y responde 302 a `volver`. Token inválido o caducado → página `/yo` con
  mensaje.
- Envío de correo en un módulo propio: SMTP por variables de entorno
  (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`,
  `BASE_URL`). Sin `SMTP_HOST`, el enlace se escribe en el log del servidor
  (modo desarrollo) y la respuesta JSON incluye `"modo": "dev"`.
- `resolver_plan` e `identidad` no cambian de firma: el gating existente sigue
  funcionando.

Cuenta: guardados

- Nueva tabla `guardados(email, tipo, sello, x, y, query, creado)` con
  `tipo ∈ {mundo, battlemap}` y clave única por (email, tipo, sello, x, y).
- `GET /api/yo/guardados` lista; `POST /api/yo/guardados` añade;
  `DELETE /api/yo/guardados` quita. Requieren sesión (401 si no).
- `GET /api/cuenta` añade `guardados_n` y, para Pro, la lista de sellos
  propios (`mundos_propios`).

Pago

- El webhook de Paddle ya resuelve el correo; se añade «asegurar usuario»: si
  el correo no existe, se crea sin contraseña con el plan del evento. El
  checkout acepta anónimos y pasa el correo tecleado en `custom_data`.
- `/pro` responde 302 a `/yo#pro`. El botón de la barra apunta a `/yo#pro`.

Páginas y navegación (front, solo presentación)

- Nuevos HTML en `frontend/`: portada, ficha, battlemap, nuevo, yo. Se
  eliminan `estudio.html`, `cuenta.html` y el modo battlemap de `mundo.html`.
  Los módulos JS existentes (visor, battlemap, api, ui, marca) se reutilizan;
  el asistente de `/nuevo` reutiliza la lógica de presets de `estudio.js`.
- `montarNav` acepta `migas: [{texto, href}]`; con migas pinta el modo
  breadcrumb, sin ellas la barra de cinco. La barra lee `GET /api/cuenta` como
  hoy para pintar Entrar/Yo y ocultar «Pro».
- La ficha lleva `<meta property="og:title|og:image|og:description">`
  rellenadas por el servidor al servir el HTML (sustitución de marcadores en
  el archivo), porque los bots de vista previa no ejecutan JS. Es la única
  página con plantillado en servidor.
- Imagen de vista previa: el render de fantasía existente a calidad 1×, servido
  por la ruta pública de render (con marca si corresponde al plan del que lo
  pide; los bots son anónimos y la marca es aceptable).

Redirecciones (302, query conservada)

| Vieja | Nueva |
|---|---|
| `/estudio` | `/` |
| `/estudio/mundo?sello&d` | `/w/<sello>?d=` |
| `/estudio/mundo?…&modo=battlemap` | `/w/<sello>/mapa?d=` |
| `/estudio/mundo?…&modo=conquistar` | `/w/<sello>/jugar?d=` |
| `/fantasia?sello&d` | `/w/<sello>/mapa?d=` |
| `/batalla?sello&d` | `/w/<sello>/mapa?d=` |
| `/juego?sello&d` | `/w/<sello>/jugar?d=` |
| `/cuenta` | `/yo` |
| `/entrar`, `/pro` | `/yo`, `/yo#pro` |

Sin `sello` válido, las rutas viejas responden 302 a `/`.

Lo que no cambia

- Estilos (`tokens.css`, `base.css`, hojas por página): se reutilizan clases
  existentes; se pueden añadir hojas nuevas por página pero no se rediseña.
- Motor, módulos `_srv`, cola, límites, planes, `web.html`, `regiones.html`.

## Testing Decisions

Un buen test aquí ejercita la app por HTTP y comprueba lo que vería un
navegador o un bot: código de estado, cabecera `Location`, JSON devuelto,
cookie fijada, marcadores OG sustituidos. No se prueban funciones internas ni
el DOM.

Seam único: la aplicación FastAPI completa mediante `TestClient` de Starlette
(requiere `httpx` como dependencia de desarrollo). Es el seam más alto que
existe y no hay pruebas previas en el repo, así que se crea `tests/` con
`pytest` y una fixture que:

- apunta `SALIDAS`, la base de datos de cuentas y `publicos.json` a un
  directorio temporal (monkeypatch de las constantes de configuración y del
  módulo de cuentas antes de importar la app);
- crea una corrida falsa mínima: `meta.json`, `detalles/<stem>.json`,
  `<stem>_capas.json` pequeño y PNG de 1×1, suficiente para resolver `d`,
  listar públicos y calcular lugares con el analizador real;
- desactiva el envío de correo (modo dev) y captura el enlace del log.

Módulos cubiertos: rutas de páginas (todas las nuevas, todas las
redirecciones, OG de la ficha), endpoint de mundo y de públicos (resolución de
`d`, visibilidad, mundo del día determinista, lugares cacheados), cuenta
(enlace mágico: creación, caducidad, un solo uso, `volver` validado, rate
limit; guardados: CRUD con y sin sesión), webhook de Paddle creando usuario.

No se prueban: renders reales de fantasía o battlemap (siguen siendo de los
módulos `_srv`), el juego, ni el JS del front.

## Out of Scope

- Vincular partidas de conquista a la cuenta.
- Filtro «populares» y cualquier contador de visitas o descargas.
- Identificadores cortos de mundo distintos del sello.
- Texto narrativo generado por mundo (ficha tipo wiki) y landing `/battlemaps`.
- Ofertas, descuentos o cupones en Paddle.
- Cambios de estilo, tipografía o paleta.
- Borrar `fantasia.html`, `batalla.html` y el código muerto asociado.
- Recuperación de contraseña: ya no hay contraseñas.

## Further Notes

- Se añade `frontend/ADR/ADR-010-rutas-publicas.md` que declara sustituidos
  ADR-004, 006 y 009 y resume la tabla de rutas y las reglas de negocio de
  esta especificación. El README de `frontend/` actualiza su tabla de rutas.
- Orden de implementación recomendado: back primero (mundo, públicos,
  lugares, enlace mágico, guardados, redirecciones, tests), luego front
  (nav, ficha, portada, visor, battlemap, nuevo, yo), luego juego y limpieza.
  Los tickets están en `tickets/`.
- El prototipo navegable del grilling queda como fuente primaria de las
  decisiones de pantalla; no se promueve a código.
- No hay issue tracker configurado para este repo (no se ejecutó
  `/setup-matt-pocock-skills`); los tickets viven como archivos locales.
