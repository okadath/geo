# ARQUITECTURA_C4.md — arquitectura del simulador tectónico en modelo C4

Complemento de [`ALGORITMO.md`](ALGORITMO.md) (la matemática) y del
[`README.md`](README.md) (el uso). Este documento describe el sistema en los
cuatro niveles del modelo C4 — Contexto, Contenedores, Componentes y Código —
y mapea **qué rasgo geológico se produce en qué etapa** del pipeline.
Los diagramas están en sintaxis Mermaid C4 (se renderizan en GitHub).

---

## Nivel 1 — Contexto

Un usuario genera mundos tectónicos animados, desde el navegador o desde la
terminal. El sistema no tiene dependencias externas más allá de numpy+Pillow.

```mermaid
C4Context
    title Nivel 1 — Contexto del sistema

    Person(usuario, "Usuario", "Genera y explora mundos tectónicos reproducibles")

    System(tecto, "Simulador tectónico (geo)", "Convección 3D aproximada → tectónica de placas 2D → GIFs animados (mapa físico + mapa de placas)")

    System_Ext(fs, "Sistema de archivos", "GIF/PNG en salidas/, mundos reanudables en mundos/, presets en semillas.json")

    Rel(usuario, tecto, "Corre simulaciones", "CLI o navegador (127.0.0.1:8000)")
    Rel(tecto, fs, "Escribe/lee", "GIFs, PNG, frames .npz, config.json")
```

---

## Nivel 2 — Contenedores

Dos procesos y tres almacenes. `web.py` nunca simula: solo valida rangos y
lanza el CLI como subproceso.

```mermaid
C4Container
    title Nivel 2 — Contenedores

    Person(usuario, "Usuario")

    Container_Boundary(sys, "Simulador tectónico") {
        Container(web, "web.py", "Python stdlib (http.server)", "UI local con sliders (imagen + algoritmo), progreso, cancelación, mundos guardados. Acota parámetros y llama al CLI")
        Container(cli, "tecto.py", "Python + numpy + Pillow (~520 líneas)", "Toda la simulación y el render. Flags: -t, -s, -r, --velocidad, --mar, --datos, --continuar, --reconstruir…")
        ContainerDb(salidas, "salidas/", "Archivos", "GIFs y PNG por trabajo web")
        ContainerDb(mundos, "mundos/", "Archivos .npz + config.json", "Estado COMPLETO por frame en float64 (incluye RNG y trench) → continuación bit-exacta")
        ContainerDb(semillas, "semillas.json", "JSON", "Presets: semilla + todos los parámetros")
    }

    Rel(usuario, web, "Usa", "HTTP local")
    Rel(usuario, cli, "Usa", "terminal")
    Rel(web, cli, "Lanza como subproceso", "argv validado")
    Rel(web, semillas, "Guarda/carga presets")
    Rel(cli, salidas, "Escribe GIF/PNG")
    Rel(cli, mundos, "Escribe frames / reanuda (--continuar, --desde)")
```

---

## Nivel 3 — Componentes de `tecto.py`

Tres capas acopladas por paso, con una retroalimentación corteza→manto
(slab pull). El bucle de `main()` orquesta:

```mermaid
C4Component
    title Nivel 3 — Componentes de tecto.py

    Container_Boundary(tecto, "tecto.py") {
        Component(main, "main() — bucle temporal", "orquestador", "Por paso: mantle.step(sink) → crust.step(u,v,hot) → sink=upsample(trench). Cada N pasos renderiza un frame")
        Component(mantle, "Mantle — manto 3D", "48×48×8, campo T", "Flotabilidad w∝T−T̄, continuidad por Poisson-FFT (damping low-k), advección semi-lagrangiana, ciclo de vida de plumas, detección de hotspots (percentil 97)")
        Component(crust, "Crust — litosfera 2D", "256², campos C/F/A/Pu/Pv/D", "Placas rígidas + momento + ridge push; orogenia, subducción, rifts, arcos, transformantes, erosión; conservación de F")
        Component(render, "elevation()/render()/render_placas()", "render", "Isostasia + subsidencia + fosa + antepaís + plataforma; tinte hipsométrico, sombreado, bordes rojos, volcanes; mapa tectónico con simbología")
        Component(ops, "Operadores discretos", "numpy vectorizado", "grad/lap periódicos, blurs de shifts crecientes, upsample bilineal, advección semi-lagrangiana, poisson_fft, label_components")
        Component(store, "Almacenamiento de mundos", "npz float64", "Guardar frame, reanudar (restaura RNG), reconstruir GIFs")
    }

    Rel(main, mantle, "u, v, hot ◀", "por paso")
    Rel(main, crust, "▶ u, v, hot", "por paso")
    Rel(crust, mantle, "trench → sink (slab pull)", "retroalimentación")
    Rel(main, render, "C, F, A, boundary, volcanes", "cada `cada` pasos")
    Rel(mantle, ops, "usa")
    Rel(crust, ops, "usa")
    Rel(main, store, "--datos / --continuar")
```

Flujo de datos entre capas (el "diagrama de tubería" de ALGORITMO.md §1):

```
MANTO 3D (48×48×8)          LITOSFERA 2D (256²)              RENDER
Mantle.step(sink) ──u,v──▶  Crust.step(u,v,hot) ──C,F,A──▶  elevation() → render()
        ▲    └──hot──────────────┘      │
        └────────── sink = trench ◀─────┘   (slab pull)
```

---

## Nivel 4 — Código: el pipeline por paso y su geología

El orden dentro de `Crust.step()` **no es arbitrario** (ALGORITMO.md §4).
Cada fila es una etapa del pipeline en su orden real de ejecución; la columna
central dice qué rasgo geológico o proceso tectónico nace ahí.

### Etapa A — Manto (`Mantle.step`)

| # | Etapa (código) | Rasgo geológico / proceso | Ref. |
|---|---|---|---|
| A1 | Flotabilidad `w = BUOY·(T − T̄)` | **Convección del manto** — lo caliente sube, lo frío baja | §3.1 |
| A2 | Continuidad Poisson-FFT con damping low-k | **Celdas de convección → número de placas** (~2.5 celdas por lado); u,v que arrastran las placas | §3.2 |
| A3 | Advección semi-lagrangiana de T + difusión + fondo ruidoso | **Reorganización lenta del patrón convectivo** (deriva de largo plazo) | §3.3 |
| A4 | Ciclo de vida de plumas (nacen cada 70 pasos, derivan, mueren) | **Plumas del manto / superplumas**; su deriva vs. la placa produce cadenas de islas tipo **Hawái** | §3.4 |
| A5 | `T −= SLAB_PULL·sink` bajo las fosas | **Slab pull**: la losa que subduce ancla la corriente descendente y sostiene los cinturones de subducción | §3.5 |
| A6 | Detección de cabezas de pluma (percentil 97 de la columna ascendente) | **Puntos calientes (hotspots)** — el mapa `hot` que alimenta el volcanismo | §3.6 |

### Etapa B — Litosfera (`Crust.step`, en orden de ejecución)

| # | Etapa (código) | Rasgo geológico / proceso | Ref. |
|---|---|---|---|
| B1 | Balsas rígidas (etiquetado de componentes + velocidad media por placa sobre su territorio Voronoi + rotación de Euler ajustada por mínimos cuadrados) | **Rigidez de placa** — las placas se mueven enteras (trasladan Y rotan); hace posibles las **colisiones continentales** | §4.1, §4.2b |
| B2 | Momento `Pu/Pv` (media móvil exponencial, τ=50 pasos) | **Inercia de rumbo de placa** — la deriva sostiene su dirección aunque el manto cambie | §4.2 |
| B2b | Remolque oceánico (media sobre continente + su océano Voronoi), ganancia `DERIVA` e impulso rígido `Qu/Qv` (τ=50 pasos) | **Deriva continental sostenida tipo Wegener** — el fondo oceánico adherido al margen pasivo remolca al continente; un continente en marcha conserva su impulso a través de reorganizaciones del manto y termina su viaje en colisión (fusión = colisión inelástica: los impulsos se promedian por área) | §4.2b |
| B3 | Ridge push `P −= RIDGE_PUSH·∇(e^{−A/AGE_TAU})` | **Empuje de dorsal** — deslizamiento gravitacional desde la dorsal; motor de la deriva post-rift (ciclo de Wilson barato) | §4.3 |
| B4 | Advección de C, F, A, Pu, Pv, D | **Deriva continental** propiamente dicha | §3.3 |
| B5 | Eje de dorsal: cresta de `opening` por supresión de no-máximos (máximo local transversal + compuertas de vigor y de fondo local) | **Dorsales meso-oceánicas continuas** — el eje NO es la pluma (un punto): es el límite divergente entre celdas de convección que UNE las plumas y recorre el océano en grandes tramos | §4.10 |
| B6 | Compuertas de subducción: `subd = max(conv−0.008,0)·madura·lejos`, con `madura = clip(A/AGE_TAU−1)` y `lejos` = lejos del eje de dorsal | **Solo el fondo oceánico viejo (denso) subduce** — el fondo joven es flotante; un margen pasivo (misma placa, tipo Atlántico) no abre fosa | §4.11 |
| B7 | `transform = max(shear − 2.5·|div|, 0)` | **Fallas transformantes** (tipo San Andrés) — solo un valle de falla, sin orogenia ni fosa | §4.6 |
| B8 | `dC/dt = −1.5·subd·C` donde F<0.4 | **Subducción** — solo la corteza oceánica vieja se consume, en límites de placa reales | §4.4 |
| B9 | `dC/dt = +1.8·conv·C` donde F≥0.4 | **Orogenia de colisión** continente-continente (tipo **Himalaya**); el crecimiento multiplicativo focaliza cinturones estrechos | §4.4 |
| B10 | Arco: blur de `subd·[F<0.4]` recortado por F | **Arco de subducción / cordillera costera** (tipo **Andes**), desplazada tierra adentro de la fosa | §4.5 |
| B11 | DoG de la carga orogénica, solo render | **Cuenca de antepaís** (foreland basin) — foso flexural que se inunda como mar interior | §4.7 |
| B12 | Rift `dC/dt = −1.2·opening·(C−C_OCEAN)` + desgarre de F con umbral 0.006 | **Rifting y ruptura continental** (tipo **Rift de África Oriental** → apertura de océano) | §4.8 |
| B13 | Anti-difusión biestable + renormalización de F + piso de flotabilidad | **Flotabilidad continental** — los continentes se parten y deforman pero no desaparecen; costas nítidas | §4.9 |
| B14 | Edad A: envejece advectada, renace SOLO en el eje divergente | **Cuencas abisales viejas** y perfil dorsal→abisal por subsidencia térmica; A alimenta `madura` (B6) y el ridge push (B3) | §4.10 |
| B15 | `trench = subd·[F<0.4]` | **Fosas de subducción** (tipo **Marianas/Perú-Chile**) SOLO en límites de placa con fondo viejo — nunca pegada a la dorsal; también es el `sink` del slab pull | §4.11 |
| B16 | Hotspots sobre océano con techo logístico C≤0.9 | **Islas volcánicas y cadenas de punto caliente** (tipo **Hawái**) | §4.12 |
| B17 | Fosa difuminada × halo (excluye el núcleo) sobre océano | **Arcos de islas** intraoceánicos (tipo **Marianas**) | §4.12 |
| B18 | `volcano_arc`, `volcano_hot` | **Volcanes activos** (puntos rojos: máximos locales de actividad) | §4.12 |
| B19 | Detalle fractal advectado D (τ=10 pasos) | **Rugosidad del terreno / costas irregulares** (solo render) | §4.14 |
| B20 | Erosión asimétrica (picos pierden 35%, valles reciben 100%) | **Erosión con rebote isostático** — por eso las cordilleras viejas persisten (tipo **Apalaches**) | §4.13 |
| B21 | `boundary = (|div|+shear)·(atenuado sobre plumas)` | **Límites de placa** (el trazo rojo del mapa) | §4.15 |

### Etapa C — Render (`elevation` → `render` / `render_placas`)

| # | Etapa (código) | Rasgo geológico / visual | Ref. |
|---|---|---|---|
| C1 | `elev ∝ C − SEA_LEVEL`, cuadrática en tierra | **Isostasia** — llanuras verdes anchas, solo las colisiones llegan a nieve | §5.1 |
| C2 | `elev −= SUBSIDENCE·(1−e^{−A/AGE_TAU})` | **Subsidencia térmica del fondo oceánico** (profundidad ∝ edad) | §4.10 |
| C3 | Halo de F remapeado casi-binario | **Plataforma continental** con talud abrupto; los márgenes activos la pierden bajo la fosa | §5.1 |
| C4 | `elev −= TRENCH·trench`, `elev −= 14·foreland` | Batimetría de **fosa** y **mar interior de antepaís** (solo render, invariante 11) | §5.1 |
| C5 | Tinte hipsométrico + sombreado NW + bordes rojos + volcanes | El **mapa físico** (GIF principal) | §5.2 |
| C6 | `render_placas`: teselación en placas (SLIC sobre velocidad + fusión de vecinas coherentes) con color por placa, dorsal (ámbar), rift (naranja), fosa (violeta), cordilleras (marrón), flechas de deriva | El **mapa tectónico**: el dominio entero se parte en placas (grandes, medianas y micro) desde el campo de velocidad — la simbología sale de los MISMOS campos que la física. La leyenda vive en la web (`web.html`), no en el GIF | §5.3 |

---

## Retroalimentaciones (lo que hace al sistema un ciclo y no una tubería)

1. **Slab pull** (B15 → A5): la fosa enfría el manto bajo ella → refuerza la
   corriente descendente → más convergencia → más fosa. Estabilizado por
   `DECAY` y la difusión.
2. **Ridge push** (B14 → B3): la edad `A` es la única memoria de dónde
   estuvo cada dorsal; su gradiente empuja las placas pendiente abajo,
   amplificado ×50 vía el momento.
3. **Madurez del fondo** (B14 → B6): la misma edad `A` decide qué fondo
   puede subducir — la fosa solo se abre sobre fondo viejo y lejos de la
   dorsal, nunca en el anillo de convergencia de una pluma recién nacida.
4. **Momento** (B2 → B4): la velocidad que advecta la corteza es el manto
   filtrado paso-bajo a 50 pasos, no el instantáneo.

## Invariantes arquitectónicos (resumen; lista completa en ALGORITMO.md §7)

- Damping low-k en `poisson_fft` (sin él: supercontinente único).
- `F` se conserva por renormalización multiplicativa.
- Reetiquetar placas **cada** paso; el océano lleva velocidad local, no cero.
- Blurs siempre con shifts crecientes (1,2,3…), nunca stride fijo.
- Umbrales relativos (percentiles), no absolutos, para hotspots y bordes.
- Fosa y antepaís viven en el render, no en `C`.
- Solo el fondo oceánico VIEJO y lejos de la dorsal subduce (`subd`);
  la fosa es un límite de placas, nunca la sombra de una pluma.
- Estado de reanudación en float64 e incluye `trench` y el estado del RNG.
