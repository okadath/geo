# FANTASIA.md — mapa de fantasía (render pergamino de un detalle)

Documento de referencia de la página `/fantasia`: un render **estilizado tipo
mapa de fantasía** (pergamino, tinta, glifos de montaña y rótulos caligráficos)
de un detalle ya generado por `tecto.py`. El render corre **en el servidor**
(`fantasia_srv.py`, módulo enchufable de `web.py`, Python + PIL): paletas,
glifos, ríos, rótulos y decoración se hornean del lado servidor y llegan al
navegador como PNG. `fantasia.html` es solo presentación (controles de capas /
paleta / semilla / calidad, visor con pan/zoom, export); su único fetch de
datos es `{stem}_capas.json`, para conocer la resolución.

Endpoints (todos GET, cacheados en disco en
`salidas/<sello>/detalles/fantasia_cache/`):

- `/api/fantasia/render?sello&d&calidad=1..4&semilla&paleta&capas&deco&px` →
  PNG del mapa completo (el export usa `deco=0|1` y `px∈{2048,4096,8192}`).
- `/api/fantasia/sector?…&cx&cy&w&h` → PNG re-horneado de una ventana (pan/zoom
  nítido; el front pide con margen y re-render diferido).
- `/api/fantasia/deco?…` → PNG RGBA transparente con marco/rosa/cartela/escala,
  superpuesto fijo al visor.
- `GET /api/fantasia/rotulos?sello&d` → JSON con la lista de rótulos editables
  (ver «Rótulos editables»). `POST /api/fantasia/rotulos` → guarda overrides.

Mismo render determinista que siempre: misma semilla → PNG byte-idéntico.

## Cómo abrirla

1. `python web.py` → `http://127.0.0.1:8000`.
2. Genera/carga una corrida y **detalla un cuadro con civilización**.
3. Abre `/fantasia?sello=…&d=<stem>` (misma query que `/regiones`; hay enlaces
   cruzados entre `/regiones`, `/juego`, `/fantasia` y `/batalla`).

`sello` y `stem` se validan con las mismas regex que el allowlist del servidor
antes de pedir nada.

## De dónde salen los datos

- `{stem}_capas.json`: ríos (con caudal y nombre), caminos, rutas comerciales,
  asentamientos (rango, nombre, país), países y regiones marinas (para los
  rótulos de mares), resolución del render.
- `{stem}_datos2.png`: raster muestreable — canal R = bioma (255 = mar),
  canal B = hielo. De aquí sale la máscara de costa.

El dibujo **no** usa los colores del render climático: es un redibujado desde
cero con paleta propia.

## Qué dibuja

- **Base de pergamino + mar**: manchas de papel con ruido de valor **anclado a
  coordenadas de mundo** (la textura no «nada» al panear), mar con degradado a
  hondo por **distancia a costa** (chamfer 2 pasadas), costa entintada y
  **waterlines concéntricas** (3 bandas paralelas al litoral).
- **Glifos**: montañas (∧ sombreadas), colinas, y vegetación por bioma
  (frondosas, coníferas, dunas…) sobre una rejilla con jitter determinista;
  se pintan de fondo a frente (orden por `y`).
- **Ríos**: trazo suave (curvas por puntos medios), grosor por caudal, nombre
  en cursiva siguiendo el cauce en los ríos grandes.
- **Caminos** punteados y **rutas marítimas** en discontinua fina.
- **Asentamientos**: iconos por rango (castillo ★ capital, caserío, punto) con
  su nombre; **rótulos** de países en versalitas espaciadas y de mares en
  cursiva, ambos con halo de papel.
- **Tinte político** opcional (colores de país al 100 % de la lista de capas).

Capas activables por casilla: relieve, vegetación, ríos, caminos/rutas,
asentamientos, rótulos, tinte político.

## Calidad (mundo «más grande»)

El selector **calidad** (1× normal, 2× alta —default—, 3× ultra, 4× extrema)
dibuja el mundo como si fuera `K` veces más grande:

- glifos más **densos y chicos** (paso de rejilla ÷ K), textos y trazos más
  finos (unidad `uni() = nx / K`);
- entran **más rótulos**: países diminutos, más mares, ríos menores con nombre
  (umbral de caudal ÷ K) y, con K ≥ 3, también las aldeas rotuladas —
  legibles solo al acercarse;
- la resolución de trabajo del canvas sube: 2048 (K=1), 3072 (K=2),
  4096 (K≥3), y el zoom máximo crece con K.

## Render por sectores (nítido a cualquier zoom)

La base de pergamino/mar no se hornea una sola vez para el mundo entero: se
**rehornea para la ventana visible** (más un margen igual al alcance de las
waterlines) cada vez que el zoom/paneo se asienta. Claves:

- la máscara de costa se muestrea con **fracción de mar bilineal**
  (`marFrac`), así la costa no muestra la escalera de píxeles del raster de
  datos al acercarse;
- todos los umbrales (ancho de costa, radios de waterlines, tamaño de manchas)
  van en **unidades de mundo**, calibrados a la base clásica de 512 px: el
  dibujo es idéntico se mire el sector que se mire;
- el grosor del trazo de costa crece **sublinealmente** con el zoom del sector
  (√), para que de cerca la tinta no se vuelva una franja;
- los **rótulos** (países, mares, ríos, asentamientos) también crecen
  **sublinealmente** (√ del zoom, `_fs_rotulo`) con techo del 3 % del ancho de
  salida: a mapa completo el tamaño es el clásico, y de cerca los nombres
  chicos se vuelven legibles sin que los grandes dominen la vista ni el halo
  pierda definición. Las fuentes buscan también rutas de Linux (Liberation
  Serif / DejaVu) además de las de Windows;
- los glifos se **descartan por ventana** (culling) antes de dibujar;
- mientras el servidor rehornea, el visor muestra el PNG anterior estirado en
  **pixelado** (`image-rendering: pixelated`) con un **loader** flotante
  («cargando sector…»), para que la espera se lea como carga y no como error;
- los PNG cacheados en disco llevan la **versión del renderer**
  (`VERSION_RENDER`) en la clave: subirla invalida la caché al cambiar el dibujo.

## Controles

- **Rueda** = zoom (re-render nítido del sector) · **arrastrar** = paneo ·
  **⟲ zoom** restablece la vista.
- **Paleta** (7): pergamino claro, sepia envejecido, noche azulada,
  **tinta imprenta** (blanco y negro puro para imprimir), **esmeralda** (verdes
  de atlas antiguo), **carmesí y oro** (tonos de imperio), **atlas oceánico**
  (azules de carta náutica). Todas cuidan el contraste de los rótulos.
- **Semilla** (texto libre): re-siembra glifos y jitter sin tocar los datos
  del detalle; misma semilla → mismo trazo.
- **✏ rótulos**: abre el panel de rótulos editables (ver sección propia).
- **Export**: **resolución** (2048/4096/8192 px), casilla **incluir marco/deco**
  (cablea el parámetro `deco`), **💾 exportar PNG** (mapa completo) y
  **✂ exportar sector** (solo la vista actual). Se descarga vía `fetch`→blob con
  **spinner** mientras el servidor hornea (los renders grandes tardan); el
  nombre del archivo es descriptivo: `fantasia_<stem>_<paleta>_<semilla>_<px>px`.
- Query opcional para **enlazar un sector**: `?c=<calidad 1..4>&z=<zoom>&cx=&cy=`
  (cx, cy en píxeles del render del detalle).

## Rótulos editables

El usuario puede **renombrar u ocultar** cualquier rótulo (asentamientos,
países, mares, ríos) desde el panel plegable **✏ rótulos**. Todo se hornea en
el servidor; el front solo lista y edita.

- **Id estable por tipo**: `asent:<índice>` (posición en `asentamientos`),
  `pais:<id>`, `mar:<id>`, `rio:<id>`. El índice del asentamiento se conserva al
  ordenar por `y` para dibujar, así el id no depende del orden de pintado.
- **`GET /api/fantasia/rotulos?sello&d`** → `{"sello","d","rotulos":[{tipo,id,
  nombre,override?}]}`, donde `nombre` es el original y `override` (si existe)
  es `{"nombre"?,"oculto"?}`.
- **`POST /api/fantasia/rotulos`** con cuerpo JSON `{"sello","d","overrides":
  {id:{"nombre"?,"oculto"?}}}` **reemplaza** el mapa de overrides. Un mapa vacío
  **borra** el archivo (equivale a restaurar todo).
- **Persistencia**: `salidas/<sello>/detalles/<stem>_fantasia_rotulos.json`
  (sobrevive entre sesiones). `sello`/`stem` se validan con las mismas regex
  allowlist del módulo; los nombres se sanean (sin caracteres de control, máx.
  60 caracteres).
- **Aplicación al dibujar**: `render` y `sector` aplican los overrides a cada
  rótulo (`oculto` → no se dibuja el texto, el icono del asentamiento
  permanece). La **clave de caché** de los PNG incorpora la firma del archivo de
  overrides (`mtime` + hash MD5 del contenido), de modo que editar los rótulos
  invalida solo los PNG afectados. La `deco` no lleva rótulos y no depende de la
  firma.
- **Front**: el panel agrupa los rótulos por tipo con edición inline y una
  casilla «ocultar» por fila; **guardar y re-render** hace el POST y refresca el
  sector (con un contador `rv` que evita la caché HTTP del navegador);
  **restaurar todo** limpia los overrides.

## Determinismo

Todo el trazo deriva de `mulberry32(hash(semilla + stem))` y de ruido de valor
por celda: misma query + misma semilla → mismo mapa, píxel a píxel (módulo
tipografías del sistema en los rótulos).
