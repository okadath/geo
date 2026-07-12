# tecto — simulación geológica ligera

Genera mapas 2D animados (GIF) de tectónica de placas a partir de una
simulación 3D **aproximada** de convección del manto. Sin mecánica de fluidos
real: solo flotabilidad, conservación de masa vía FFT y advección. Corre a
~80 pasos/s en un hilo de CPU.

![ejemplo](tectonica.gif)

Cada corrida produce además un **mapa tectónico animado**
(`NOMBRE_placas.gif`): límites de placa clasificados por tipo con los mismos
campos que usa la física — dorsales (ámbar, el eje divergente que fabrica
corteza), rifts continentales (naranja), fosas de subducción (violeta) —
más cadenas montañosas (marrón), flechas con la dirección de deriva de cada
placa y leyenda.

![placas](tectonica_placas.gif)

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

Diales del algoritmo (sobrescriben las constantes de `tecto.py`):

| Opción | Default | Efecto |
|---|---|---|
| `--velocidad V` | 18.0 | velocidad de la deriva continental (px/paso) |
| `--mar H` | 0.52 | nivel del mar (más alto = más océano) |
| `--continentes U` | 0.55 | umbral continental inicial (menor = más tierra) |
| `--plumas N` | 70 | pasos entre nacimientos de plumas (menor = manto más activo) |
| `--erosion E` | 0.008 | desgaste del relieve |
| `--empuje R` | 0.15 | empuje de dorsal (motor de la deriva post-rift) |
| `--momento M` | 0.02 | relajación del rumbo por paso (menor = colisiones más decididas) |
| `--rigidez G` | 0.85 | rigidez de placa: 0 = fluido, 1 = balsa rígida |

## Mundos guardados (datos por frame)

```bash
python3 tecto.py -t 800 --datos              # guarda mundos/<nombre>/
python3 tecto.py --reconstruir mundos/NOMBRE # re-renderiza ambos GIFs desde los datos
python3 tecto.py --continuar mundos/NOMBRE -t 500          # +500 pasos desde el final
python3 tecto.py --continuar mundos/NOMBRE --desde 400 -t 500  # reescribe desde el paso 400
```

Con `--datos`, cada corrida crea una carpeta `mundos/<salida>_s<semilla>_<fecha>/`
que identifica al mundo y contiene:

```
config.json     todos los parámetros (imagen + algoritmo) e historial de continuaciones
base.npz        textura de detalle y total continental
mapa.gif        el mapa animado          placas.gif   el mapa tectónico animado
mapa_final.png  el último frame
frames/000000.npz, 000008.npz, …   estado COMPLETO de la simulación por frame
```

Cada `frames/PASO.npz` guarda el estado íntegro (corteza, manto, plumas,
momento, edad, estado del RNG), así que **cualquier frame** sirve para
re-renderizar o para retomar la simulación desde ahí. La continuación es
**bit-exacta**: continuar un mundo produce exactamente el mismo futuro que
haberlo corrido de un tirón. `--desde` descarta los frames posteriores al
punto elegido (la historia se reescribe desde ahí). Tamaño: ~2–3 MB por
frame a 256² (contrólalo con `-c`).

Duración del GIF ≈ `(tiempo / cada) × ms / 1000` segundos.
Ej.: `-t 2400 -c 8 --ms 60` → 300 frames ≈ 18 s.

## Interfaz web

```bash
python3 web.py            # abre http://127.0.0.1:8000
python3 web.py -p 9000    # otro puerto
```

Página local (solo biblioteca estándar, sin dependencias extra) que llama al
CLI para generar GIFs desde el navegador:

- **Sliders** para los parámetros importantes: tiempo, frame cada N pasos,
  ms por frame, resolución y detalle, con estimación en vivo de la duración
  del GIF y del tiempo de cómputo.
- **Sliders del algoritmo**: velocidad de deriva, nivel del mar, umbral
  continental, ritmo de plumas, erosión, empuje de dorsal, momento y rigidez
  de placa (los flags `--velocidad`, `--mar`, … del CLI).
- **Botón Cancelar** para abortar una simulación en curso, y botón
  **⟲ Valores por defecto** que restablece todos los sliders (imagen y
  tectónica; la semilla se conserva).
- Muestra **ambos GIFs**: el mapa y el mapa tectónico de placas.
- **Semilla** editable con botón 🎲 de semilla aleatoria; misma semilla +
  mismos parámetros reproducen el mundo byte a byte.
- **Mundos guardados**: guarda la semilla junto con todos los parámetros
  bajo un nombre (persisten en `semillas.json`) y cárgalos después para
  repetir la simulación exacta.
- Barra de progreso durante la simulación; al terminar muestra el GIF con
  enlaces de descarga (GIF y PNG final). Los resultados quedan en
  `salidas/` (fuera de git, igual que `semillas.json`).

El servidor escucha solo en `127.0.0.1` y acota todos los parámetros a
rangos seguros antes de invocar el CLI.

## Cómo funciona

Tres capas, cada una una aproximación deliberadamente barata:

### 1. Manto 3D (48×48×8 celdas; esférico: longitud periódica, polos sin envolver)

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
  paso y renace **solo en el eje de la dorsal** (el núcleo intenso de la
  divergencia — la dorsal es el límite de placa que fabrica corteza; su
  equivalente sobre continente es el rift que lo parte). El fondo joven
  queda somero y el viejo se hunde (`SUBSIDENCE`, `AGE_TAU`) →
  **cordilleras submarinas** a lo largo de las dorsales y cuencas abisales
  viejas lejos de ellas.
- **Fosas de subducción** (`TRENCH`): depresión batimétrica donde converge
  flujo sobre corteza oceánica, el rasgo oscuro que bordea los márgenes
  activos.
- **Plataforma continental**: el margen sumergido del continente forma un
  mar somero turquesa que bordea las costas, plano y con talud abrupto al
  abisal. Los márgenes activos la pierden bajo la fosa (como en los Andes);
  los mares interiores comparten la misma banda somera.
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

## Capa climática

Un cuarto mapa (`clima.gif`, y `clima_*.png` en el reproductor) que se calcula
**a partir de la geografía de cada cuadro** en `clima.py`: temperatura del aire,
vientos (alisios/westerlies), corrientes marinas, lluvia con sombra orográfica,
glaciares y banquisa, ríos con lagos y estuarios, y **biomas** (selva, sabana,
desierto, estepa, pradera, bosque templado, taiga, tundra, hielo).

Es una capa de **snapshots, no retroactiva**: el clima es una función pura de la
elevación del frame, no retroalimenta la tectónica, no se guarda en los `.npz`
(se recalcula al reconstruir/extrapolar) y **no consume el generador aleatorio**
de la simulación, así que la continuación de un mundo sigue siendo bit-exacta.

Dos diales globales (grupo *algoritmo* del CLI, también en la web):

- `--temperatura` (−1 … 0 … +1): de bola de nieve a templado (Tierra) a
  invernadero; desplaza toda la curva térmica del planeta.
- `--precipitaciones` (0.2 … 1 … 2): de árido a normal a muy húmedo; escala el
  nivel de lluvia final, la densidad de la red fluvial y la extensión de selva
  (`--humedad` se acepta como alias del nombre viejo).

## Capa de civilización

Al **detallar un cuadro** (`tecto.py --detallar`, o el botón *Detallar* de la
web) se genera además, en `civ.py`, una capa de civilización derivada de los
mismos campos que el clima HD —el mapa de **Köppen** y las **cuencas y ríos** de
la hidrología fina— y **no** de los colores del render:

- **Asentamientos humanos**: máximos de un campo de *habitabilidad* (clima
  Köppen + acceso a agua dulce y costa − altitud y pendiente) sembrados con
  separación mínima. Cada uno trae nombre, rango (aldea / pueblo / ciudad /
  capital), población orientativa y si es costero o ribereño.
- **Caminos**: red terrestre de mínimo coste entre asentamientos (árbol de
  expansión mínima sobre un campo de coste del terreno, más un anillo de
  redundancia); rodean montañas y siguen los valles.
- **Rutas comerciales**: troncales de largo alcance entre las capitales,
  **terrestres** y **marítimas** (estas saltan de un continente a otro por el
  mar, hugging la costa).
- **Países**: reparto del suelo entre las capitales por Dijkstra multi-fuente
  sobre un coste donde **montañas y ríos son barreras**, así que las fronteras
  caen solas sobre divisorias y cauces —no siguen a Köppen, sí a la geografía
  del agua, como pidió el diseño.

Todo es **determinista y pasivo** igual que el clima: la semilla se deriva de la
propia elevación (no toca el generador aleatorio de la simulación, la
continuación de un mundo sigue siendo bit-exacta) y se calcula sobre una malla
reducida para que el A*/Dijkstra en Python sea barato.

**Formato legible y evaluable.** La información de la ampliación queda guardada
por cuadro detallado en `{nombre}_capas.json` (más los rásters `{nombre}_datos.png`
—tair/precip/altitud— y `{nombre}_datos2.png` —bioma/Köppen/hielo— para el
inspector, y el overlay `{nombre}_paises.png`). El JSON reúne, en coordenadas de
píxel del render, las capas ya existentes (Köppen, cuencas, ríos, vientos,
corrientes, isoyetas) y las nuevas:

```jsonc
{
  "asentamientos": [{"x","y","nombre","rango","poblacion","costa","rio","pais"}],
  "caminos":       [{"puntos":[[x,y],…], "clase"}],
  "rutas":         [{"puntos":[[x,y],…], "mar", "a", "b"}],
  "paises": {"png":"…_paises.png",
             "lista":[{"id","nombre","rgb","area"}]}
}
```

El visor de clima HD de la web añade dos casillas combinables —**países** y
**asentamientos, caminos y rutas**— con leyenda de países y *tooltip* del
asentamiento bajo el cursor (nombre, rango, población y país). En los detalles
con civilización ambas capas arrancan encendidas.

**Diales de civilización.** El CLI (`--semilla-civ`, `--asentamientos`,
`--paises`; 0 = automático) y la sección **«Detallar con civilización»** de la
web (que reusa los diales geográficos de «Detallar cuadro» y añade semilla de
civilización, nº de asentamientos y nº de países) controlan el poblamiento:
la semilla de civilización se mezcla con la derivada de la geografía, así que
cambiarla da otros asentamientos, nombres y países sobre el mismo mapa.
Además del JSON se rinde `{nombre}_civ.png`: el **mapa político** ya compuesto
(clima HD + tinte de países + caminos, rutas y asentamientos rotulados), que el
visor enlaza como «mapa político».

## Páginas interactivas sobre un detalle

Cada cuadro detallado **con civilización** habilita cuatro páginas más del
servidor local, con la misma query `?sello=…&d=<stem>`. La lógica propietaria
(motor del juego, renders de fantasía y battlemaps) corre **en el servidor**,
en módulos enchufables que `web.py` carga al arrancar (`juego_srv.py`,
`fantasia_srv.py`, `batalla_srv.py`, endpoints `/api/...`); los HTML son solo
presentación:

- **`/regiones`** — visor de **subregiones**: provincias de cada país y
  regiones marinas, con selección múltiple, fichas, tooltips y árbol por país.
  Doc: [`SUBREGIONES.md`](SUBREGIONES.md).
- **`/juego`** — **juego de conquista por turnos** (estilo Age of History)
  sobre esas provincias: economía, ejércitos, mar transitable, desembarcos,
  diplomacia e IA. Doc: [`JUEGO.md`](JUEGO.md).
- **`/fantasia`** — **mapa de fantasía**: redibujado estilo pergamino (glifos
  de montaña, waterlines, rótulos caligráficos) con niveles de calidad,
  re-render nítido por sector al hacer zoom y export de PNG completo o del
  sector visible. Doc: [`FANTASIA.md`](FANTASIA.md).
- **`/batalla`** — **battlemaps de encuentro**: elige un punto del mundo y
  genera un mapa táctico con rejilla coherente con ese lugar (14 temas con
  subtipos, título narrativo, export PNG para VTT/impresión).
  Doc: [`BATALLA.md`](BATALLA.md).

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

[`DETALLE_HD.md`](DETALLE_HD.md) documenta la capa de clima del cuadro
**ampliado** (`clima.py` + `tecto.py::detallar`): corrientes reutilizadas del
mapa pequeño y re-escaladas al detalle, el dial de **sinuosidad** (meandros) y
los **lagos extendidos / cuencas endorreicas** de la hidrología fina, con su
matemática, sus diales y las trampas ya resueltas.

Además: [`SUBREGIONES.md`](SUBREGIONES.md) (provincias y cuencas marinas +
página `/regiones`), [`JUEGO.md`](JUEGO.md) (juego de conquista `/juego`),
[`FANTASIA.md`](FANTASIA.md) (mapa de fantasía `/fantasia`),
[`BATALLA.md`](BATALLA.md) (battlemaps `/batalla`),
[`ARQUITECTURA_C4.md`](ARQUITECTURA_C4.md) (vistas C4 del sistema) y
[`NEGOCIO.md`](NEGOCIO.md) (posibles líneas de producto).
