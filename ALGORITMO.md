# ALGORITMO.md — documentación técnica para retomar el proyecto

Documento de referencia de `tecto.py`. Explica **qué componente geológico se
agregó, por qué, con qué variables, cómo se comporta, qué motivó cada
decisión y la matemática exacta de cada elemento**, incluyendo las trampas
ya resueltas (no las reintroduzcas). Pensado para que una IA o un
desarrollador retome el proyecto sin el historial de la conversación
original.

Idioma del código y los comentarios: español. Un solo archivo (`tecto.py`,
~520 líneas), solo `numpy` + `Pillow`, sin dependencias de simulación.

Notación: `DT = 1`, así que "por paso" y "por unidad de tiempo" son lo
mismo; las derivadas temporales `d/dt` se implementan como incrementos por
paso. ∇ = gradiente, ∇² = laplaciano, ∇· = divergencia; todos discretos
sobre malla periódica (toro), ver §2.1.

---

## 1. Filosofía y arquitectura

**Objetivo**: mapas 2D animados (GIF) que *parezcan* tectónica de placas
real, con el mínimo costo computacional. La fidelidad física NO es objetivo:
cada mecanismo es la aproximación más barata que produce el efecto visual
correcto. Corre a ~25–30 pasos/s a 256² en un hilo de CPU.

Tres capas acopladas, cada una alimenta a la siguiente por paso:

```
MANTO 3D (48×48×8)          LITOSFERA 2D (256²)              RENDER
Mantle.step(sink) ──u,v──▶  Crust.step(u,v,hot) ──C,F,A──▶  elevation() → render()
        ▲    └──hot──────────────┘      │
        └────────── sink = trench ◀─────┘   (retroalimentación: slab pull)
```

- `u,v`: velocidad horizontal de la capa superior del manto (mueve las placas).
- `hot`: mapa de cabezas de pluma (genera volcanismo de punto caliente).
- `sink`: mapa de fosas de subducción reescalado al manto — enfría el manto
  superior y **ancla** las corrientes descendentes bajo las fosas (slab pull).

Todo el dominio es **toroidal** (periódico en x e y). Todas las operaciones
son vectorizadas numpy; no hay bucles por celda.

Estado completo: `Mantle.T` (48×48×8 floats), `Mantle.plumes` (lista de
dicts), y en `Crust`: `C` (espesor), `F` (fracción continental), `A` (edad
del fondo), `Pu/Pv` (momento), `D` (detalle), `trench`, `foreland`,
`volcano_arc`, `volcano_hot`. Nada más persiste entre pasos.

---

## 2. Operadores discretos y tabla de constantes

### 2.1 Operadores base (todos periódicos, `np.roll`)

- **Gradiente** (`grad_periodic`): diferencias centradas,
  `∂f/∂x ≈ (f[x+1] − f[x−1])/2`. Error O(Δx²).
- **Laplaciano** (`lap_periodic`): estrella de 5 puntos (2D) o de 3 por eje,
  `∇²f ≈ Σ_vecinos f − 2·n_ejes·f`. Con paso explícito `f += κ∇²f`, el
  criterio de estabilidad es `κ ≤ 1/4` en 2D (el autovalor más negativo del
  laplaciano discreto es −8; se necesita `|1 − 8κ| ≤ 1`). Todos los usos
  cumplen: `KAPPA = 0.08`, suavizado anti-anillos `0.05`.
- **Blurs multi-pasada**: kernel en cruz de 5 puntos con desplazamiento `s`:
  `f ← (f + f(±s,0) + f(0,±s))/5`. Su respuesta en frecuencia para un modo
  axial de número de onda k es `H(k) = (3 + 2cos(sk))/5`: vale 1 (pasa
  intacto) cuando `sk ≡ 0 (mod 2π)`, es decir para longitudes de onda que
  dividen a `s`. **De ahí el invariante de los shifts crecientes**: un blur
  de stride fijo s=2 es matemáticamente ciego al peine de 2 px (k=π ⇒
  sk=2π ⇒ H=1, gana 1 en cada pasada, jamás se atenúa); una pasada con s=1
  sí lo mata (H(π) = 1/5). Con shifts (1,2,3…) los ceros de atenuación de
  cada pasada no coinciden y todo el espectro alto se suprime.
  La varianza espacial del kernel por pasada es `σ² = 0.4·s²` por eje
  (peso 2/5 a distancia s); pasadas sucesivas suman varianzas:
  shifts (1,2,3) ⇒ σ ≈ 2.4 px; (1,2,3,4) ⇒ σ ≈ 3.5 px; (1,2) ⇒ σ ≈ 1.4 px.
- **`upsample`**: interpolación bilineal periódica (malla del manto → mapa).
- **`sample_nearest`**: vecino más cercano (máscaras y etiquetas, donde
  interpolar no tiene sentido).

### 2.2 Tabla de constantes

| Constante | Valor | Qué controla | Sensibilidad / escala derivada |
|---|---|---|---|
| `MX, MY, MZ` | 48, 48, 8 | resolución del manto | bajarla apenas cambia lo visual |
| `NX, NY` | 256 | resolución del mapa (CLI `-r`) | costo ~cuadrático |
| `DT` | 1.0 | paso de tiempo | no tocar; todo está calibrado a 1 |
| `KAPPA` | 0.08 | difusión térmica del manto | estable (≤ 0.25); alto = convección muere |
| `BUOY` | 0.9 | ganancia flotabilidad w ∝ ΔT | vigor de la convección |
| `VEL_SCALE` | 18.0 | px/paso que el manto mueve la corteza | **velocidad de la evolución geológica**; 14→18 cuando el usuario pidió cambios visibles con menos pasos |
| `C_OCEAN` | 0.35 | espesor de corteza oceánica nueva | |
| `C_CONT` | 1.0 | espesor continental inicial | |
| `SEA_LEVEL` | 0.52 | nivel del mar en unidades de C | más alto = más océano |
| `EROSION` | 0.008 | difusividad de la erosión | |
| `PLUME_EVERY` | 70 | pasos entre nacimientos de pluma | con vida media ~425 ⇒ ~6 plumas activas |
| `PLUME_AMP` | 0.06 | calor/paso inyectado por pluma | |
| `DECAY` | 0.006 | relajación de T al perfil conductivo | τ = 1/0.006 ≈ 167 pasos: cuánto sobrevive la anomalía de una pluma muerta |
| `AGE_TAU` | 70.0 | e-folding de la subsidencia térmica | ancho de las dorsales |
| `SUBSIDENCE` | 0.45 | hundimiento del fondo viejo vs dorsal | contraste de las dorsales |
| `TRENCH` | 6.0 | profundidad extra de las fosas (solo render) | |
| `SLAB_PULL` | 0.1 | enfriamiento del manto bajo fosas | fija los cinturones de subducción; 0.06→0.1 para rumbos más sostenidos |
| `RIGID` | 0.85 | mezcla fluido↔balsa rígida | <0.7: las colisiones no se completan |
| `LGRID` | 64 | malla reducida para etiquetar placas | |
| `MOMENTUM` | 0.02 | relajación del rumbo al manto | memoria de rumbo τ = 1/0.02 = 50 pasos |
| `RIDGE_PUSH` | 0.15 | empuje pendiente-abajo desde las dorsales | amplificado ×50 en estado estacionario (§4.3) |

Constantes "enterradas" importantes (no están arriba del archivo):

- `k0 = 2π·2.5/N` en `poisson_fft`: **número de celdas de convección** ⇒
  número efectivo de placas. Ver §3.2.
- Umbral `0.55` del ruido inicial en `Crust.__init__`: fracción de continente.
- `0.4` como corte océano/continente en `F` (subducción, arcos, fosas,
  islas). `0.5` en la máscara de balsas y el render.
- Percentil `97` en la detección de plumas (§3.6).
- `2.5` en la definición de falla transformante (§4.6).

---

## 3. Manto 3D — `Mantle`

Campo único: temperatura `T[z, y, x]`, z=0 fondo caliente, z=MZ−1 tope frío.
No hay campo de velocidad persistente; se deriva de `T` cada paso.

### 3.1 Flotabilidad (motor de la convección)

**Geología**: el material caliente sube, el frío baja.

**Matemática**: el manto real convecta en régimen de Stokes con número de
Prandtl ≈ ∞: la inercia es despreciable y la velocidad es una función
*instantánea* (diagnóstica) de la densidad, no una variable de estado. El
balance vertical de fuerzas es `μ∇²w ≈ Δρ·g` con `Δρ = −ρ₀α(T − T̄)`
(Boussinesq); colapsando el operador viscoso a una constante queda la
aproximación más barata posible:

```
w[z] = BUOY · (T[z] − ⟨T[z]⟩)        ⟨·⟩ = media horizontal de la capa
```

Restar la media de la capa no es cosmético: garantiza `∬ w dA = 0` en cada
capa — el flujo vertical neto es cero, consistente con un dominio periódico
que no puede inflarse ni desinflarse.

### 3.2 Continuidad por FFT (de dónde salen u,v)

**Geología**: lo que sube en una pluma debe divergir horizontalmente arriba
y converger abajo — eso arrastra las placas.

**Matemática**: incompresibilidad 3D `∂u/∂x + ∂v/∂y + ∂w/∂z = 0` ⇒ la
divergencia horizontal de cada capa está prescrita:

```
∇·(u,v)|z = −∂w/∂z|z        (∂w/∂z por diferencias centradas, np.gradient)
```

Se asume el flujo horizontal **irrotacional** (se descarta la parte
toroidal, aceptable porque las fuentes de flotabilidad son poloidales):
`(u,v) = ∇φ`, lo que convierte la restricción en un Poisson 2D por capa:

```
∇²φ = −∂w/∂z
```

En Fourier el laplaciano es diagonal: `φ̂(k) = R̂(k) / (−|k|²)` con
`R̂ = FFT(−∂w/∂z)` y `k` en radianes/celda (`np.fft.fftfreq·2π`; se usa el
símbolo continuo −|k|², no el discreto −4sin²(k/2) — el error solo importa
en k altos y ahí es irrelevante). Costo O(N² log N), 8 capas de 48².

**Trampa resuelta (crítica) — amortiguación de baja frecuencia**: el kernel
`1/|k|²` diverge cuando k→0: el modo de mayor escala recibe ganancia
arbitrariamente grande ⇒ una sola celda de convección global ⇒ todos los
continentes colapsaban en un supercontinente y la animación moría. Solución:

```
φ̂(k) = R̂(k) · (1 − e^{−|k|²/k0²}) / (−|k|²)        k0 = 2π·2.5/N
```

Análisis del kernel efectivo `Gain(k) = (1 − e^{−k²/k0²})/k²`:
para k ≫ k0 el factor → 1 (Poisson intacto); para k → 0, expandiendo la
exponencial, `Gain → 1/k0²` — la ganancia **satura** en vez de divergir.
Toda estructura mayor que la longitud de onda `2π/k0 = N/2.5` celdas
responde como si midiera N/2.5: el dominio contiene ~2.5 celdas de
convección por lado, que físicamente es "las celdas miden ~la profundidad
del manto, no todo el planeta". El modo medio k=0 queda exactamente anulado
(damp(0) = 0), así que el `k2[0,0] = 1` del código es solo para evitar el
0/0, no afecta el resultado. **Si quitas este damping, el modelo se rompe.**

### 3.3 Transporte

**Advección semi-lagrangiana** (`advect`): resuelve `Df/Dt = 0` (derivada
material nula) hacia atrás:

```
f^{n+1}(x) = I[f^n](x − u·Δt)        I = interpolación bilineal periódica
```

Es **incondicionalmente estable** porque la interpolación bilineal es una
combinación convexa (pesos ≥ 0 que suman 1): vale el principio del máximo,
`min f^n ≤ f^{n+1} ≤ max f^n`, no se crean extremos nuevos a ninguna
velocidad — por eso no hay límite CFL y `VEL_SCALE = 18 px/paso` es legal.
El precio es **difusión numérica**: para desplazamiento fraccional `a`, la
interpolación lineal equivale a una difusión efectiva por eje

```
κ_num ≈ a(1−a)/2 · Δx²/Δt        (máximo 1/8 cuando a = ½)
```

Esta difusión es la que convierte las costas de `F` en neblina — el término
biestable de §4.9 existe exactamente para contrarrestarla, y la gota de
textura original de §4.14 compensa lo mismo en `D`.

**Transporte vertical — peculiaridad conocida (no-op)**: las dos líneas de
upwind vertical del código se cancelan algebraicamente. Con
`dTdz_up = T − T(z−1)` y `dTdz_dn = T(z+1) − T` calculados una sola vez:

```
T += 0.5·(w⁺·(−dTdz_up)·(−1) + w⁻·(−dTdz_dn)·(−1))   # = +0.5·(w⁺·up + w⁻·dn)
T −= 0.5·(w⁺·dTdz_up + w⁻·dTdz_dn)                    # = −0.5·(w⁺·up + w⁻·dn)
```

La suma es exactamente 0 (verificado numéricamente: 1e−16). El acoplamiento
vertical real del manto viene de la difusión vertical explícita
(`T[1:-1] += KAPPA·(T[z−1] − 2T[z] + T[z+1])`), de las condiciones de borde
(fondo caliente ruidoso, tope frío), de la inyección de plumas en las 3
capas inferiores y del slab pull. El modelo está calibrado con este no-op
dentro; si se "arregla" (un upwind real: `T −= Δt·(w⁺·dTdz_up + w⁻·dTdz_dn)`
con estabilidad `|w|Δt ≤ 1`), hay que recalibrar `BUOY`, `DECAY` y
`PLUME_AMP`, y todos los mundos generados cambian.

**Difusión + bordes térmicos**: difusión horizontal y vertical con `KAPPA`;
fondo re-fijado cada paso a `T = 1 + 0.12·N(0,1)` (el ruido reorganiza la
convección a largo plazo), tope `T = 0`, y clip global a [−0.2, 1.4].

### 3.4 Ciclo de vida de plumas (dinamismo a largo plazo)

**Por qué se agregó**: el usuario reportó que "pasado un tiempo la animación
deja de ser dinámica" — la convección se estacionaba. También pidió que
nazcan plumas nuevas y mueran las viejas, y después que las plumas se muevan.

**Matemática**: cada `PLUME_EVERY = 70` pasos nace una pluma
`{y, x, dy, dx, age, life}` con posición uniforme, deriva fija por pluma
`dy, dx ~ N(0, 0.04)` celdas/paso y vida `life ~ U{250…600}`. Cada paso
inyecta en las 3 capas inferiores una gaussiana **periódica** (métrica
toroidal `d = min(|Δ|, N − |Δ|)` por eje):

```
blob(y,x) = exp(−(dy² + dx²)/(2r²))            r = 3.5 celdas
T[z] += PLUME_AMP · fade · (1 − z/3) · blob    z ∈ {0,1,2} ⇒ pesos 1, ⅔, ⅓
fade = min(age/60, 1, (life − age)/60)          trapecio: 60 pasos de fundido
```

La muerte real la produce la relajación exponencial al perfil conductivo:

```
dT/dt = DECAY·(perfil − T)   ⇒   anomalía(t) = anomalía₀·e^{−DECAY·t}
```

con τ = 1/DECAY ≈ 167 pasos (una anomalía huérfana se reduce a la mitad en
ln2/0.006 ≈ 116 pasos). Escalas derivadas: vida media 425 pasos y nacimiento
cada 70 ⇒ ~6 plumas activas en régimen; deriva |d| ~ 0.05 celdas/paso por
~400 pasos ⇒ desplazamiento ~20 celdas ≈ ⅖ del dominio — suficiente para que
un punto caliente marino deje una **cadena de islas lineal** (la placa y la
pluma se mueven distinto, como Hawái).

### 3.5 Slab pull (retroalimentación corteza→manto)

**Geología**: la losa fría que subduce tira de la placa y ancla la corriente
descendente.

**Implementación**: `T[z] −= SLAB_PULL·sink` en las capas z = MZ−2, MZ−3,
con `sink = upsample(crust.trench)` a 48². Es un forzamiento frío
proporcional a la intensidad de subducción: baja la T local ⇒ baja w (§3.1)
⇒ la corriente descendente se refuerza justo bajo la fosa ⇒ más
convergencia ⇒ más fosa. Un lazo de retroalimentación positiva estabilizado
por `DECAY` y la difusión: sin él, cada pluma nueva redibujaba todo el patrón
de flujo y los rumbos de placa no se sostenían.

### 3.6 Detección de cabezas de pluma (`self.hot`)

**Por qué es así**: el volcanismo de punto caliente necesita saber DÓNDE hay
una pluma tocando la litosfera. La primera versión usaba un umbral fijo
sobre `w` de una capa: **nunca disparó** (se midió `hot max = 0.008` vs
umbral 0.08 — tres GIF "distintos" salieron idénticos porque los hotspots
eran todos cero).

**Matemática (estadística de orden, auto-escalada)**:

```
wcol = ⟨max(w, 0)⟩_{z=1..MZ−2}          columna ascendente media, manto medio
hot  = clip((wcol − P97(wcol)) / (3·mean(wcol)), 0, 1)
```

Usar el percentil 97 como umbral fija **por construcción** la fracción de
área marcada como pluma en el 3%, sea cual sea el vigor absoluto de la
convección en ese momento (el umbral se mueve con la distribución). La
normalización por `3·media` hace la intensidad adimensional y comparable
entre pasos. No cambies esto a un umbral absoluto: la escala de w varía en
órdenes de magnitud a lo largo de una corrida.

---

## 4. Litosfera 2D — `Crust.step(um, vm, hot)`

Dos campos primarios advectados por la velocidad del manto
(`u = upsample(um)·VEL_SCALE`, ídem v):

- `C` — espesor de corteza (lo que se ve: elevación ∝ C − SEA_LEVEL).
- `F` — fracción continental ∈ [0,1], **conservada** (§4.9). `F` decide el
  *tipo* de corteza; `C` decide el *relieve*. Regla de oro: **la posición de
  continentes y volcanes depende solo del manto y de F, nunca de C** — si un
  ajuste solo toca C, los rasgos no se moverán, solo cambiará su altura.

Del gradiente de velocidad se derivan los tres escalares que clasifican cada
punto del mapa (§4.6 da la descomposición completa):

```
div = ∂u/∂x + ∂v/∂y      conv = max(−div, 0)      opening = max(div, 0)
shear = √((∂u/∂x − ∂v/∂y)² + (∂u/∂y + ∂v/∂x)²)
```

El orden del pipeline dentro de `step()` NO es arbitrario. Orden real:
placas/momento/velocidad → advección → transformantes → orogenia/subducción
→ arco andino → cuenca de antepaís → rift/desgarramiento → biestable →
conservación de F → piso continental → edad A → fosa → hotspots/islas →
arcos de islas → volcanes → detalle → erosión → suavizado → boundary.

### 4.1 Rigidez de placa (balsas rígidas)

**Por qué se agregó**: el usuario reportó "las masas de tierra deben
colisionar" — con la corteza tratada como fluido, el campo de velocidad
tiene un **punto de estancamiento** en la línea de convergencia (u → 0
linealmente al acercarse, así que la distancia restante decae
exponencialmente): los continentes frenaban sin llegar y los mares nunca
terminaban de cerrarse. Una placa real es rígida: se mueve entera con una
sola velocidad.

**Matemática** (puro numpy, sin scipy):

1. Submuestrear `F > 0.5` a `LGRID² = 64²` por vecino más cercano.
2. `label_components`: componentes conexas periódicas por **propagación de
   máximos** — cada celda toma `lab ← max(lab, vecinos)` restringido a la
   máscara. Cada iteración es una dilatación morfológica que propaga el id
   máximo una celda; el punto fijo se alcanza en ≤ diámetro del componente
   más grande (acotado por `2·LGRID`), y la iteración corta antes al
   converger.
3. Velocidad de balsa por placa p: la media
   `ū_p = (1/|p|) Σ_{i∈p} Pu_i` (vía `np.bincount`). No es arbitraria: la
   traslación rígida `c` que minimiza `Σ_{i∈p} |v_i − c|²` es exactamente la
   media — es el ajuste L2-óptimo de un movimiento rígido sin rotación (la
   rotación de placa no se modela; sería el siguiente término del ajuste).
   Nota: la media se toma sobre el **momento** `Pu/Pv` (§4.2), no sobre la
   velocidad instantánea del manto.
4. Rellenar cada placa con su media, subir a 256² y mezclar:

```
w = RIGID · F · clip(1 − 25·opening, 0, 1)
u_final = (1 − w)·u_manto + w·u_balsa
```

El factor `clip(1 − 25·opening)` **ablanda la placa donde hay rift activo**
(w→0 si opening > 0.04): sin él, la rigidez promediaría el rift con el resto
de la placa y una pluma nueva jamás podría desgarrar un continente.

**Tres trampas resueltas aquí (el bug más difícil del proyecto —
"crestas paralelas artificiales" dentro de los continentes, bandas de ~5 px):**

1. **Reetiquetar CADA paso.** Se etiquetaba cada 10 pasos; con etiquetas
   viejas el borde de ataque de la balsa usa la huella desactualizada del
   continente: la franja entre la huella vieja y la real recibe velocidad de
   manto contra velocidad de balsa ⇒ línea de convergencia falsa ⇒ cresta
   orogénica artificial paralela al frente, una por cada reetiquetado.
2. **El océano lleva su velocidad LOCAL, no cero.** Las celdas sin etiqueta
   (océano y huecos/suturas dentro de un continente) quedaban con velocidad
   0: un cero rodeado de velocidad finita es un pozo con `div < 0` en el
   lado de entrada y `div > 0` en el de salida ⇒ pares cresta/fosa
   artificiales espaciados por la malla de balsas.
3. **Suavizar u_balsa tras el upsample** (shifts 1,2,3). El salto 64→256
   deja mesetas de 4 px con saltos de velocidad en sus bordes; cada salto es
   una delta de divergencia que deposita crestas en escalera. El blur con
   varianza acumulada σ ≈ 2.4 px (§2.1) redondea las mesetas por debajo del
   umbral en que la orogenia las detecta.

Diagnóstico que funcionó: volcado numérico de perfiles 1D de `C` y
`foreland` a través de la zona con artefactos (oscilaban con período ~5 px),
tras descartar hipótesis falsas (dithering del GIF — refutado comparando
PNG RGB; textura de detalle; peines de blur).

### 4.2 Memoria de rumbo (momento, `Pu/Pv`)

**Por qué se agregó**: aun con balsas, "las placas no mantienen su
movimiento a lo largo de una dirección" (usuario): cada pluma nueva desviaba
a los continentes antes de que cruzaran el océano; las colisiones nunca se
completaban.

**Matemática**: campo de momento que viaja advectado **con la placa** y se
relaja hacia el manto instantáneo:

```
Pu ← advect(Pu, u, v)·(1 − λ) + λ·u          λ = MOMENTUM = 0.02
```

Siguiendo una parcela de placa, esto es una **media móvil exponencial** de
la velocidad del manto a lo largo de su trayectoria:

```
Pu(t) = λ · Σ_{j≥0} (1−λ)^j · u(t−j)
```

con constante de memoria τ = 1/λ = **50 pasos**: el rumbo de la placa es la
velocidad del manto filtrada paso-bajo a 50 pasos. Consecuencia calibrable:
una perturbación del manto más corta que ~τ (una pluma joven) casi no
desvía el rumbo; bajar `MOMENTUM` da placas más tercas. Es el análogo barato
de la inercia de placa / slab pull.

### 4.3 Empuje de dorsal (ridge push)

**Por qué se agregó**: el usuario pidió que "plumas o cordilleras que surgen
en medio del océano o de los continentes empujen los continentes… hacia
colisionar en la dirección contraria". La advección del manto sola no
sostiene ese empuje lejos de la pluma.

**Matemática**: en la Tierra el ridge push es literalmente el deslizamiento
gravitacional de la placa por la pendiente de la dorsal: fuerza ∝ −∇h con h
la elevación del fondo. Aquí la elevación del fondo joven es
`h ∝ ridge = e^{−A/AGE_TAU}` (§4.10), así que:

```
(Pu, Pv) −= RIDGE_PUSH · ∇(e^{−A/AGE_TAU})
```

(y `∇ridge = −(1/AGE_TAU)·e^{−A/AGE_TAU}·∇A`: el empuje apunta de fondo
joven a fondo viejo, alejándose de la dorsal por ambos flancos).

**Por qué se aplica al momento y no a la velocidad**: la actualización del
momento es `P ← (1−λ)P + λu − g` con `g = RIDGE_PUSH·∇ridge`. En estado
estacionario (`P` constante sobre una pendiente sostenida):

```
λP = λu − g   ⇒   P* = u − g/λ = u − (RIDGE_PUSH/MOMENTUM)·∇ridge
```

La fuerza por paso queda **amplificada ×(1/λ) = ×50**: una pendiente de
dorsal modesta aporta hasta `0.15/0.02 = 7.5·|∇ridge|` de velocidad
sostenida. Ese factor es el que empuja las dos orillas de un rift a través
de todo el océano hasta colisionar en el lado opuesto del toro; aplicado a
la velocidad instantánea, el empuje sería 50 veces más débil e invisible.

### 4.4 Orogenia y subducción (la asimetría clave)

**Geología (pedida explícitamente por el usuario)**: solo la corteza
oceánica subduce; la continental nunca se hunde bajo la oceánica. Colisión
continente-continente → cordillera (Himalaya); océano-continente → fosa +
cordillera costera (Andes).

**Matemática**: crecimiento/consumo **multiplicativo** en C:

```
dC/dt = −1.5·conv·C    donde F < 0.4   (subducción: el océano se consume)
dC/dt = +1.8·conv·C    donde F ≥ 0.4   (orogenia: el continente se apila)
```

Al ser lineal en C, la solución bajo convergencia sostenida es exponencial:
`C(t) = C₀·exp(±k·∫conv dt)` — la corteza gruesa se engrosa más rápido, lo
que **focaliza** las cordilleras en cinturones estrechos en vez de inflar
mesetas anchas (con crecimiento aditivo `dC/dt = k·conv` salían mesetas).
La asimetría entera es el `where(F < 0.4)`; los factores 1.5/1.8 se
calibraron a ojo (más apilamiento ⇒ mapa nevado; menos ⇒ sin cordilleras).
El clip final `C ∈ [0.2, 2.2]` acota la exponencial.

### 4.5 Arco de subducción tipo Andes

**Por qué se agregó**: interjección del usuario: "en la subducción la placa
se hunde una debajo de otra y eso genera una cadena montañosa" — faltaba la
cordillera costera sobre la placa que cabalga.

**Matemática**: la fosa está en el lado oceánico (`F < 0.4`) pero la
cordillera debe crecer en el continental (`F` alto) y **desplazada tierra
adentro**. Ambas cosas las hace una convolución:

```
arc = G_σ * (conv·[F < 0.4])          blur shifts (1,2,3) ⇒ σ ≈ 2.4 px
C  += 1.8 · arc · F · DT
```

La convolución `G_σ` derrama la señal de la fosa ~σ píxeles hacia ambos
lados; el producto por `F` recorta el lado oceánico y deja solo la cola que
cayó sobre el continente ⇒ una banda de crecimiento a distancia O(σ) de la
fosa, paralela a ella: la cordillera costera. También alimenta `volcano_arc`.

### 4.6 Fallas transformantes

**Por qué se agregó**: pedida por el usuario; donde las placas solo se rozan
no debe haber ni orogenia ni fosa.

**Matemática**: el gradiente de velocidad 2D se descompone en cuatro modos
independientes:

```
L = [[∂u/∂x, ∂u/∂y], [∂v/∂x, ∂v/∂y]]
div     = ∂u/∂x + ∂v/∂y            expansión isótropa (traza)
ω       = ∂v/∂x − ∂u/∂y            vorticidad (rotación rígida: NO deforma)
s₁      = ∂u/∂x − ∂v/∂y            cizalla normal (estira x, comprime y)
s₂      = ∂u/∂y + ∂v/∂x            cizalla pura a 45°
shear   = √(s₁² + s₂²)             magnitud de deformación a área constante
```

`shear` es invariante ante rotación del sistema de coordenadas (s₁ y s₂ se
mezclan como un doblete bajo rotación, su norma no cambia): mide "cuánto se
distorsiona la forma sin cambiar el área", exactamente el régimen de
deslizamiento de rumbo. La vorticidad se excluye adrede — girar en bloque no
deforma. El clasificador:

```
transform = max(shear − 2.5·|div|, 0)
C −= 0.3 · transform · DT              solo un valle de falla sutil
```

es un **cono en el plano (|div|, shear)**: solo los puntos con cizalla > 2.5
veces la divergencia cuentan como transformantes. En dorsales y fosas hay
cizalla, pero la divergencia los descalifica; solo el deslizamiento casi
puro sobrevive al recorte. La pendiente 2.5 es el dial de selectividad.

### 4.7 Cuenca de antepaís (foreland basin)

**Por qué se agregó**: pedida por el usuario — la corteza se flexiona hacia
abajo frente a la cordillera en crecimiento; si baja del nivel del mar se
inunda (mar interior, como el que hubo frente a los Andes).

**Matemática**: la física real es la flexión de una placa elástica bajo
carga: `D∇⁴w + Δρ·g·w = q(x)`, cuya función de Green es una oscilación
amortiguada `w(x) ∝ e^{−x/α}(cos x/α + sin x/α)` — un foso (moat) junto a la
carga y un abombamiento periférico. El sustituto barato es una **diferencia
de gaussianas** (DoG), que reproduce el foso anular:

```
G     = (conv + arc)·F                     carga orogénica
basin = clip(G_σ * G − 1.5·G, 0)·[F > 0.3]  σ ≈ 3.5 px (shifts 1,2,3,4)
```

El término `G_σ*G` reparte la carga en un halo ancho; restar `1.5·G` la
cancela con creces en el núcleo del orógeno ⇒ el resultado positivo queda
solo en el **anillo** a distancia ~σ..3σ, que es donde va el foso flexural.
Se aplica **solo en el render** (`elev −= 14·foreland` en `elevation()`), no
toca `C`: la depresión existe mientras el orógeno crece y desaparece con él,
sin dejar cicatriz permanente en el espesor.

### 4.8 Rift y desgarramiento continental

- **Rift genérico**: relajación hacia corteza oceánica donde hay divergencia:
  `dC/dt = −1.2·opening·(C − C_OCEAN)` ⇒ decaimiento exponencial de C hacia
  `C_OCEAN` con tasa proporcional a la apertura (donde la divergencia se
  sostiene, C → C_OCEAN con τ = 1/(1.2·opening) pasos).
- **Desgarramiento de F, con umbral**:
  `dF/dt = −2·max(opening − 0.006, 0)·F`. La rampa con umbral es la clave:
  la divergencia débil de fondo (ruido del manto, |div| ~ 10⁻³) queda por
  debajo de 0.006 y **no roe los continentes** — el usuario pidió que "las
  zonas continentales difícilmente desaparecen". Solo un rift vigoroso y
  sostenido (opening ≫ 0.006, una pluma real debajo) rompe la placa.

### 4.9 Conservación y cohesión de F (por qué los continentes no desaparecen)

Tres mecanismos, en este orden dentro del paso:

1. **Anti-difusión biestable** (tipo Allen–Cahn):

   ```
   dF/dt = r·F(1−F)(2F−1)·clip(1 − 25·opening, 0, 1)        r = 0.08
   ```

   El término de reacción es el gradiente descendente del doble pozo
   `V(F) = ½F²(1−F)²` (se verifica: `−dV/dF = F(1−F)(2F−1)`): tiene puntos
   fijos en F = 0, ½, 1. Linearizando `f(F) = F(1−F)(2F−1)`,
   `f'(0) = f'(1) = −1` (estables) y `f'(½) = +½` (inestable): todo valor
   intermedio cae al pozo más cercano con tasa ~r, lo que re-afila los
   frentes de costa exactamente contra la difusión numérica κ_num de la
   advección (§3.3) — es una ecuación de Allen–Cahn donde el término
   difusivo lo pone "gratis" el error de interpolación. El factor
   `clip(1 − 25·opening)` apaga la reacción donde hay rift activo, para no
   volver a soldar lo que la pluma está desgarrando.

2. **Renormalización (conservación exacta)**:
   `F ← F · F_total / ΣF`. Es la proyección multiplicativa sobre la
   restricción `ΣF = F_total` (el multiplicador de Lagrange barato); al ser
   multiplicativa preserva F ≥ 0 y los ceros exactos, cosa que una
   corrección aditiva no haría. Un rift *parte* un continente, no lo borra;
   una colisión lo *concentra*, no lo crea.

3. **Piso de flotabilidad + relajación diferencial**:

   ```
   C ← max(C, piso)          piso = C_OCEAN + F·(C_CONT − C_OCEAN)·0.92
   dC/dt = −0.001·(C − piso)·(1 − 0.75·F)
   ```

   El `max` hace **imposible** que un continente adelgace bajo su espesor
   base, pida lo que pida la subducción. La relajación del exceso tiene
   constante de tiempo τ = 1000 pasos sobre océano y τ = 4000 sobre
   continente puro (factor 1−0.75F): el relieve oceánico decae, las
   cordilleras interiores casi no (pedido del usuario).

**Historia**: la primera versión sin `F` perdía los continentes enteros por
subducción en ~500 pasos. Un término posterior de "concentración de F" +
clipping encogía el área continental — se eliminó (C ya se apila solo;
duplicarlo en F rompía la conservación).

### 4.10 Edad del fondo oceánico y dorsales submarinas

**Por qué se agregó**: pedido explícito de "cordilleras submarinas".

**Matemática**: la edad `A` obedece `DA/Dt = 1` (cada parcela envejece un
paso: advección semi-lagrangiana + `+DT`), con **renacimiento multiplicativo
en los rifts**: `A ← A·clip(1 − 12·opening, 0, 1)` (un rift vigoroso resetea
la edad a ~0 en pocas pasadas). Nace "vieja" (`5·AGE_TAU`) para que el
océano inicial no parezca recién creado, y se acota a `10·AGE_TAU`.

En el render, la **subsidencia térmica**:

```
elev −= SUBSIDENCE · (1 − e^{−A/AGE_TAU}) · [océano]
```

En la Tierra el enfriamiento de semiespacio da profundidad ∝ √edad
(saturando hacia viejo); la exponencial saturante tiene la misma forma
monótona-saturante, es acotada por construcción y cuesta una sola `exp`.
Perfil resultante: dorsal somera (A≈0 ⇒ resta ≈0) que cae al abisal con
e-folding `AGE_TAU = 70` pasos de edad — el ancho visual de la dorsal es
directamente `AGE_TAU · velocidad_de_separación` píxeles por flanco.
`A` también alimenta el ridge push (§4.3): la edad es la única memoria de
dónde estuvo cada dorsal.

### 4.11 Fosas de subducción

`trench = conv·[F < 0.4]` — convergencia sobre corteza oceánica. Tres usos:
depresión batimétrica en el render (`elev −= TRENCH·trench`, el rasgo oscuro
que bordea los márgenes activos), semilla de los arcos de islas (§4.12), y
retroalimentación `sink` al manto (§3.5).

### 4.12 Volcanismo: puntos calientes, islas y arcos

Pedidos del usuario: puntos rojos como volcanes en cordilleras de subducción
y orígenes de pluma; las plumas marinas generan islas; después: "que generen
menos tierra y más volcanes".

- **Puntos calientes**: `hs = upsample(hot)·0.25`. Sobre océano
  (`isl = hs·[F < 0.4]`) el edificio volcánico crece con **saturación**:

  ```
  dC/dt = 0.12 · isl · clip(0.9 − C, 0, 1)
  ```

  Ecuación logística-recortada con techo C = 0.9: como
  `SEA_LEVEL = 0.52`, el techo equivale a elevación cruda 0.38·1.1 ≈ 0.42,
  que la escala cuadrática del render (§5) comprime a ~0.12 — una isla
  verde baja que apenas asoma, jamás una montaña nevada. La tasa era 0.25 y
  se bajó a 0.12 cuando el usuario pidió menos tierra (con 0.25 las islas
  crecían a masas con nieve). Además `A ← A·clip(1 − 3·isl, 0.2, 1)`: el
  domo térmico rejuvenece el fondo, que queda somero alrededor (como el
  enjambre batimétrico hawaiano).
- **Arcos de islas (tipo Marianas)**: la fosa difuminada (shifts 1,2 ⇒
  σ ≈ 1.4 px) crece solo sobre océano y con techo mayor (C ≤ 1.1 ⇒ montaña
  baja):

  ```
  C += 2.0 · (G_σ*trench) · halo · [F < 0.4] · clip(1.1 − C, 0, 1)
  halo = clip(1 − 50·trench, 0, 1)
  ```

  **Trampa resuelta**: el `halo` excluye el núcleo de la fosa — sin él, el
  crecimiento (+2.0·iarc) y la subducción (−1.5·conv·C, §4.4) actuaban
  sobre el mismo píxel y la subducción ganaba: el arco nunca emergía. El
  halo desplaza el crecimiento al anillo vecino, que es donde están los
  arcos reales (la isla crece sobre la placa que cabalga, no en la fosa).
- **Campos para el render**: `volcano_arc = arc·F + iarc·[F<0.4]` y
  `volcano_hot = hs`. Los puntos se pintan en `render()` (§5).

### 4.13 Erosión con rebote isostático

**Por qué es así**: el usuario pidió que el relieve continental resista
("por eso los Apalaches persisten") y que la erosión no borre las
cordilleras viejas.

**Matemática**: la erosión difusiva estándar es `∂C/∂t = ε∇²C` (rebaja
picos, rellena valles). Aquí se hace **asimétrica**:

```
d = EROSION · ∇²C · [C > SEA_LEVEL] · (1 − 0.7·F)
C += (d < 0) ? 0.35·d : d
```

El laplaciano es negativo en picos y positivo en valles; multiplicar solo la
parte negativa por 0.35 significa: *los valles reciben el depósito completo,
pero las cimas solo pierden el 35% de lo que la difusión pediría*. Balance
de masa: la difusión pura conserva ΣC (`Σ∇²C = 0` en el toro); con la
asimetría, `ΣΔC = Σd⁺ + 0.35·Σd⁻ > 0` — la erosión **inyecta volumen
neto**, y esa inyección ES el rebote isostático: el 65% "no perdido" es la
raíz cortical que asciende al descargarse la cordillera. El factor
`(1 − 0.7·F)` reduce además toda la erosión ×0.3 sobre continente puro.

Después hay un suavizado global débil `C += 0.05·∇²C` (difusión explícita,
estable por §2.1) cuyo único fin es borrar los "anillos de crecimiento" de
la orogenia (franjas de 2 px depositadas paso a paso por el frente de
convergencia al moverse).

### 4.14 Detalle fractal advectado

Textura multi-octava `D0` (suma de ruidos upsampleados a escalas 16, 32,
64, 128 con amplitudes 1, 0.5, 0.25, 0.12 — espectro ~1/f); cada paso:

```
D ← advect(D, u, v)·0.90 + 0.10·D0
```

La misma media móvil exponencial de §4.2 (λ = 0.1, τ = 10 pasos): la textura
viaja pegada a la placa (las costas rugosas se mueven con el continente) y
la gota de original repone la varianza que la difusión numérica de la
advección destruye (sin la gota, D → constante en ~100 pasos; con λ mayor,
la textura se vuelve estática respecto al mapa y "flota" sobre las placas).
**Solo afecta al render** (§5), jamás a la simulación: rugosidad gratis.
CLI `-d/--detalle`.

### 4.15 Bordes de placa (`boundary`, valor de retorno)

```
boundary = (|div| + shear) · (1 − clip(30·hs, 0, 0.95))
```

Suma de los dos modos deformantes de §4.6 (la actividad total del límite de
placa), atenuada ≥95% sobre cabezas de pluma.
**Trampa resuelta**: la atenuación debe aplicarse **antes** de la
normalización por percentil del render — una versión previa atenuaba
después, y como el percentil re-escala todo el campo por su rango, las
manchas redondas de las plumas volvían a aparecer amplificadas.

---

## 5. Render

### 5.1 `elevation(detail)`

```
elev = (C − SEA_LEVEL)·1.1
elev = (elev > 0) ? 0.5·elev² + 0.03 : elev        escala cuadrática en tierra
elev −= SUBSIDENCE·(1 − e^{−A/AGE_TAU})·[océano]    §4.10
elev −= TRENCH·trench                               §4.11
elev −= 14·foreland                                 §4.7
elev += detail·D·(0.04 + 0.11·clip(elev, 0, 1))
```

**Por qué cuadrática**: la derivada del mapeo es `d(elev')/d(elev) = elev` —
crece linealmente con la altura. Las elevaciones bajas se comprimen (todo el
interior continental queda en llanura verde) y solo las zonas de colisión,
con C alto, alcanzan la pendiente para llegar a marrón/nieve. Sin ella, el
interior continental entero salía marrón uniforme. El `+0.03` mantiene la
costa por encima del degradado marino. El detalle fractal se modula con la
altura (`0.04` en el mar, hasta `0.15` en cumbre): montaña rugosa, mar liso.

### 5.2 `render(elev, boundary, volcanoes)`

- **Tinte hipsométrico**: interpolación lineal por canal (`np.interp`) sobre
  la tabla `HYPSO` (abisal → costa → verde → marrón → nieve).
- **Sombreado**: `shade = clip(1 + 2.2·(∂elev/∂x − ∂elev/∂y), 0.78, 1.22)` —
  es la derivada direccional `∇elev·(1,−1)` = iluminación lambertiana
  linealizada con el sol desde el noroeste; el clip acota el contraste.
- **Bordes de placa**: `boundary` con 2 pasadas de blur s=1, normalizado por
  su percentil 98 (`b = clip(boundary/P98 − 0.6, 0, 1)`) — de nuevo un
  umbral relativo, no absoluto: la actividad tectónica total varía con el
  tiempo. Mezcla alfa 0.45 con rojo oscuro (180,40,30).
- **Volcanes**: para cada campo `(vol, vmin, win)` se calcula el máximo
  local por **dilatación morfológica** (max de la ventana `(2·win+1)²` vía
  `np.roll`): un píxel es volcán si `vol == max_ventana` (máximo local) Y
  supera el umbral doble `max(vmin, 0.35·max_global)` (absoluto: hay
  actividad real; relativo: no pintar la cola débil). Los puntos se dilatan
  1 px (cruz de 5) y se pintan (235,45,25). En el CLI:
  `((volcano_arc, 0.003, 3), (volcano_hot, 0.012, 2))`.

---

## 6. Bucle principal (CLI, `main()`)

```python
for i in range(tiempo):
    u, v = mantle.step(sink)              # sink del paso anterior (None el 1º)
    boundary = crust.step(u, v, mantle.hot)
    sink = upsample(crust.trench, MY, MX) # retroalimentación slab pull
    # cada `cada` pasos: frames.append(render(elevation(), boundary, vol))
```

Flags: `-t` pasos, `-c` cada, `--ms`, `-s` semilla, `-r` resolución,
`-d` detalle, `-o` prefijo, `--sin-gif`. La semilla reinicializa el `rng`
global (¡`main` hace `global rng, NX, NY`!) — mismo comando = mismo mundo.

---

## 7. Invariantes — NO romper al modificar

1. **Damping low-k en `poisson_fft`** (§3.2): sin él la ganancia 1/k²
   diverge en el modo global ⇒ supercontinente único.
2. **F se conserva** (renormalización multiplicativa, §4.9): sin ella los
   continentes desaparecen o crecen sin límite.
3. **Reetiquetar placas cada paso** (§4.1): etiquetas viejas ⇒ líneas de
   convergencia falsas en el borde de ataque ⇒ crestas paralelas.
4. **El océano en el campo de balsas lleva velocidad local, nunca cero**
   (§4.1): un cero es un pozo de velocidad con div≠0 en sus flancos.
5. **Suavizar u_raft/v_raft tras el upsample** (§4.1): la escalera 64→256
   son deltas de divergencia.
6. **Todos los blurs multi-pasada usan shifts crecientes (1,2,3…)**, nunca
   un stride fijo: el kernel con shift s tiene ganancia 1 exacta en las
   longitudes de onda que dividen a s (H(k) = (3+2cos sk)/5, §2.1) — un
   stride fijo es ciego para siempre a su propio peine de paridad.
7. **El umbral de hotspots es un percentil, no un valor absoluto** (§3.6):
   la escala de w varía órdenes de magnitud; el percentil fija la fracción
   de área por construcción.
8. **El halo excluye el núcleo de la fosa en los arcos de islas** (§4.12):
   en el núcleo la subducción (−1.5·conv·C) gana al crecimiento del arco.
9. **La atenuación de `boundary` sobre plumas va antes de normalizar**
   (§4.15): el percentil re-amplifica lo que se atenúe después.
10. **Solo la corteza oceánica subduce** (`where(F < 0.4, …)`, §4.4):
    invertirlo contradice el requisito central del usuario.
11. **La cuenca de antepaís y las fosas viven en el render**, no en `C` — no
    las conviertas en modificaciones permanentes del espesor sin repensar la
    erosión.
12. El transporte es semi-lagrangiano: estable a cualquier velocidad
    (principio del máximo, §3.3) pero difusivo (κ_num ≈ a(1−a)/2) — por eso
    existen el término biestable de F y la gota de `D0`. Si cambias el
    esquema de advección, revisa esos dos compensadores.
13. **El transporte vertical del manto es un no-op** (§3.3): dos líneas que
    se cancelan exactamente. El modelo está calibrado así; arreglarlo exige
    recalibrar `BUOY`, `DECAY`, `PLUME_AMP` y cambia todos los mundos.

---

## 8. Cómo depurar (técnicas que funcionaron)

- **Instrumentar sin tocar el archivo**: `import tecto` en un script del
  scratchpad, correr N pasos e imprimir estadísticas de campos
  (`crust.F.sum()`, `mantle.hot.max()`, percentiles de `boundary`…). Así se
  descubrió que los hotspots nunca disparaban.
- **Perfiles numéricos 1D** a través de una zona con artefactos
  (`C[fila, col0:col1]` impreso): reveló la periodicidad de ~5 px de las
  crestas artificiales cuando ninguna hipótesis visual funcionaba.
- **Descartar el GIF como sospechoso**: renderizar el mismo frame a PNG RGB
  y comparar — si el artefacto está en el PNG, no es la cuantización GIF.
- **Extraer y ampliar frames**: `Image.open('x.gif'); seek(n); crop().resize()`
  para inspeccionar rasgos pequeños (volcanes, islas) frame a frame.
- **Verificar álgebra sospechosa con un caso pequeño**: así se confirmó el
  no-op del transporte vertical (§3.3) — reproducir las líneas exactas sobre
  arrays aleatorios y medir el cambio.
- Regla de diagnóstico: si "no cambia nada" al ajustar un parámetro,
  verifica primero que el mecanismo dispare en absoluto (imprime su max).

## 9. Rendimiento

~25–30 pasos/s a 256² (fue 105 sin mecanismos; cada uno costó algo).
2400 pasos ≈ 88 s. Costos dominantes: las advecciones 256² (6 campos:
C, F, A, Pu, Pv, D — cada una recalcula el mismo backtrace `x − uΔt` y sus
pesos bilineales) y los blurs. El manto (FFTs 48²) es despreciable.
Optimización pendiente más obvia: factorizar el backtrace — calcular índices
y pesos una vez por paso y aplicarlos a los 6 campos (~6× menos trabajo en
la parte dominante).

## 10. Ideas futuras mencionadas y NO implementadas

Del listado del usuario quedaron como posibles extensiones (no pedidas aún):
sedimentación/deltas en costas y desembocaduras, obducción/acreción de
terranos (fragmentos que se sueldan al continente al colisionar), rifts de
tres brazos (aulacógenos), y nivel del mar variable (eustasia). Si se
retoman, respetar los invariantes de §7 — en particular la conservación de
F para la acreción de terranos.
