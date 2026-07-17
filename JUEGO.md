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
| `juego_srv.py`   | **El motor completo, en el servidor**: construcción del mapa jugable, economía, combate, IA, diplomacia, niebla de guerra, victoria/derrota, historia/replay y guardado de partidas. Módulo enchufable de `web.py` con endpoints `/api/juego/*`. |
| `juego.html`     | Solo presentación: canvas (dueños, selección, flechas), zoom/paneo, tooltip, paneles y reproductor de replay. Dibuja el estado visible que manda el servidor. |
| `web.py`         | Ruta `GET /juego` que sirve `juego.html` sin caché, y el sistema de módulos que carga `juego_srv`. |
| `regiones.html`  | Enlace **«🎮 jugar conquista»** en el encabezado, apuntando a `/juego` con el `sello`/`d` del detalle actual. |

Endpoints del motor: `GET /api/juego/mapa` y `/api/juego/estado`;
`POST /api/juego/nueva`, `/orden`, `/turno`, `/diplomacia` y `/borrar`. El
front además carga `_regiones.png` (hit-test del ratón y pintado) y el clima HD
de fondo por el allowlist estático de siempre.

**Antitrampas por diseño:** la niebla de guerra se calcula en el servidor y el
estado que llega al navegador ya viene censurado — las tropas **y la población**
no vistas llegan como `null` y el oro/puntos de los rivales ni siquiera se
envían. El azar de las batallas y los turnos de la IA se resuelven del lado
servidor. Las coropletas de población y militares pintan la niebla en gris.

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
- **Mantener la milicia cuesta oro**: cada tropa del país (guarniciones y
  flotas) descuenta `MANTEN_TROPA = 0.1` de oro por turno del ingreso. El
  ingreso NETO (el que muestra la barra, con desglose en el tooltip) puede ser
  negativo si el ejército es desmedido; el oro nunca baja de 0 (no hay deuda).
  La IA paga el mismo mantenimiento (su multiplicador `eco` solo ayuda al
  ingreso bruto).
- El oro del país es la suma de sus provincias menos el mantenimiento; se
  cobra al terminar el turno.
- **Reclutar** cuesta `3 de oro por tropa` (botones +5 / +25 en la ficha).

### Puntos de acción 🏃 (separados del oro)
- Cada país tiene `min(30, 4 + provincias/2 + población/150000)` puntos por
  turno: cuentan las provincias Y la población disponible (un punto extra por
  cada 150 000 habitantes). Se renuevan al empezar tu turno; la IA juega con
  la misma regla.
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
- **Movimiento parcial (la fatiga es POR TROPA, no por provincia):** cada
  provincia lleva la cuenta de sus tropas **agotadas** (`agotado`; en las
  flotas, `f.a`). Las tropas que **llegan** a una celda (moviéndose,
  conquistando u ocupando) quedan agotadas hasta el próximo turno — así no se
  pueden encadenar movimientos larguísimos en un solo turno, ni por tierra ni
  por mar. Pero las tropas **frescas** de esa misma celda sí pueden seguir
  actuando: una provincia puede dar varias órdenes por turno (cada una paga
  sus 🏃) mientras le quede fuerza fresca por encima de la guarnición, y las
  **recién reclutadas entran frescas** (aunque la provincia ya haya actuado,
  pueden moverse este mismo turno). El slider solo ofrece las frescas; la
  ficha muestra «N libres» / «ya actuó». La IA juega con la misma regla.
- **El mar es transitable:** las tropas pueden moverse a las cuencas marinas
  vecinas como si fueran provincias. El mar libre (sin flota) se **ocupa sin
  batalla**; una flota enemiga en el mar se combate con la lógica normal. En
  el mar no queda guarnición: la flota se mueve entera, y al vaciarse la
  celda vuelve a ser aguas libres. Atacar tierra desde el mar cuenta como
  desembarco (`×0.72`). Si un país es eliminado, sus flotas se dispersan.
- **Mares compartidos (países EN PAZ):** cada cuenca marina guarda una LISTA
  de flotas que coexisten — `prov["flotas"] = [{p, n, m}]` — mientras los
  países estén en paz. Entrar a un mar donde solo hay flotas en paz (o mar
  libre) **no es hostil**: la flota entra y coexiste, sin batalla ni conquista.
  Los campos `dueno`/`ejército` de la celda son la **flota mayoritaria** (para
  el render y las pastillas: se muestra la mayoritaria + un globo con el número
  de flotas). Si dos países que comparten agua **entran en guerra**, sus flotas
  **chocan en el acto** (regla «combate al declarar», no «coexisten hasta que
  uno ataque»: así el combate sigue siendo siempre celda→celda y no hace falta
  un ataque «en la misma celda»). Compatibilidad: las partidas viejas (con un
  único dueño por cuenca) se migran al cargar (`_migrar_mar`) sintetizando su
  lista de una sola flota.
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
- **Vista «diplomacia» + lista unificadas:** al activar la vista se despliega un
  **panel acoplado** (izquierda) con todos los países (provincias, fuerza ⚔,
  estado guerra/pacto/paz respecto a ti). El botón «diplomacia» de la barra es
  ahora sinónimo de activar/desactivar esa vista (ya no abre un overlay aparte).
  La lista se **ordena por estado y tamaño**: primero los países **en guerra**
  contigo, luego los que tienen **pacto de no agresión**, y al final los **en
  paz** — dentro de cada grupo, los más grandes (por provincias) primero; tú
  encabezas la lista. La fuerza ⚔ mostrada es **solo lo visible** y lleva `+?`
  si el país tiene provincias fuera de tu vista. Al hacer **clic/hover** sobre
  un país de la lista (o sobre su territorio en el mapa) su **ficha** muestra el
  estado de ESE país: contra quién está en guerra, con quién tiene tratados de
  no agresión y cuántos turnos quedan, y con quién está en paz. En esta vista el
  clic en el **territorio** inspecciona el país, pero el clic en la **pastilla
  de tropas** selecciona esa región concreta (su ficha de provincia). **No
  existe un sistema de alianzas** en el motor (solo guerra/paz/tratados): la
  ficha lo indica explícitamente.
- **Acciones en la ficha del país** (no en el listado), cuando estás en juego:
  - **🕊 solicitar la paz** (si estás en guerra con él): cuesta `PA_PAZ = 2` 🏃.
    La IA acepta con probabilidad `0.15 + 0.6·(1−agresión)`, `+0.40` si va
    perdiendo (fuerza < la tuya): la pragmática corta pérdidas, la belicosa es
    cabezona. Si acepta, la paz **impone un tratado de no agresión forzoso** de
    1–3 turnos (`_dur_tratado`, más corto cuanto más agresivo el par).
  - **🤝 solicitar tratado de no agresión** (si estáis en paz y sin tratado):
    cuesta `PA_TRATADO = 2` 🏃. La IA acepta con probabilidad `0.25 + 0.6·(1−
    agresión)`; usa la misma duración 1–3 turnos.
  - Los puntos se **cobran aunque la IA rechace** (el esfuerzo diplomático se
    gasta igual; evita spamear ofertas). Los botones muestran el costo y se
    desactivan sin puntos; el resultado (acepta/rechaza) se anota en el log.

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
  de tropas. **Esc** o clic fuera: cancelar la orden. El **clic (y el hover)
  resuelve primero la pastilla de tropas bajo el cursor** y luego el píxel, así
  una pastilla dibujada sobre otra provincia selecciona su provincia y no la de
  debajo.
- **Guardado automático en el servidor:** la partida se persiste tras cada
  acción en `salidas/<sello>/partidas/<stem>.json` (un guardado por detalle).
  Al volver a abrir el juego con el mismo detalle, la pantalla de inicio ofrece
  **«▶ continuar partida guardada»**. El guardado se borra al terminar la
  partida (victoria o derrota).
- **⟲ zoom:** restablecer vista.
- **Terminar turno ▶:** resuelve la IA y avanza el turno.
- Tooltip al pasar el cursor: nombre, país, tropas y población de cada provincia.

## Constantes ajustables (en `juego_srv.py`)

```python
COSTO_TROPA = 3       # oro por tropa reclutada
MANTEN_TROPA = 0.1    # oro por tropa y turno (mantenimiento de la milicia)
PA_POR_POB = 150000   # habitantes por punto de acción extra
BONO_DEFENSA = 1.2    # ventaja del defensor
PENA_NAVAL = 0.72     # penalización al desembarcar
PA_MOV, PA_NAVAL = 1, 2   # puntos de acción por orden
PA_REC, PA_EDIF = 1, 2    # (mover/naval, reclutar, construir)
PA_PAZ, PA_TRATADO = 2, 2 # solicitar paz / tratado (se cobran aunque rechacen)
```

Otros números tocables en el código: dinero inicial de cada país (`dinero: 120`
en la carga), población base por área (`p.area * 25`), guarniciones iniciales,
ingreso por provincia y crecimiento de población por turno (`×1.006`).

## Notas

- El motor corre en el servidor (`juego_srv.py`); el navegador solo presenta.
  El guardado vive en `salidas/<sello>/partidas/<stem>.json`: un slot por
  detalle con dueños, tropas, población, edificios, oro, puntos, guerras,
  turno y dificultad. Si el guardado no encaja con el mapa (ids de provincia
  distintos), se ignora.
- Requiere que el detalle traiga **subregiones**; si no, avisa y no arranca
  (regenera el detalle con provincias).
