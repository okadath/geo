# BATALLA.md — battlemaps de encuentro derivados del mundo

Documento de referencia de la página `/batalla`: un generador de **mapas
tácticos de encuentro** (battlemaps con rejilla, estilo mesa de rol) coherentes
con **un punto elegido del mundo**. La generación corre **en el servidor**
(`batalla_srv.py`, módulo enchufable de `web.py`): el análisis del punto, la
detección de tema, los títulos narrativos y el dibujo del battlemap se hacen en
Python y llegan al navegador como JSON/PNG. `batalla.html` es solo presentación
(visor con zoom/paneo, ficha, controles). El PRNG del servidor es idéntico bit
a bit al del JS original (Mulberry32 + FNV-1a), así que las semillas siguen
siendo reproducibles.

Endpoints (todos GET; el PNG se cachea en
`salidas/<sello>/detalles/batalla_cache/`):

- `/api/batalla/info?sello&d` → resolución + catálogo de temas y subtipos.
- `/api/batalla/lugar?sello&d&rx&ry` → ficha del punto (bioma, altitud, clima,
  río/camino/asentamiento cercanos, tema sugerido).
- `/api/batalla/escena?…&tema&sub&semilla&momento&estacion` → título narrativo
  (con coletilla «…, al anochecer en invierno» cuando aporta) y subtipo
  efectivo.
- `/api/batalla/mapa?…&cols&rows&px&rejilla&nums&momento&estacion` → PNG del
  battlemap (10–40 casillas, px 8–160; el export HD usa px=140).
- `/api/batalla/vtt?…&formato=foundry|roll20` → manifiesto de exportación a VTT
  (arma el servidor). `foundry`: escena mínima de Foundry (`name`, `width`/
  `height` en px, `grid:{size:100,type:1}`, imagen con nombre descriptivo).
  `roll20`: nombre de archivo + `nota` con la rejilla («NxM casillas · 70
  px/casilla»).

## Cómo abrirla

1. `python web.py` → `http://127.0.0.1:8000`.
2. Genera/carga una corrida y **detalla un cuadro con civilización**.
3. Abre `/batalla?sello=…&d=<stem>` (misma query que `/regiones`; hay enlaces
   cruzados con `/regiones` y `/fantasia`).

## Flujo

1. **Elegir el lugar**: visor del mundo (clima HD de fondo) con zoom y paneo;
   un clic marca el punto. La **ficha del lugar** muestra lo que los rásters y
   `_capas.json` saben de ahí: bioma, altitud, temperatura, precipitación,
   hielo, y qué hay cerca (río con nombre, camino, costa, asentamiento con su
   país — con insignia «aquí» si el punto cae encima).
2. **Tema sugerido**: de esos datos se deduce el tema del encuentro
   (`detectarTema`): p. ej. cerca de un asentamiento → *aldea*, junto a un río
   → *vado*, litoral → *playa*, bioma helado → *nieve*… El usuario puede
   cambiarlo a mano.
3. **Generar el battlemap**: rejilla de 10–40 × 10–40 casillas, dibujada
   proceduralmente según tema + subtipo + semilla.

## Temas y subtipos

17 temas: bosque templado, taiga, selva densa, desierto/roquedal,
nieve/tundra, ciénaga/pantano, paso rocoso/montaña, pradera, **tierras
volcánicas / roca ardiente**, vado de río, playa/costa, aldea, **puerto/
muelle**, y cuatro interiores (taberna, cripta, mazmorra, **gruta/caverna**).

Los tres temas nuevos se integran en `detectarTema`: junto a un asentamiento
**en el litoral** → *puerto* (tierra adentro sigue siendo *aldea*); gran
altitud + calor tórrido → *volcánico*. La *gruta* es un interior manual (como
taberna/cripta/mazmorra, no se autodetecta).

Cada tema exterior admite **subtipos** que cambian la escena (además de
«✨ automático», que elige uno según la semilla): clásico, espesura densa,
claro abierto, ruinas antiguas, círculo de piedras, cementerio, campamento,
oasis, cañón angosto, lago helado, mina abandonada, granja, puente, piedras de
paso, naufragio, acantilado, mercado, y los nuevos **torre en ruinas, altar
profanado, cruce de caminos, madriguera, géiseres y embarcadero** — según el
tema (p. ej. *bosque* ofrece torre/altar/madriguera; *paso* y *volcánico*,
géiseres; *puerto* y *playa*, embarcadero; *desierto* y *pradera*, cruce de
caminos). Los interiores no tienen subtipo.

El encuentro recibe un **título narrativo** armado con el lugar real («Ruinas
antiguas de …», «Naufragio en la costa de …», «Mazmorra bajo …», «Torre en
ruinas de …», «Puerto de …» con el nombre del asentamiento si el punto cae en
uno), más la coletilla de ambiente cuando aporta («…, al anochecer»,
«… en invierno»).

## Controles y export

- **tamaño**: columnas × filas (10–40 cada eje).
- **semilla** numérica + 🎲; misma semilla + mismo punto/tema/subtipo/tamaño +
  mismo momento/estación → mismo mapa (determinista).
- **momento** (día · atardecer · noche) y **estación** (primavera · verano ·
  otoño · invierno): post-procesado barato de paleta/iluminación sobre el
  render base (tinte frío + oscurecido con toques de luz cálida de noche, tinte
  dorado al atardecer; en invierno los temas templados ganan escarcha/nieve
  parcial, en otoño el follaje vira a ocre). Entran en la clave de caché del
  PNG y en el título narrativo.
- **rejilla** y **numeración A1…** activables (el export las respeta).
- **💾 PNG** a 70 px/casilla o **PNG HD** a 140 px/casilla.
- **🎲 Foundry VTT**: descarga el PNG a **100 px/casilla sin numeración** de
  coordenadas más un `.json` de escena mínimo de Foundry (`grid:{size:100,
  type:1}`) con el mismo nombre de archivo; el manifiesto lo arma el servidor
  (`/api/batalla/vtt?formato=foundry`).
- **🎲 Roll20**: descarga el PNG a **70 px/casilla sin numeración** y muestra el
  dato para configurar la rejilla en Roll20 («NxM casillas · 70 px/casilla»).
- Los nombres de archivo son descriptivos (tema, tamaño, semilla).

## Archivos

| Archivo        | Papel |
|----------------|-------|
| `batalla.html` | La página completa (visor del mundo + generador + export). |
| `web.py`       | Ruta `GET /batalla` que la sirve sin caché (misma query que `/regiones`). |

No hay rutas de datos nuevas: consume `_capas.json`, `_datos.png`,
`_datos2.png` y `_climahd.png` del detalle.
