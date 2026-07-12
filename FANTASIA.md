# FANTASIA.md — mapa de fantasía (render pergamino de un detalle)

Documento de referencia de la página `/fantasia`: un render **estilizado tipo
mapa de fantasía** (pergamino, tinta, glifos de montaña y rótulos caligráficos)
de un detalle ya generado por `tecto.py`. Todo corre **en el navegador**
(`fantasia.html`, HTML + CSS + JS en una sola página, sin dependencias): el
servidor solo sirve los artefactos del detalle que ya expone el allowlist de
`web.py`.

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
- los glifos se **descartan por ventana** (culling) antes de dibujar.

## Controles

- **Rueda** = zoom (re-render nítido del sector) · **arrastrar** = paneo ·
  **⟲ zoom** restablece la vista.
- **Paleta**: pergamino claro, sepia envejecido, noche azulada.
- **Semilla** (texto libre): re-siembra glifos y jitter sin tocar los datos
  del detalle; misma semilla → mismo trazo.
- **💾 exportar PNG**: el mapa completo. **✂ exportar sector**: solo la vista
  actual, a la resolución de trabajo.
- Query opcional para **enlazar un sector**: `?c=<calidad 1..4>&z=<zoom>&cx=&cy=`
  (cx, cy en píxeles del render del detalle).

## Determinismo

Todo el trazo deriva de `mulberry32(hash(semilla + stem))` y de ruido de valor
por celda: misma query + misma semilla → mismo mapa, píxel a píxel (módulo
tipografías del sistema en los rótulos).
