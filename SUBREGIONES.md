# SUBREGIONES.md — subdivisiones administrativas y su página interactiva

Documento de referencia de la capa de **subregiones**: cómo se generan las
provincias de cada país y las cuencas marinas, cómo se exportan y cómo la
página `/regiones` permite seleccionarlas en el navegador. Pensado para
retomar el proyecto sin el historial de la conversación original.

Idioma del código y los comentarios: español. La capa vive en `civ.py`
(generación), `clima.py` (exportación) y `regiones.html` + `web.py` (interfaz).
Depende solo de `numpy` (generación) y `Pillow` (raster de ids).

---

## 1. Qué se agregó y por qué

El detallado climático ya producía **países** (reparto del suelo entre
capitales por Dijkstra multi-fuente, con ríos y montañas como barreras). Esta
capa añade el siguiente nivel de detalle político:

- **Provincias** (tierra): cada país se subdivide en subregiones, una por cada
  asentamiento suyo. Son el equivalente a condados/comarcas/prefecturas.
- **Cuencas marinas** (mar): el mar se reparte en cuencas pequeñas cuyas
  fronteras caen sobre las dorsales y umbrales submarinos, más los mares
  interiores aislados y los lagos.

Todo es **determinista** (misma semilla → mismo resultado) y se calcula sobre
los mismos campos que el resto de la civilización, sin tocar el generador
aleatorio de la simulación. Reutiliza la infraestructura ya existente
(`_dijkstra_multi`, el coste de fronteras `costo_f`) para que las divisiones
hereden la lógica geográfica de los países.

La motivación de interfaz: una **página nueva** (`/regiones`) donde el usuario
navega el mapa y **selecciona subregiones** con clic (multiselección), con
fichas, tooltips y un árbol navegable. En el mar se permiten regiones también,
como pidió el requerimiento («en el mar permite también regiones en cuencas
pequeñas»).

---

## 2. Generación (`civ.py`)

### 2.1 Contrato

`civ.generar(campo, seed, n_asent=0, n_paises=0, tam_paises=0)` devuelve, además
de `asentamientos`, `caminos`, `rutas` y `paises`, la clave:

```python
"subregiones": {
    "tierra": {"lista": [...], "idmap": int32 (nc,nc)},
    "mar":    {"lista": [...], "idmap": int32 (nc,nc)},
}
```

- `idmap` es la etiqueta por celda de la malla de civilización (`nc`, ≤200),
  con `-1` donde no aplica (mar en el mapa de tierra y viceversa).
- Cada elemento de `lista` de **tierra**:
  `{id, pais, asent, area, nombre, rgb}`.
- Cada elemento de `lista` de **mar**: `{id, nombre, area, rgb}`.

### 2.2 Provincias — `_provincias(idmap, costo_f, asent, rng)`

Para cada país por separado:

1. Se toma la máscara de sus celdas (`idmap == p`).
2. Se siembran como fuentes **los asentamientos de ese país** (todos, no solo
   la capital).
3. **Dijkstra multi-fuente** (`_dijkstra_multi`) sobre el mismo `costo_f` que
   generó las fronteras nacionales, pero **acotado a la máscara del país** (el
   coste es `inf` fuera). Así:
   - una provincia **nunca cruza una frontera nacional** (invariante duro,
     verificado en el test);
   - las fronteras **interiores** caen sobre ríos y divisorias, porque `costo_f`
     encarece cruzar cauces y montañas — la misma física que separa países.
4. Los enclaves que el Dijkstra no alcanza (tras barreras infranqueables dentro
   del país) se pegan a la provincia vecina más cercana con
   `_rellenar_huecos` (BFS multi-fuente desde las celdas ya asignadas).

Nombre: `"{tipo} {nombre_del_asentamiento}"`, con `tipo ∈ _TIPO_PROV`
(«Provincia de», «Condado de», «Marca de», «Comarca de», «Prefectura de»,
«Cantón de»). Color: el tono del país, aclarado/oscurecido de forma cíclica
(factor `0.72 + 0.56·((k·φ) mod 1)`), así las provincias vecinas se distinguen
pero comparten la familia cromática de su país.

> Con `tam_paises=2` (países chicos) quedan tierras libres sin país; esas
> celdas simplemente no tienen provincia (`idmap == -1`), coherentemente.

### 2.3 Cuencas marinas — `_cuencas_marinas(mar, elev, seed, n_obj=0)`

1. **Profundidad** = `clip(-elev, 0, 1)` en el mar, suavizada 3×3 dos veces
   (X envuelve, los polos no) para que las semillas no caigan en poros.
2. **Fragmentación costera** `frag`: fracción de celdas de mar cuya distancia
   a la tierra más cercana (`d_tierra`, BFS 8-vecinal reutilizando
   `_dist_a_mar` invertida — 0 en la costa, creciendo mar adentro) es ≤ 1.5,
   es decir litoral inmediato. Un mar salpicado de islas/penínsulas/estrechos
   da `frag` alto; un océano abierto y compacto da `frag` bajo.
3. **Semillas** en los fondos más profundos, greedy con separación mínima
   `rmin ≈ 0.55·nx/√n` (mismo patrón que el sembrado de asentamientos).
   Número objetivo `n` en automático: `clip(round(mar_frac·40·(1+1.8·frag)),
   4, tope)`, con `tope = clip(round(30+34·frag), 30, 64)` — mares más
   fragmentados piden más cuencas (hasta 64) para que ninguna abrace un
   archipiélago entero. Con `n_obj` explícito se usa tal cual, acotado a
   `[2, 64]` (sin ajuste por `frag`).
4. **Dijkstra multi-fuente** con coste que **encarece lo somero** de forma
   cuadrática (`0.25 + 6·(1+elev)²`) y además **encarece la cercanía a
   tierra** con `(3+6·frag)·exp(-d_tierra/3)`: las aguas costeras y los
   estrechos salen caros, así las fronteras entre cuencas se pegan a las
   **crestas del fondo marino** y cortan por los pasos angostos entre tierras
   en vez de rodearlas enteras.
5. Los **mares interiores aislados** sin semilla ni conexión se etiquetan como
   una región propia cada uno (BFS de componentes conexas). Los charcos
   diminutos (`area < 8`) se nombran «Lago …», el resto «Mar interior de …».

Nombre de las cuencas abiertas: `_PREF_MAR` («Mar de», «Golfo de», «Cuenca de»,
«Bahía de», «Fosa de», «Estrecho de»). Color: tonos fríos (HSV `h≈0.50`) bien
espaciados alrededor del azul-cian. La lista se ordena por área descendente
(las cuencas grandes primero).

### 2.4 Ensamblado en `generar()`

Sección 6, al final, después de que ya existen `idmap` (países), `costo_f` y los
asentamientos con su campo `pais`:

```python
submap, lista_prov = _provincias(idmap, costo_f, asent, rng)
# ... color de provincia derivado del color del país ...
marmap, lista_mar = _cuencas_marinas(mar, campo["elev"], seed)
```

Si no hubo asentamientos (mundo sin sitios habitables) se devuelve igualmente
`subregiones` con la tierra vacía y las cuencas marinas calculadas.

---

## 3. Exportación (`clima.py`)

En `_capa_civilizacion(...)`, tras construir el overlay de países, se genera:

### 3.1 Raster de ids — `{salida}_regiones.png`

Un PNG a `res_koppen` donde cada píxel codifica el **id combinado 1-based** de
su subregión:

- **R = byte bajo, G = byte alto** del id (`id = R | (G << 8)`), **0 = ninguna**.
- ids `1..Nt` = provincias (tierra); `Nt+1..` = regiones marinas.
- La costa se decide con `elev2` (la elevación **fina** del render), no con la
  malla gruesa de civilización, así el raster respeta el litoral real del mapa
  y la página puede hacer **hit-testing por píxel**.

Esto permite que el navegador identifique la región bajo el cursor leyendo un
solo píxel del PNG (sin polígonos ni geometría vectorial).

### 3.2 Bloque `subregiones` en `{salida}_capas.json`

```json
"subregiones": {
  "png": "…_regiones.png",
  "res": [nkx, nky],
  "res_civ": [ncw, ncw],
  "tierra": [{"id", "nombre", "pais", "asentamiento", "rgb", "area"}, …],
  "mar":    [{"id", "nombre", "rgb", "area"}, …]
}
```

Los `id` aquí ya vienen **desplazados a 1-based** para casar con el raster
(`id+1` para tierra, `id+1+Nt` para mar). `res_civ` da el total de celdas para
convertir `area` en porcentaje del mundo. Vale `null` si el detalle no tiene
civilización.

---

## 4. Servidor (`web.py`)

Cambios mínimos y aditivos (los detalles viejos siguen funcionando):

- **Ruta nueva `GET /regiones`** → sirve `regiones.html` sin caché.
- `_regiones.png` añadido al **allowlist** de `/salidas/...` (regex estricta,
  sin traversal), a la lista de artefactos por detalle (`_detalles`, clave
  `regiones`) y a la limpieza de detalles fallidos.

La página se abre con `?sello=<sello>&d=<stem>`, donde `stem` es el nombre base
del detalle (p. ej. `d000249_f8_f107cf`). Ambos se validan con las mismas
regex que el allowlist antes de pedir nada al servidor.

---

## 5. Página interactiva (`regiones.html`)

Autocontenida (HTML + CSS + JS inline, sin bundler, como el resto del proyecto).

### 5.1 Carga

1. `fetch` de `{stem}_capas.json` → lee el bloque `subregiones`, la resolución
   y las listas; llena un `Map` id→región.
2. Carga `{stem}_regiones.png` a un canvas offscreen y hace `getImageData` una
   vez → `Uint16Array` con el id de cada píxel (`R | G<<8`).
3. Fondo: `{stem}_climahd.png` (o `{stem}.png` si no hay clima HD).
4. Indexa qué asentamientos caen en cada región (para las fichas).

### 5.2 Capas del visor (mismo esquema zoom/paneo que el visor HD del index)

- **`cv-regiones`**: tinte de todas las regiones + fronteras (opacidad
  ajustable, se puede apagar). Se pinta una vez.
- **`cv-sel`**: selección + hover; se repinta al cambiar. La selección lleva
  borde dorado y rótulo en el centroide; el hover un velo claro.
- **`cv-civ`**: asentamientos (puntos por rango; capitales y ciudades con
  nombre).

### 5.3 Interacción

- **Rueda** = zoom hacia el cursor; **arrastrar** = paneo (con umbral para
  distinguir de un clic).
- **Hover** = tooltip (nombre, tipo, país) + ficha lateral (tipo, país,
  % del mundo, lista de asentamientos que contiene).
- **Clic** (sin arrastre) = selecciona / deselecciona la región. Multiselección.
- **Panel lateral**:
  - *Región*: ficha de la última región apuntada.
  - *Selección*: lista de lo seleccionado con superficie total; ✕ para quitar.
  - *Todas las regiones*: árbol agrupado por país + un grupo «mar — cuencas»,
    clicable en ambos sentidos (sincronizado con la selección del mapa).
- Controles: colorear todas las regiones, opacidad, asentamientos, rótulos,
  ⟲ zoom, limpiar selección.

### 5.4 Enlace desde el detalle

En `detallar.js`, cada detalle nuevo con civilización muestra un enlace
**«subregiones»** (junto a «mapa político») que arma la URL
`/regiones?sello=…&d=…` a partir de la ruta de `_regiones.png`.

> Nota: el proyecto añadió aparte un enlace «🎮 jugar conquista» → `/juego?…`
> en el header de `regiones.html`; esa es una funcionalidad separada.

---

## 6. Invariantes (verificados)

- Cada provincia está **contenida en un solo país** (`idmap[celdas] == pais`).
- El **área** de cada región coincide con el conteo de celdas de su id.
- **Toda celda de tierra con país** tiene provincia; **todo el mar** tiene
  región marina (0 celdas huérfanas).
- **Determinismo**: misma `(campo, seed, diales)` → mismos `idmap`, mismas
  listas, mismos nombres.
- El **raster PNG** solo contiene ids presentes en las listas (más 0).

Prueba sintética end-to-end: 5 países → 26–34 provincias, 30–53 regiones
marinas, sin celdas huérfanas, determinismo confirmado.

---

## 7. Cómo probarlo

```bash
python web.py                 # http://127.0.0.1:8000
# 1) genera/carga una corrida con mundo de checkpoints
# 2) detalla un cuadro (sección «Detallar con civilización»)
# 3) en el visor HD del detalle, clic en el enlace «subregiones»
#    o abre directo:
#    http://127.0.0.1:8000/regiones?sello=<SELLO>&d=<STEM>
```

Los detalles **anteriores** a esta capa no traen subregiones: basta
**redetallar** el mismo cuadro (mismos diales → sobrescribe los mismos
archivos) para obtener el `_regiones.png` y el bloque nuevo en `capas.json`.

---

## 8. Archivos tocados

| Archivo | Cambio |
|---|---|
| `civ.py` | `_rellenar_huecos`, `_provincias`, `_cuencas_marinas`; sección 6 en `generar()`; `subregiones` en el retorno |
| `clima.py` | raster `_regiones.png` + bloque `subregiones` en `_capa_civilizacion` y en `exportar_capas` |
| `web.py` | ruta `/regiones`; `_regiones.png` en allowlist, `_detalles` y limpieza |
| `regiones.html` | **página nueva**: visor con selección de subregiones |
| `detallar/detallar.js` | enlace «subregiones» en cada detalle con civilización |
