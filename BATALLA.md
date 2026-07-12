# BATALLA.md — battlemaps de encuentro derivados del mundo

Documento de referencia de la página `/batalla`: un generador de **mapas
tácticos de encuentro** (battlemaps con rejilla, estilo mesa de rol) coherentes
con **un punto elegido del mundo**. Todo corre en el navegador
(`batalla.html`, una sola página sin dependencias); el servidor solo sirve los
artefactos del detalle ya permitidos por el allowlist de `web.py`.

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

14 temas: bosque templado, taiga, selva densa, desierto/roquedal,
nieve/tundra, ciénaga/pantano, paso rocoso/montaña, pradera, vado de río,
playa/costa, aldea, y tres interiores (taberna, cripta, mazmorra).

Cada tema exterior admite **subtipos** que cambian la escena (además de
«✨ automático», que elige uno según la semilla): clásico, espesura densa,
claro abierto, ruinas antiguas, círculo de piedras, cementerio, campamento,
oasis, cañón angosto, lago helado, mina abandonada, granja, puente, piedras de
paso, naufragio, acantilado, mercado — según el tema (p. ej. *playa* ofrece
naufragio y acantilado; *vado*, puente y piedras de paso). Los interiores no
tienen subtipo.

El encuentro recibe un **título narrativo** armado con el lugar real («Ruinas
antiguas de …», «Naufragio en la costa de …», «Mazmorra bajo …» con el nombre
del asentamiento si el punto cae en uno).

## Controles y export

- **tamaño**: columnas × filas (10–40 cada eje).
- **semilla** numérica + 🎲; misma semilla + mismo punto/tema/subtipo/tamaño →
  mismo mapa (determinista).
- **rejilla** y **numeración A1…** activables (el export las respeta).
- **💾 PNG** a 70 px/casilla o **PNG HD** a 140 px/casilla, listo para VTT o
  impresión.

## Archivos

| Archivo        | Papel |
|----------------|-------|
| `batalla.html` | La página completa (visor del mundo + generador + export). |
| `web.py`       | Ruta `GET /batalla` que la sirve sin caché (misma query que `/regiones`). |

No hay rutas de datos nuevas: consume `_capas.json`, `_datos.png`,
`_datos2.png` y `_climahd.png` del detalle.
