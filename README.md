# tecto — simulación geológica ligera

Genera mapas 2D animados (GIF) de tectónica de placas a partir de una
simulación 3D **aproximada** de convección del manto. Sin mecánica de fluidos
real: solo flotabilidad, conservación de masa vía FFT y advección. Corre a
~80 pasos/s en un hilo de CPU.

![ejemplo](tectonica.gif)

## Requisitos

- Python 3.8+
- `numpy` y `Pillow` (`pip install numpy pillow`)

## Uso

```bash
python3 tecto.py                      # 800 pasos, tectonica.gif + tectonica_final.png
python3 tecto.py -t 2400              # simulación más larga → GIF más largo
python3 tecto.py -t 1000 -s 42        # otro mundo (otra semilla)
python3 tecto.py --sin-gif -t 500     # solo el PNG del mapa final
python3 tecto.py -r 512 -o mundo      # mapa 512×512 → mundo.gif, mundo_final.png
python3 tecto.py --help               # todas las opciones
```

| Opción | Default | Efecto |
|---|---|---|
| `-t, --tiempo PASOS` | 800 | pasos de simulación; más pasos = más deriva y GIF más largo |
| `-c, --cada N` | 8 | guarda un frame cada N pasos (menor = animación más suave y pesada) |
| `--ms MS` | 60 | milisegundos por frame del GIF (mayor = reproducción más lenta) |
| `-s, --semilla N` | 7 | semilla aleatoria; cada semilla es un mundo distinto y reproducible |
| `-r, --resolucion PX` | 256 | lado del mapa en píxeles (el costo crece ~cuadrático) |
| `-d, --detalle X` | 0.6 | rugosidad fractal del render, 0=liso .. ~1.5=abrupto; **no** cambia el costo de simulación |
| `-o, --salida NOMBRE` | tectonica | prefijo de los archivos de salida |
| `--sin-gif` | — | omite el GIF, solo guarda `NOMBRE_final.png` |

Duración del GIF ≈ `(tiempo / cada) × ms / 1000` segundos.
Ej.: `-t 2400 -c 8 --ms 60` → 300 frames ≈ 18 s.

## Cómo funciona

Tres capas, cada una una aproximación deliberadamente barata:

### 1. Manto 3D (48×48×8 celdas, toroidal)

La convección se reduce a tres reglas por paso, sin Navier-Stokes ni presión:

- **Flotabilidad**: la velocidad vertical de cada celda es proporcional a su
  anomalía térmica respecto a la media de su capa (`w ∝ T − T̄`). Lo caliente
  sube, lo frío baja.
- **Continuidad**: la divergencia horizontal de cada capa es `−∂w/∂z`; el
  flujo horizontal sale de resolver un Poisson 2D por capa vía FFT. Los modos
  de escala más grande se amortiguan (parámetro `k0` en `poisson_fft`) porque
  sin eso el `1/k²` hace dominar una sola celda de convección global y todos
  los continentes colapsan en un supercontinente.
- **Transporte**: advección semi-lagrangiana de la temperatura + difusión.
  El fondo se mantiene caliente con ruido, lo que hace migrar las plumas y
  reorganiza las placas con el tiempo.
- **Ciclo de vida de plumas**: cada `PLUME_EVERY` pasos nace una pluma nueva
  en un sitio aleatorio del fondo, con deriva propia lenta y vida finita
  (250–600 pasos, con fundido de entrada/salida); las anomalías decaen hacia
  el perfil conductivo (`DECAY`), así que las plumas viejas mueren. La deriva
  hace que un punto caliente bajo el mar deje cadenas de islas lineales.
- **Arrastre de losa** (`SLAB_PULL`): donde la corteza subduce, el manto
  superior se enfría — la corriente descendente queda anclada bajo las fosas,
  como en la Tierra.

### 2. Litosfera 2D (mapa de `resolucion`²)

La velocidad de la capa superior del manto se interpola al mapa y advecta dos
campos: el **espesor de corteza** `C` y la **fracción continental** `F`
(conservada — sin ella la subducción se come los continentes):

- Divergencia (`∇·u > 0`) → **rift**: corteza oceánica nueva y delgada.
- Convergencia sobre océano (`F` bajo) → **subducción**: la corteza se consume.
- **Empuje de dorsal** (`RIDGE_PUSH`): la corteza recién creada en una dorsal
  queda elevada, y las placas se deslizan pendiente abajo alejándose de ella.
  Cuando una pluma abre un rift en medio de un océano o un continente, este
  empuje conduce las placas hasta colisionar en el lado opuesto — donde se
  levanta una cordillera (continente-continente) o una fosa con su cordillera
  costera (océano-continente).
- **Memoria de rumbo** (`MOMENTUM`): la velocidad de cada placa no es la del
  manto instantáneo sino un campo de momento que viaja advectado con la placa
  y se relaja hacia el manto solo un 2% por paso — el análogo barato del
  *slab pull*. Sin esto cada pluma nueva desvía a los continentes antes de
  que alcancen a cruzar el océano, y las colisiones nunca se completan.
- **Rigidez de placa** (`RIGID`): cada continente se etiqueta como componente
  conexa (en una malla reducida `LGRID`², puro numpy) y se mueve como balsa
  rígida con la velocidad media del manto bajo él. Sin esto el campo de
  velocidad tiene un punto de estancamiento en la línea de convergencia, los
  continentes frenan exponencialmente y los mares nunca terminan de cerrarse
  — con rigidez las colisiones sí ocurren. Un rift activo "ablanda" la placa
  localmente para que las plumas aún puedan desgarrarla.
- Convergencia sobre continente (`F` alto) → **orogenia**: `C` se apila y
  levanta cordilleras (marrón/nieve) a lo largo de la sutura de colisión.
- Subducción bajo un margen continental → **arco de subducción**: la placa
  oceánica que se hunde levanta una cordillera costera en la placa que
  cabalga (tipo Andes), paralela a la fosa.
- Rift sostenido sobre continente → **desgarramiento**: la pluma que sube
  debajo lo parte en fragmentos que derivan por separado (la cohesión
  biestable de `F` se apaga localmente donde el rift está activo).
- **Flotabilidad continental**: `C` nunca baja del piso que marca `F`; los
  continentes se deforman y derivan pero no desaparecen. El total de `F` se
  conserva (un rift parte un continente, no lo borra) y un término biestable
  mantiene las costas nítidas frente a la difusión numérica.
- **Edad del fondo oceánico** (`A`): se advecta con la placa, envejece paso a
  paso y renace a cero en los rifts. El fondo joven queda somero y el viejo
  se hunde (`SUBSIDENCE`, `AGE_TAU`) → **cordilleras submarinas** visibles a
  lo largo de las dorsales.
- **Fosas de subducción** (`TRENCH`): depresión batimétrica donde converge
  flujo sobre corteza oceánica, el rasgo oscuro que bordea los márgenes
  activos.
- **Fallas transformantes**: cizalla alta con divergencia baja = las placas
  solo se rozan; no hay orogenia ni fosa, apenas un valle de falla sutil.
- **Cuencas de antepaís**: la corteza se flexiona hacia abajo frente al
  orógeno en crecimiento (carga difuminada menos el núcleo); si la depresión
  baja del nivel del mar se inunda como mar interior.
- **Erosión con rebote isostático**: al erosionarse una cordillera la raíz
  cortical empuja de vuelta, así que solo ~35% de lo erosionado se pierde en
  las cimas (por eso los Apalaches persisten). Reducida además sobre corteza
  continental — el relieve interior resiste; la corteza continental no se
  hunde ni subduce, solo la oceánica.
- **Volcanismo**: las cabezas de pluma se detectan como el 3% más vigoroso de
  la columna ascendente del manto medio (umbral auto-escalado). Un punto
  caliente bajo el mar construye una isla volcánica (y la placa que deriva
  encima deja una cadena, tipo Hawái); la subducción intraoceánica levanta
  arcos de islas junto a su fosa (tipo Marianas). Los volcanes activos se
  pintan como puntos rojos: máximos locales de actividad en arcos de
  subducción y puntos calientes.
- **Detalle fractal advectado** (`--detalle`): una textura de ruido
  multi-octava viaja pegada a las placas y se suma a la elevación **solo en
  el render** — costas irregulares y relieve fino en montaña sin ningún
  costo de simulación extra (una gota de la textura original por paso
  compensa la difusión numérica).

### 3. Render

Elevación por isostasia trivial (`elev ∝ C − nivel_del_mar`), tinte
hipsométrico (abisal → costa → verde → marrón → nieve), sombreado por
pendiente, y bordes de placa en rojo donde `|divergencia| + |cizalla|` supera
el percentil 98.

## Diales interesantes (constantes al inicio de `tecto.py`)

- `k0` en `poisson_fft` — número de celdas de convección ⇒ número de placas.
- Umbral `0.55` del ruido inicial en `Crust.__init__` — fracción de continente.
- `VEL_SCALE` — velocidad de la deriva continental.
- `SEA_LEVEL` — nivel del mar (más alto = más océano).
- `MX/MY/MZ` — resolución del manto; bajarla acelera casi sin cambio visual.

El estado completo son ~25k floats del manto + 2 mapas 2D: el esquema es
portable tal cual a un shader o a un motor de juego.

## Documentación técnica

[`ALGORITMO.md`](ALGORITMO.md) documenta cada componente geológico en
detalle: por qué se agregó, sus variables, su comportamiento, las trampas ya
resueltas (invariantes que no hay que romper) y las técnicas de depuración
que funcionaron. Es el punto de entrada para retomar o extender el proyecto
(por una IA o un desarrollador) sin el historial original.
