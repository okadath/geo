# DETALLE_HD.md — corrientes reutilizadas, meandros e hidrología de lagos

Documento de referencia de las funciones de **detallado climático HD** que
viven en `clima.py` y se orquestan desde `tecto.py::detallar`. Cubre tres
capacidades añadidas en esta iteración, con **qué se agregó, por qué, la
matemática exacta, los diales expuestos y las trampas ya resueltas** (no las
reintroduzcas). Mismo espíritu que `ALGORITMO.md`, pero para la capa de clima
del cuadro ampliado, no para la tectónica.

Idioma del código y los comentarios: español. Solo `numpy` + `Pillow`.

Contexto: al **detallar** un cuadro (web «Detallar cuadro» / CLI `--detallar`)
se super-muestrea un frame a `factor`× la resolución, se le añade geografía
menor por ruido (fBm) y se calcula un clima *snapshot* sobre esa geografía. El
render climático HD produce `<salida>_clima.png`, `<salida>_climahd.png` y
`<salida>_capas.json` (capas vectoriales del visor web). La **física** del
clima (vientos, SST, precipitación, hielo, temperatura del aire) se calcula
sobre una malla capada por costo (≤512), pero el **render** y la **hidrología**
van a plena resolución.

---

## 1. Corrientes reutilizadas del cuadro pequeño

### 1.1 El problema

El mapa de clima **pequeño** (el primero, sin definición, de la corrida) genera
corrientes marinas de forma correcta: sus circuitos (giros oceánicos) salen
bien cerrados y con la topología física esperada. Al **ampliar** (detallar), la
costa se rompe con el fBm de detalle; si se re-evalúan las corrientes sobre esa
costa ruidosa, los giros salen **deformados**: la tangencia a la costa
(`simular_clima` §3c) y la función de corriente barotrópica se enganchan a las
islitas y bahías del ruido, y el resultado ya no coincide con el mapa pequeño
que se veía bien.

### 1.2 La solución: recalcular sobre el cuadro ORIGINAL y re-escalar

En `tecto.py::detallar`, tras calcular el clima del detalle sobre la malla
capada `elev_c`, las corrientes **no** se toman de ese clima. Se recalculan
sobre la elevación del cuadro **original** (`elev_orig = crust.elevation(...)`,
la misma malla `NX×NY` que produjo el mapa pequeño) y solo se **re-escalan** a
la malla del detalle:

```python
cor = clima.simular_clima(elev_orig, temperatura=T, precipitaciones=P,
                          solo_corrientes=True)
mar_cd = elev_c <= 0.0
for k in ("cu", "cv", "sst_anom", "psi"):
    campos[k] = clima._upsample_bicubico_a(cor[k], *elev_c.shape) * mar_cd
```

- `cu, cv`: componentes de la corriente (velocidad).
- `sst_anom`: anomalía de SST (cálida/fría) — tiñe las flechas y circuitos.
- `psi`: función de corriente del flujo total — localiza los centros de giro
  para trazar los circuitos cerrados.

El re-escalado es **bicúbico periódico** (`_upsample_bicubico_a`): continuo, sin
los rombos de la bilineal a grandes aumentos. La máscara `mar_cd` anula las
corrientes que caen sobre lo que en el detalle es tierra.

Estos campos alimentan por igual el PNG `_clima.png` (flechas + circuitos vía
`_flechas_corriente` y `_dibuja_circuitos`) y la capa `corrientes`/`circuitos`
del `_capas.json` (visor HD). Resultado: **las corrientes del mapa ampliado son
las mismas del mapa pequeño**, solo que renderizadas con más calidad.

### 1.3 El flag `solo_corrientes` de `simular_clima`

`simular_clima(elev, ..., solo_corrientes=False)`. Con `True`, la función corta
justo después de la circulación oceánica (tras calcular `sst_anom` y `psi_tot`)
y devuelve solo `{cu, cv, sst, sst_anom, psi}`, **sin pagar** lluvia, drenaje,
biomas ni Köppen. Es el atajo que hace barato recalcular las corrientes sobre el
cuadro original.

### 1.4 Calidad del trazo en el visor (JS)

En `detallar/detallar.js::dibujarCor`, los circuitos (que llegan como polilíneas
en `capas.json`) se trazan con **curvas cuadráticas por los puntos medios** en
vez de segmentos rectos: los lazos salen redondos al hacer zoom, no poligonales.
El decimado del JSON se relajó de `::3` a `::2` (`exportar_capas`) para dar más
vértices sin inflar demasiado el archivo. Las flechas de corriente se dibujan
igual que antes.

### 1.5 Trampa resuelta: sin rótulo de temperatura

Una versión intermedia rotulaba cada giro con «corriente cálida/fría» (en PNG y
en canvas). **Se eliminó por completo**: el texto no debe renderizarse. Quedan
solo los lazos tintados (rojo = cálida, azul = fría, por `anom`) y las puntas de
flecha que marcan el sentido. Si se vuelve a pedir la distinción térmica, es el
color del trazo quien la lleva, no texto. (El `import ImageFont` se revirtió.)

---

## 2. Meandros — dial de sinuosidad

### 2.1 Objetivo

Que los ríos del detalle **serpenteen** en vez de bajar en las rectas
diagonales típicas del drenaje D8 sobre pendientes suaves y uniformes.

### 2.2 El dial

`sinuosidad ∈ [0, 3]`, por defecto **1.0**:
- `0` = drenaje puro por pendiente (ríos rectos).
- `1` = normal.
- `>1` = más serpenteante y más lagos/cuencas endorreicas.

Cableado completo: `web.html` (slider `det-sinu`) → `detallar.js` (POST
`/api/detallar`, compartido también por «Detallar con civilización») → `web.py`
(`DETALLE["sinuosidad"] = (0.0, 3.0, float, 1.0)`, se pasa `--sinuosidad`) →
`tecto.py::detallar(sinuosidad=1.0)` (lo guarda en el `.json` de meta) →
`clima.hidrologia_fina(elev_h, precip_h, hielo_h, sinuosidad=1.0)`.

### 2.3 Dos mecanismos independientes

El serpenteo se logra con **dos** mecanismos, porque solo uno no basta (ver la
trampa de §2.5):

**(a) Ruido de meandro en el DRENAJE** — un campo suave de grano ancho (~12
granos por mapa) se suma a la elevación de drenaje, solo en tierra:

```python
if sinuosidad > 0.0:
    ngr = 12
    g = rng_local.standard_normal((max(6, ngr*ny//nx), ngr))
    meandro = _upsample_bicubico_a(g, ny, nx)
    meandro = meandro / (abs(meandro).max() + 1e-12)   # NO in-place: vista RO
    elev_dren = elev_dren + 0.008 * sinuosidad * meandro * tierra
```

Desvía los cauces y —clave para §3— **siembra depresiones suaves** que el
relleno acotado no siempre vacía.

**(b) Ondulación VISUAL del trazo** (`_meandro_visual`) — un campo de
desplazamiento continuo `(dx, dy)` en **celdas** que mueve cada vértice de las
polilíneas al dibujarlas:

```python
def _meandro_visual(ny, nx, sinuosidad, tierra, rng):
    amp = 1.8 * sinuosidad
    campos = []
    for _ in range(2):                      # dos campos: dx y dy
        g = rng.standard_normal((ny//20, nx//20))
        o = _upsample_bicubico_a(g, ny, nx)
        campos.append(amp * o / (abs(o).max() + 1e-12))
    borde = _suaviza(tierra.astype(f32), 3)  # atenúa hacia la costa
    return campos[0]*borde, campos[1]*borde
```

Se guarda en `hidro["meandro"] = (mdx, mdy)` (o `None` si `sinuosidad == 0`) y
lo consumen **idénticamente**:
- `_dibujar_hidro_fina` (PNG `_climahd.png`): cada vértice `(i,j)` se dibuja en
  `((j+0.5+mdx[i,j])*kx, (i+0.5+mdy[i,j])*ky)`.
- `_rios_json` (capa web «cuencas y ríos»): el mismo desplazamiento, para que
  PNG y capa vectorial tracen exactamente el mismo cauce.

Como es un campo **continuo compartido**, los ríos vecinos se ondulan coherentes
y **ningún tramo se rompe**. La atenuación hacia la costa evita que las
desembocaduras «bailen» sobre el mar.

### 2.4 Por qué la amplitud es pequeña pero > 1e-4

El desempate del drenaje D8 usa ruido de amplitud `1e-4` (para romper empates
sin tocar la continuación bit-exacta de los mundos). El ruido de meandro (a) es
`0.008·sinuosidad`, **muy por encima** de ese desempate (para que se note) pero
pequeño frente a las pendientes regionales (para no cambiar de cuenca).

### 2.5 Trampa resuelta: el D8 con relleno vuelve a rectas

**Medí** en un plano inclinado sintético que perturbar la elevación de drenaje
**no basta** para meandros visibles: el relleno de depresiones (Planchon-Darboux)
aplana las cubetas del ruido y el flujo cruza el llano en línea recta al
desagüe. Datos:

- Grano **ancho** (~12 por mapa): la sinuosidad L/D (longitud de cauce /
  distancia en línea recta) pasa de ~1.4 a **>3** en un elev crudo.
- Pero tras el pipeline real (suavizado + relleno), el efecto vuelve a ~1.5.
- Grano **fino** (~48 por mapa) o mezclar una octava fina es **contraproducente**:
  el gradiente de alta frecuencia domina la dirección local y corta los detours.
- El **orden del rng** importó: consumir el desempate antes del meandro cambiaba
  la realización y el resultado.

Conclusión y decisión: el mecanismo (a) se quedó como **una sola octava ancha**
(que sí siembra depresiones útiles para los lagos), y el serpenteo **visible** se
delegó al mecanismo (b), que actúa sobre el trazo y es robusto al relleno. Por
eso hay dos mecanismos y no uno.

---

## 3. Lagos extendidos y cuencas endorreicas

### 3.1 Antes: lagos de 1 celda

La versión previa marcaba como lago solo la **celda del pozo** (terminal en
tierra con caudal grande). Eran puntos sueltos, no masas de agua.

### 3.2 Ahora: la cubeta embalsada entera

Tras rellenar depresiones, `W` es el «nivel de agua» y `elev_dren` el suelo. La
diferencia es la **huella del lago**:

```python
prof = (W - elev_dren) * tierra     # cuánto subió el relleno = profundidad
```

Un lago es toda celda con `prof > 0` cuya **cuenca recoge agua de verdad**:

```python
root = _raices(recv_flat)                       # cuenca (raíz del árbol D8)
caudal_raiz = caudal.reshape(-1)[root]          # caudal en el terminal
lagos = tierra_libre & (prof > 2e-4) & (caudal_raiz > umb*3.0)
lagos |= sink2d & tierra_libre & (caudal > umb*3.0)   # pozo mínimo de 1 celda
```

Cubre **dos** tipos de lago:
- **Con emisario**: la depresión se llenó y rebosa hacia el mar (relleno
  completo).
- **Endorreico**: pozo residual sin salida al mar (terminal en tierra).

### 3.3 Cuenca endorreica sin lago (aridez)

El filtro `caudal_raiz > 3·umbral` es lo que da realismo: una depresión en zona
**árida** existe como cuenca cerrada pero **no se moja** (la cuenca no recoge
suficiente agua). Así hay cuencas endorreicas secas, no todas con lago. El dial
`sinuosidad` (mecanismo 2.3a) es quien **siembra** estas depresiones: con
`sinuosidad=0` no hay ruido de meandro → casi sin lagos; con `sinuosidad≥1`
aparecen decenas.

### 3.4 Medición

En el cuadro de prueba (1024², paso 90): de ~6 celdas puntuales de lago a **~260
celdas** con `sinuosidad=2`. El log de `detallar` ahora informa el conteo:
`… N celdas de rio, M de lago …`.

---

## 4. Contrato de datos y flujo

```
tecto.py::detallar(mundo, paso, factor, salida,
                   sinuosidad=1.0, temperatura, precipitaciones, ...)
  │
  ├─ elev_orig = crust.elevation(...)          # cuadro pequeño (NX×NY)
  ├─ eu = _upsample_bicubico(elev_orig, factor)
  ├─ elev2 = eu + ruido fBm de detalle         # geografía menor
  ├─ elev_c = elev2 capada a ≤512              # malla física del clima
  │
  ├─ campos = clima.simular_clima(elev_c, T, P)          # clima del detalle
  ├─ cor    = clima.simular_clima(elev_orig, T, P,       # §1: corrientes del
  │                               solo_corrientes=True)  #     cuadro original
  ├─ campos[cu,cv,sst_anom,psi] = upsample(cor[...]) * mar_cd
  │
  ├─ hidro = clima.hidrologia_fina(elev_h, precip_h, hielo_h,
  │                                sinuosidad)            # §2, §3
  │            └─ devuelve rios, lagos, receptor, root, meandro=(mdx,mdy)
  │
  ├─ render_clima_hd(...) → _climahd.png                 # trazo con meandro §2.3b
  └─ exportar_capas(...)  → _capas.json                  # corrientes, circuitos,
                                                         #   ríos ondulados, lagos
```

### Claves nuevas / modificadas

| Sitio | Clave / firma | Qué es |
|---|---|---|
| `simular_clima` | `solo_corrientes=False` | corta tras la circulación oceánica; devuelve `{cu,cv,sst,sst_anom,psi}` |
| `hidrologia_fina` | `sinuosidad=1.0` | dial de meandros + siembra de depresiones |
| `hidrologia_fina` retorno | `"meandro": (mdx,mdy) \| None` | desplazamiento en celdas para ondular el trazo |
| `_meandro_visual(ny,nx,sinuosidad,tierra,rng)` | — | genera el campo `(mdx,mdy)`, atenuado hacia la costa |
| meta `.json` de detalle | `"sinuosidad": float` | dial efectivo del cuadro |
| `web.py DETALLE` | `"sinuosidad": (0.0,3.0,float,1.0)` | validación del slider |

---

## 5. Invariantes — NO romper

1. **Determinismo**. Toda la aleatoriedad usa `rng_local` de semilla fija
   (`12345` en `hidrologia_fina`, `[semilla, paso]` en el fBm de detalle).
   Mismo cuadro + mismos diales ⇒ mismo mapa, bit a bit. **Jamás** el rng global
   de `tecto` (la continuación de mundos debe seguir bit-exacta).
2. **Las corrientes del detalle salen del cuadro ORIGINAL**, nunca de la costa
   ruidosa del detalle. Si algún día se re-evalúan sobre `elev_c`, los giros se
   deforman (§1.1).
3. **Sin texto sobre las corrientes** (§1.5).
4. **El meandro visible va al TRAZO, no al drenaje** (§2.5). No intentes lograr
   sinuosidad solo perturbando `elev_dren`: el relleno la borra.
5. **El campo de meandro es compartido y continuo**: PNG y capa web usan el
   mismo `(mdx,mdy)` para trazar el mismo cauce; los tramos no se rompen porque
   el desplazamiento es coherente entre vértices vecinos.
6. **Lagos = cubeta embalsada con caudal**, no la celda del pozo (§3.2). El
   filtro `caudal_raiz > 3·umbral` mantiene secas las cuencas áridas.
7. **El orden del rng** dentro de `hidrologia_fina` fija la realización del
   ruido: no reordenes los consumos (desempate → meandro de drenaje → meandro
   visual) sin re-verificar.

---

## 6. Cómo verificar

- **Compilar**: `python -m py_compile clima.py tecto.py web.py` y
  `node --check detallar/detallar.js`.
- **Autoprueba de clima**: `python clima.py` — todas las invariantes deben pasar.
- **Punta a punta**: detallar un cuadro real a varios `--sinuosidad` y comparar
  recortes de la misma región fluvial:
  ```
  python tecto.py --detallar salidas/<sello>/mapa_mundo --desde-paso 90 \
      --factor 8 --sinuosidad 0 -o /tmp/s0
  python tecto.py --detallar salidas/<sello>/mapa_mundo --desde-paso 90 \
      --factor 8 --sinuosidad 2 -o /tmp/s2
  ```
  Con `s2` los codos de 90° del D8 salen curvados; el log reporta más celdas de
  lago.
- **Sinuosidad medida** (L/D en plano inclinado sintético): script en el
  historial; ~1.5 sin meandro visual, se dispara con el trazo ondulado.
