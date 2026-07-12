# Juego de conquista (estilo Age of History)

Juego de estrategia por turnos sobre las provincias de **un detalle** ya
generado por `tecto.py`. Reutiliza los mismos datos que la ventana de regiones
(`_capas.json`, `_regiones.png` y el clima HD de fondo), así que no genera nada
nuevo: solo juega encima del mapa que ya existe.

## Cómo abrirlo

1. `python web.py` (servidor local en `http://127.0.0.1:8000`).
2. Genera o carga una corrida, **detalla un cuadro** (necesita subregiones).
3. Abre ese detalle → **regiones** → enlace **«🎮 jugar conquista»** en el
   encabezado.

La URL es `/juego?sello=…&d=<stem del detalle>`, con la misma query que
`/regiones`. Si faltan `sello`/`d` válidos, la página avisa y no intenta cargar.

## Archivos tocados

| Archivo          | Cambio |
|------------------|--------|
| `juego.html`     | **Nuevo.** El juego completo (HTML + CSS + JS en una sola página, sin dependencias externas). |
| `web.py`         | Nueva ruta `GET /juego` que sirve `juego.html` sin caché (igual que `/` y `/regiones`). |
| `regiones.html`  | Enlace **«🎮 jugar conquista»** en el encabezado, apuntando a `/juego` con el `sello`/`d` del detalle actual. |

No se añadieron rutas de datos nuevas: el juego consume los artefactos del
detalle que ya expone el allowlist de `web.py` (`_capas.json`, `_regiones.png`,
`_climahd.png`/`.png`).

## De dónde salen los datos

Del `_capas.json` del detalle:

- **Provincias (tierra):** `subregiones.tierra` — id, nombre, rgb, área, país.
- **Cuencas marinas:** `subregiones.mar` — son provincias **transitables**:
  las tropas pueden ocuparlas y combatir en ellas, pero no tienen población,
  no dan ingreso, no cuentan como provincia (puntos/victoria) y no admiten
  reclutar ni construir. También definen las vecindades navales de los puertos.
- **Países:** `paises.lista` — id, nombre, rgb (son las facciones iniciales).
- **Asentamientos:** `asentamientos` — suman población a su provincia; los de
  rango 3 marcan la provincia como **capital** (★).

El raster `_regiones.png` codifica el id de provincia por píxel en
`R | (G<<8)`, igual que en `regiones.html`; de ahí se sacan **adyacencias**
(tierra-tierra y tierra-mar-tierra), **centroides** (para las pastillas de
tropas) y el mapeo píxel→provincia para el ratón.

**Conectividad garantizada:** tras construir el grafo de adyacencias
(`conectarComponentes`) se detectan con BFS las componentes conexas del grafo
de movimiento; si hay más de una (una isla cuya costa quedó bajo el umbral de
contacto, una cuenca aislada…), se añaden enlaces sintéticos entre el par de
provincias más cercano (distancia entre centroides, envolviendo en x) hasta
que todo el mapa sea una sola componente. Así ninguna provincia queda
inalcanzable/inconquistable. Los enlaces sintéticos son vecinos normales
(cuestan 1 🏃) y, si unen tierra con mar, marcan la tierra como costera.

## Mecánicas

### Economía
- Cada provincia da ingreso `1 + población/45000` por turno.
- El oro del país es la suma de sus provincias; se cobra al terminar el turno.
- **Reclutar** cuesta `3 de oro por tropa` (botones +5 / +25 en la ficha).

### Puntos de acción 🏃 (separados del oro)
- Cada país tiene `min(30, 4 + provincias/2)` puntos por turno; se renuevan al
  empezar tu turno. La IA juega con la misma regla.
- Costos: **mover/atacar** 1 punto (2 si es travesía naval), **reclutar** 1
  punto por orden, **construir** (bastión/torre/puerto) 2 puntos.
- Sin puntos no hay órdenes: los objetivos dejan de resaltarse y los botones se
  desactivan hasta el próximo turno. Así no hay movimientos infinitos.

### Ejércitos y órdenes
- Cada provincia tiene una guarnición de tropas (pastilla numerada en su
  centroide, al estilo AoH; capitales con ★).
- Al seleccionar una provincia **tuya** se dibuja un **abanico de flechas
  semitransparentes** hacia **todos** los destinos posibles de sus tropas
  (verde mover a propia, roja atacar, discontinua si es travesía naval), para
  ver de un vistazo a dónde puede ir el ejército.
- Haz clic en una vecina **resaltada**: se
  abre una **orden pendiente** con una **flecha** opaca origen→destino sobre
  el mapa (verde mover, roja atacar, discontinua si es naval) y un **slider**
  para elegir cuántas tropas enviar (siempre queda al menos 1 de guarnición).
- Confirma (✔ mover / ⚔ atacar) para ejecutar y gastar los puntos, o cancela
  con ✕, `Esc` o clic en el mapa. Atacar a un país en paz **declara la guerra**.
- Tras actuar, la provincia de origen queda marcada como «ya actuó» este turno
  (borde tenue), aunque conserve tropas.
- **El mar es transitable:** las tropas pueden moverse a las cuencas marinas
  vecinas como si fueran provincias. El mar libre (sin flota) se **ocupa sin
  batalla**; una flota enemiga en el mar se combate con la lógica normal. En
  el mar no queda guarnición: la flota se mueve entera, y al vaciarse la
  celda vuelve a ser aguas libres. Atacar tierra desde el mar cuenta como
  desembarco (`×0.72`). Si un país es eliminado, sus flotas se dispersan.
- **Desembarcos navales con puerto:** entre dos costas de la **misma cuenca
  marina** aunque no sean vecinas terrestres, con penalización de fuerza
  (`×0.72`) y costo de 2 🏃 (salto directo, sin cruzar celda a celda).

### Batallas
- Fuerza atacante = `(tropas enviadas) × azar × (naval? 0.72 : 1)`.
- Fuerza defensora = `max(tropas, 0.5) × 1.2 (bono defensa) × azar`.
- `azar ∈ [0.85, 1.15]`.
- Si gana el atacante, conquista con las tropas sobrantes y la provincia
  **pierde ~7% de población** (la guerra despuebla). Si no, el atacante pierde
  sus tropas y el defensor queda mermado.

### Diplomacia
- Panel con todos los países (provincias, fuerza ⚔, estado guerra/paz).
- **Declarar guerra** o **pedir la paz**. La IA acepta la paz según cómo vaya la
  guerra (rechaza si te está ganando claro).

### IA (por país, cada turno)
1. Cobra su ingreso y renueva sus puntos de acción.
2. Pide la paz si va claramente perdiendo una guerra.
3. Declara guerra oportunista a un vecino bastante más débil (con moderación).
4. Recluta en su provincia de frontera más amenazada.
5. Ataca al vecino válido más débil desde cada provincia con tropas.
6. Mueve reservas interiores hacia el frente.

### Fin de partida
- **Victoria 👑** si eliminas a todas las facciones rivales.
- **Derrota 💀** si te quedas sin provincias.
- Un país se elimina al perder su última provincia (rompe sus guerras).

## Controles

- **Rueda del ratón:** zoom (hasta ×24).
- **Arrastrar:** paneo.
- **Clic** en provincia propia: seleccionar; clic en la ya seleccionada:
  deseleccionar; clic en objetivo resaltado: abre la orden con flecha y slider
  de tropas. **Esc** o clic fuera: cancelar la orden.
- **💾 guardar:** guarda la partida en el navegador (`localStorage`, un
  guardado por detalle). Al volver a abrir el juego con el mismo detalle, la
  pantalla de inicio ofrece **«▶ continuar partida guardada»**. El guardado se
  borra al terminar la partida (victoria o derrota).
- **⟲ zoom:** restablecer vista.
- **Terminar turno ▶:** resuelve la IA y avanza el turno.
- Tooltip al pasar el cursor: nombre, país, tropas y población de cada provincia.

## Constantes ajustables (en `juego.html`)

```js
const COSTO_TROPA = 3;      // oro por tropa reclutada
const BONO_DEFENSA = 1.2;   // ventaja del defensor
const PENA_NAVAL = 0.72;    // penalización al desembarcar
const PA_MOV = 1, PA_NAVAL = 2,  // puntos de acción por orden
      PA_REC = 1, PA_EDIF = 2;   // (mover/naval, reclutar, construir)
```

Otros números tocables en el código: dinero inicial de cada país (`dinero: 120`
en la carga), población base por área (`p.area * 25`), guarniciones iniciales,
ingreso por provincia y crecimiento de población por turno (`×1.006`).

## Notas

- Todo corre en el navegador; el servidor solo sirve archivos estáticos y los
  datos del detalle. El guardado es local al navegador (`localStorage`): un
  slot por detalle con dueños, tropas, población, edificios, oro, puntos,
  guerras, turno y dificultad. Si el guardado no encaja con el mapa (ids de
  provincia distintos), se ignora.
- Requiere que el detalle traiga **subregiones**; si no, avisa y no arranca
  (regenera el detalle con provincias).
