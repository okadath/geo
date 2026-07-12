# Viabilidad del juego como negocio

**Resumen:** es viable como micronegocio de un solo desarrollador, pero solo en
la versión **monojugador** (con multijugador asíncrono opcional después). El
multijugador en tiempo real no se justifica ni por costos ni por el diseño (es
un juego por turnos). Y vender mapas como producto separado es la parte más
débil del plan — tu generador procedural vale más como *feature* diferenciadora
que como DLC.

---

## 1. El mercado

Tu comparable directo es exactamente el juego que estás emulando, y es a la vez
la mejor y la peor noticia:

- **Age of History II** (un solo desarrollador, Łukasz Jakowski): ~$11.1M brutos
  estimados y entre 1 y 2 millones de copias en Steam. **Age of History 3**
  (oct 2024) lleva ~17,000 reseñas con 85% positivas — con el ratio típico de
  40–70 ventas por reseña del género, eso sugiere del orden de **700k–1M de
  copias**.
- El problema: eso es el *outlier*, no la mediana. En 2025 salieron ~19,000
  juegos en Steam; la **mediana de ingresos de un lanzamiento nuevo fue $249** y
  el 66% ganó menos de $1,000. La mediana histórica de un indie "real" (no
  shovelware) está en **$5,000–15,000 brutos de por vida** (~$3,500–10,500 netos
  tras el 30% de Steam).
- A favor tuyo: estrategia es de los nichos con mejor mediana y menor costo de
  producción, con ratios reseña-venta favorables (60–80x), y los juegos con
  publisher ganan ~5x la mediana de los autopublicados ($16k vs $3.3k).

**Tu diferenciador real no es "otro AoH-like"** — es que AoH juega siempre sobre
el mismo mapa de la Tierra, y tú generas **planetas enteros con tectónica, clima
e hidrología coherentes**, cada semilla un mundo distinto. Eso es un pitch de
marketing genuino ("conquista un planeta que nunca ha existido") que casi nadie
en el nicho tiene.

## 2. ¿Vender mapas como extra?

Es la pata floja, por una contradicción interna: tu propio generador hace que
los mapas sean infinitos y baratos de producir, así que el comprador percibe
poco valor en pagar por uno. Funciona mejor invertido:

- **Mapas gratis como marketing** — compartir semillas/mundos ("juega el mundo
  #4217") es viral y gratis de producir.
- **El generador como contenido premium**: la versión gratis juega en mundos
  precocinados; la de pago genera mundos propios, con los diales de `tecto.py`
  expuestos. Eso sí es vendible.
- Mapas "curados" a mano (escenarios con lore, países balanceados) podrían ser
  DLC de $2–3, pero es ingreso marginal, no el negocio.

## 3. Monojugador en línea vs multijugador

| | Monojugador (navegador/Steam) | Multijugador asíncrono | Multijugador tiempo real |
|---|---|---|---|
| Costo de servidor | ~$0 (estático) o $5–10/mes | $20–50/mes hasta miles de jugadores | $100–1,000+/mes, escala con jugadores |
| Trabajo extra | Poco (ya funciona así) | Cuentas, persistencia, notificaciones, **mover toda la lógica al servidor** | Todo lo anterior + netcode, salas, latencia |
| Riesgos | Ninguno nuevo | Trampas (hoy TODO corre en el cliente), moderación | Los mismos, amplificados; necesita masa crítica de jugadores simultáneos |

El punto crítico técnico: hoy `juego.html` corre 100% en el navegador con
guardado en `localStorage`. Para cualquier multijugador honesto hay que
**reescribir la resolución de turnos en el servidor** (validar órdenes, tirar el
azar de las batallas allí) — no es "agregar un socket", es rehacer la
arquitectura. Para un juego por turnos, el asíncrono estilo "juega tu turno
cuando quieras" es la única variante multijugador sensata, y aun así es un
proyecto de 2–4 meses adicionales.

El otro riesgo del multijugador: un juego por turnos multijugador **muere sin
masa crítica**. Si lanzas con MP y hay 30 jugadores activos, la experiencia es
peor que no tenerlo. El monojugador no tiene ese riesgo — la IA ya existe.

## 4. Gastos (escenario: tú solo, monojugador primero)

| Concepto | Costo |
|---|---|
| Steam Direct (cuota por juego) | $100 USD (recuperables tras $1,000 en ventas) |
| Hosting de la demo web | $0–10/mes (Cloudflare Pages/itch.io son gratis) |
| Arte/UI (cápsula de Steam, trailer, pulido visual) | $500–2,000 si lo encargas; el arte de tienda importa muchísimo |
| Música/SFX | $0–500 (hay packs con licencia) |
| Localización EN/ES (mínimo inglés) | $0 si lo haces tú |
| Empaquetado escritorio (Tauri/Electron sobre tu HTML) | $0, ~2–4 semanas de trabajo |
| Marketing | $0 en dinero, mucho en tiempo (devlogs, Reddit r/AgeofCivilizations y r/4Xgaming, TikTok de mapas generándose) |
| **Total en efectivo** | **~$600–2,600** |
| **Costo real** | **6–12 meses de tu tiempo** para pasar de prototipo a producto (más IA, balance, tutorial, rendimiento, guardados robustos) |

Si luego agregas multijugador asíncrono: +$20–50/mes de servidor, más el costo
de desarrollo ya mencionado. El dinero nunca es el problema; el tiempo sí.

## 5. Escenarios de ingreso (precio tipo $5–10, como AoH)

- **Pesimista (el más probable estadísticamente):** <$1,000 de por vida. Es el
  destino del 66% de los lanzamientos, casi siempre por lanzar sin wishlists.
- **Base (ejecutas bien el nicho):** $5,000–15,000 brutos. Ganas experiencia y
  una base para el siguiente juego, no un salario.
- **Bueno (el generador procedural conecta, 1,000+ wishlists al lanzar, algo de
  prensa/YouTube):** $30,000–100,000. Alcanzable en este nicho precisamente
  porque estrategia tiene compradores fieles y poca oferta con generación
  planetaria real.
- **AoH-tier:** millones. Existe, pero AoH2 tardó años y se apoyó fuerte en
  móvil — no lo pongas en el plan de negocio.

## 6. Recomendación

1. **Monojugador primero, multijugador nunca-hasta-tener-tracción.** El asíncrono
   solo si la versión SP demuestra demanda.
2. **La demo web gratis es tu mejor arma de marketing** — ya la tienes casi
   lista. Úsala en itch.io para juntar wishlists de Steam (el patrón itch→Steam
   está bien documentado).
3. **Vende el juego, regala los mapas.** El generador es el gancho; los mundos
   compartibles por semilla son el motor viral; el "mapa como DLC" déjalo para
   escenarios curados opcionales.
4. La página "Coming Soon" de Steam se abre **meses antes** del lanzamiento —
   los wishlists son el predictor número uno de ingresos.

---

## 7. El otro mercado: mapas para rol y escritores

Sí es un nicho real, y más sano que el de videojuegos en un aspecto: es un
mercado de **suscripción recurrente**, no de venta única. Un Dungeon Master
necesita mapas nuevos cada semana.

### Los números del nicho

- **Czepeku** (battlemaps para D&D/Pathfinder): ~$80,000/mes en Patreon, más de
  16,000 suscriptores de pago. **Beneos Battlemaps** dejó su trabajo de tiempo
  completo en un año.
- Modelo estándar: Patreon por niveles ($5/mes = mapa del mes + variantes,
  $10 = packs exclusivos) + venta suelta en DriveThruRPG.
- Herramientas para escritores/worldbuilders: **Inkarnate** (suscripción),
  **Wonderdraft** ($29.99 pago único).

### El problema: el generador produce el tipo de mapa *equivocado*

Ese mercado compra dos cosas, y hoy no producimos ninguna:

1. **Battlemaps** (lo que mueve el dinero de Czepeku): escenas de encuentro
   20×20 con arte bonito — una taberna, una cripta. Nuestro generador hace
   planetas enteros; es la escala opuesta.
2. **Mapas de región/mundo de fantasía**: la escala sí coincide, pero el
   mercado quiere mapas *estilizados* (pergamino, montañas dibujadas a mano,
   tipografía élfica). Nuestra salida es un mapa **científico** — se ve como
   atlas geográfico, no como el mapa de El Señor de los Anillos.

**La ironía:** la mayor virtud técnica (coherencia geológica real) es justo lo
que a este mercado le importa menos.

El competidor a estudiar es **Azgaar's Fantasy Map Generator**: gratis, open
source, generación procedural de mundos con clima/ríos/biomas para escritores y
DMs. Su autor no vende mapas — monetiza con Patreon a $5/mes por mantener la
herramienta. Eso marca el techo y el camino.

### Dónde sí hay negocio con el generador

1. **Vender la herramienta, no los mapas** (modelo Wonderdraft/Inkarnate):
   $20–30 pago único o $5/mes por usar el generador — control de semilla,
   diales de `tecto.py`, exportación en alta resolución, licencia comercial.
   Mismo principio que en el videojuego: **el generador es el producto premium,
   el mapa es gratis.**
2. **Cerrar la brecha de estilo:** una capa de render "fantasía" (pergamino,
   montañas estampadas, nombres y etiquetas generados) encima de la geología
   real. Con eso se compite de frente con Azgaar/Inkarnate con una ventaja que
   ellos no tienen: los ríos corren cuesta abajo de verdad y los desiertos
   están donde la física los pone.
3. **Exportar a lo que ellos ya usan:** heightmap en escala de grises + máscara
   de biomas + ríos como PNG. La gente lo mete a Unreal, Azgaar y VTTs; el
   generador se vuelve *fuente de mundos* para todo ese ecosistema.
4. **Patreon de mundos curados** (como Czepeku pero a escala planetaria):
   $5/mes = 3–4 mundos nuevos al mes ya "vestidos" en estilo fantasía, con mapa
   político, lore semilla y archivos para VTT. Solo funciona si primero se
   resuelve el punto 2.

### Conclusión

El negocio del generador **no es vender el archivo de mapa** — ese mercado ya
lo tiene gratis (Azgaar) o quiere arte estilizado que no producimos. El negocio
es vender el generador como herramienta, y el requisito de entrada al mercado
creativo es la capa de render fantasía.

La jugada más realista: un solo motor (`tecto.py` + clima + hidrología) que
alimente **dos productos** — el juego de conquista (Steam) y la herramienta de
worldbuilding (web/Patreon) — compartiendo ~80% del código. No elegir entre
juego y generador: el generador es el núcleo común que paga dos veces.

---

## 8. Plan de precios concreto (estado actual: ya con `/fantasia` y `/batalla`)

> **Actualización.** Las secciones 1–7 se escribieron cuando las dos barreras
> de entrada al mercado creativo eran (1) no tener render estilo fantasía y
> (2) no tener battlemaps. **Ambas ya existen** (`/fantasia` y `/batalla`).
> Esto adelanta el producto vendible de "el juego" a "la herramienta creativa",
> que hoy está lista antes.

### 8.1 Qué sección vender

| Sección | ¿Vendible hoy? | Por qué |
|---|---|---|
| `/batalla` | **Sí, la primera** | Es el nicho con el dinero (Czepeku ~$80k/mes). Un DM necesita mapas nuevos cada semana; el generador los hace infinitos y coherentes con un mundo. |
| `/fantasia` | **Sí, como complemento** | Compite con Wonderdraft/Inkarnate con geología real. Sola es más débil (Azgaar es gratis); junto a `/batalla` forma un paquete único: "del planeta al encuentro". |
| `/juego` | Después, en Steam | Necesita 6–12 meses de pulido (tutorial, balance, IA). No va primero. |
| Generador científico | No directamente | Es el motor y el marketing (GIFs virales de tectónica), no el producto. Nadie paga por un atlas. |

La combinación **no existe en el mercado**: Dungeondraft hace battlemaps
desconectados de todo; Azgaar hace mundos sin battlemaps ni tectónica. Aquí se
genera el planeta, su historia geológica, sus reinos, y se baja hasta "las
ruinas junto al río que sí corre cuesta abajo". Ese es el pitch.

### 8.2 Mecanismos de cobro (glosario)

- **Pago único**: se paga una vez, se usa para siempre. Simple, sin
  infraestructura, pero cobras una sola vez por persona. Estándar para
  *herramientas* (Wonderdraft $29.99, **Dungeondraft $19.99** — el comparable
  directo).
- **Suscripción**: cobro mensual. Solo se justifica con **valor recurrente**:
  contenido nuevo cada mes (Patreon/Czepeku) o un servicio alojado en servidor
  (Inkarnate). Cobrar suscripción por algo que no cambia = cancelaciones y
  malas reseñas.
- **Freemium**: versión gratis limitada; se paga por desbloquear. Sirve de demo
  permanente y motor de boca a boca.
- **Donación/Patreon puro** (modelo Azgaar): techo bajo (~$5k/mes el mejor
  caso), sin fricción.

**Restricción técnica que decide el mecanismo:** ~~hoy todo corre en el
navegador del cliente en un HTML autocontenido~~ → **resuelta el 11-jul-2026**:
el motor del juego y los renders de fantasía/battlemaps se migraron al servidor
(`juego_srv.py`, `fantasia_srv.py`, `batalla_srv.py`; el front es solo
presentación). La opción **(b)** — el servidor "cerrable con llave" — ya
existe, lo que cambia el mecanismo recomendado. **Ver §9**, que reemplaza a
§8.3 como plan vigente.

### 8.3 Estrategia en orden

1. **Ahora — itch.io, freemium + pago único $12–15.** Web gratis: `/batalla`
   exporta a 70 px/casilla con marca de agua discreta, `/fantasia` a calidad
   1×. Pago (descarga de la app empaquetada): export HD (140 px, calidad 4×),
   todos los diales y semillas, y **licencia de uso comercial** (los DMs que
   publican módulos la necesitan y la valoran). $12–15: por debajo de
   Dungeondraft siendo desconocido; itch.io retiene ~10% (Steam 30%).
2. **A los 2–3 meses, con tracción — Patreon $5/mes por contenido, no por la
   herramienta.** El nivel de $5 entrega 3–4 **mundos curados/mes**: semilla +
   mapa fantasía rotulado + pack de 8–10 battlemaps de ese mundo + página de
   lore. Ahí sí hay valor recurrente real (modelo Czepeku, produciendo en horas
   lo que ellos pintan en semanas). La herramienta sigue siendo pago único: no
   mezclar.
3. **Más adelante — `/juego` en Steam, pago único $6–10**, con página "Coming
   Soon" abierta meses antes (los wishlists predicen todo). Los mundos del
   Patreon se vuelven escenarios del juego: el mismo motor cobra tres veces.

**Qué NO hacer:** suscripción por la herramienta (sin servidor ni valor
recurrente que la justifique), vender mapas sueltos a $2 (el generador abarata
el mapa individual — ver §2 y §7), y multijugador (ver §3).

### 8.4 Expectativa honesta

El escenario base del nicho: de cientos a pocos miles de dólares el primer año.
El bueno ($1–3k/mes sostenidos vía Patreon) llega con publicación constante de
mundos y marketing en r/battlemaps, r/worldbuilding y TikTok (los GIFs de
tectónica generándose son ideales). El paso con mejor relación
esfuerzo/aprendizaje es el **1**: empaquetar y subir a itch.io cuesta semanas,
no meses, y confirma con dinero real si hay demanda antes de invertir en el
resto.

---

## 9. Plan de precios v2 — con la lógica en el servidor (11-jul-2026)

> **Qué cambió.** Toda la lógica propietaria corre ahora en el back Python:
> motor del juego (con niebla censurada en servidor y guardado en disco),
> render fantasía (`/api/fantasia/render|sector|deco`) y battlemaps
> (`/api/batalla/*`), con caché en disco y render determinista por semilla.
> El navegador ya no recibe ni el código ni los datos que valen dinero. Eso
> desbloquea el mecanismo que en §8.2 estaba descartado: **SaaS con pasarela de
> pago**, cobrando por el servicio alojado — el modelo de Inkarnate, no el de
> Wonderdraft. La suscripción deja de ser deshonesta (§8.2) porque ahora sí hay
> servidor que mantener y cómputo que pagar.

### 9.1 Sí: ya puede ir detrás de una pasarela… con un colchón de trabajo

Lo cobrable ya es cerrable (el free tier se limita en el servidor: calidad,
resolución, marca de agua, nº de renders — el cliente no puede saltárselo).
Lo que falta **no es producto, es plomería**, y conviene presupuestarlo:

1. **Cuentas y sesiones** (hoy no hay usuarios): login simple + tabla de
   suscriptores. ~1–2 semanas.
2. **Endurecer el despliegue**: `web.py` es `http.server` escuchando en
   127.0.0.1; para internet hay que ponerlo detrás de un proxy (Caddy/nginx +
   HTTPS), meter rate-limiting por usuario y colas para los renders caros.
   ~1–2 semanas.
3. **Integrar la pasarela** (webhook de alta/baja → flag premium): ~1 semana.

Total honesto: **3–6 semanas** para pasar de "migrado" a "cobrable". Nada de
meses: el trabajo duro (mover el motor) ya está hecho.

### 9.2 Qué pasarela (dev individual en México)

| Opción | Comisión real | ¿Gestiona IVA global (MoR)? | Veredicto |
|---|---|---|---|
| **Paddle** | 5% + $0.50 | **Sí** | **La elegida**: merchant of record, paga a bancos mexicanos, sin cuota fija. En un plan de $5 se lleva ~15%; en el anual de $25, ~7% |
| Stripe MX | 3.6% + MXN$3 (+0.5% intl., +2% divisa, +0.7% Billing, +16% IVA sobre comisiones) | No — tú remites impuestos de cada país | Más barata en apariencia, pero te vuelve responsable del IVA internacional; no para un dev solo |
| Lemon Squeezy / Stripe Managed Payments | 5% + $0.50 (+0.5% subs) | Sí | Equivalente a Paddle; en transición (Stripe la absorbió; su MoR nativo está en preview desde feb-2026). Vigilar, no apostar aún |
| Gumroad | 10% + $0.50 | Sí | El doble de comisión que Paddle; solo si se quiere cero fricción |
| Patreon | ~13–15% efectivo (10% plano nuevos creadores + procesamiento) | Sí (IVA de membresías) | No para la herramienta; sigue siendo el canal correcto para el **contenido** (mundos curados, §8.3-2) |

Regla que sale de la tabla: **cobrar anual por defecto** — la parte fija
($0.50) y el peso de la comisión se diluyen 12×, y la caja llega por
adelantado.

### 9.3 El costo del servidor es ruido (números medidos, no estimados)

Tiempos reales medidos en esta máquina: render fantasía completo **3.7–9.3 s**
de CPU en frío, **~0.1 s** desde caché (determinista: misma semilla → mismo
PNG, la caché en disco convierte lo repetido en gratis); battlemap
**0.10–0.15 s** por generación. Servidor de referencia: **Hetzner CX33 (4
vCPU, 8 GB) ≈ €9/mes** con IPv4 (~$10 USD).

- Capacidad al 60% de uso sostenido: ~**6.2 millones de s-CPU/mes**.
- Un suscriptor *muy* activo (un DM que genera 300 battlemaps y 40 mapas
  fantasía HD al mes): ~420 s-CPU/mes. → **Un CX33 aguanta ~10,000 usuarios
  así**; siendo pesimistas ×10 en consumo, ~1,000.
- **Costo marginal por suscriptor: $0.01–0.10/mes.** El margen bruto del SaaS
  es ~98%: la comisión de la pasarela pesa 100 veces más que el cómputo.
- Arranque aún más barato: Fly.io con scale-to-zero (~$12/mes tope por 2
  vCPU) mientras no haya tráfico; migrar a Hetzner al crecer.

**Punto de equilibrio: 3 suscriptores mensuales** (3 × $4.25 netos ≈ $12.75 >
$10 de servidor). Todo lo demás es margen.

### 9.4 Precios (contra el mercado verificado a jul-2026)

Referencias vigentes: Inkarnate subió a **$7.99/mes (Creator)** y
**$14.99/mes (Studio, uso comercial)**; Dungeondraft sigue en ~$19.99 único;
Czepeku cobra $5 por pack y factura ~$76k por lanzamiento; Dungeon Scrawl Pro
$5/mes. Hay espacio debajo de Inkarnate y el pitch es distinto (geología real +
"del planeta al encuentro").

| Nivel | Precio | Qué incluye (todo se aplica en el servidor) |
|---|---|---|
| **Free** (demo permanente) | $0 | Mundos precocinados; fantasía calidad 1×; battlemap 70 px con marca de agua discreta; N renders/día. Es el marketing (§2) |
| **Pro** | **$4.99/mes o $29/año** (≈ $2.42/mes efectivo) | Mundos propios: semillas y diales del generador; fantasía calidad 4× + export 8K; battlemap 140 px sin marca; sin límites razonables |
| **Comercial** | **$9.99/mes o $59/año** | Pro + licencia comercial (DMs que publican módulos, escritores) + prioridad de cola. Espejo de la escalera de Inkarnate, ~un tercio más barato |

Con las conversiones del nicho (herramientas hobby: **2.2% mediana, 3–5%
bueno** según RevenueCat 2026 / Growth Unhinged):

| Usuarios free | Conversión | Suscriptores | Neto/mes (mezcla 80% Pro anual, 20% Comercial, tras Paddle y servidor) |
|---|---|---|---|
| 1,000 | 2.2% | 22 | ~$75 |
| 5,000 | 3% | 150 | ~$550 |
| 20,000 | 4% | 800 | ~$3,000 |

La fila de en medio es la meta realista del primer año; la última exige
marketing constante (r/battlemaps, r/worldbuilding, TikTok de tectónica). Son
los mismos escenarios de §8.4, pero ahora **recurrentes** en lugar de ventas
únicas.

### 9.5 Qué queda del plan anterior

- **§8.3-1 (itch.io pago único)** baja de "empezar aquí" a **opcional**: sirve
  como segundo canal (app de escritorio para quien no quiere suscripción, a
  $15–20 único), pero ya no es el único mecanismo honesto — y el SaaS captura
  valor recurrente que el pago único regala.
- **§8.3-2 (Patreon de mundos curados)** no cambia: sigue siendo contenido, a
  los 2–3 meses de tracción, y ahora cada mundo curado enlaza a la herramienta.
- **§8.3-3 (`/juego` en Steam)** no cambia de calendario, pero la migración le
  regaló la arquitectura multijugador-asíncrono-lista (§3: "mover toda la
  lógica al servidor" ya está hecho — órdenes validadas y azar tirado en el
  back). El asíncrono sigue condicionado a tracción, pero su costo bajó de
  2–4 meses a semanas.
- **Qué NO hacer** (actualiza §8.3): ya no aplica "no cobrar suscripción";
  ahora lo que no hay que hacer es **cobrar suscripción sin free tier** (la
  demo web es el embudo completo) ni gestionar el IVA a mano con Stripe puro.

---

## 10. LA DECISIÓN — qué cobrar, qué desarrollar, qué promocionar

Sin ambigüedad. Los tres productos funcionan; **no se lanzan los tres**: se
lanza **uno** con los otros dos en papeles de apoyo.

### 10.1 Modelo de cobro: SUSCRIPCIÓN freemium, vía Paddle

**Suscripción. No pago único, no Patreon, no itch.io como canal principal.**

- **Por qué suscripción:** el cliente objetivo (un DM) necesita mapas nuevos
  *cada semana* — es la definición de valor recurrente. El costo de servirlo
  es recurrente (servidor) y el margen es ~98% (§9.3). El pago único regala
  ese valor: Dungeondraft cobra $19.99 *una vez* por lo que Czepeku factura
  $76k *por pack*.
- **Cómo:** Paddle (merchant of record, §9.2). Precios de §9.4: Free de demo /
  **Pro $4.99/mes o $29/año** / **Comercial $9.99/mes o $59/año**. En la
  página, el botón grande es el **anual** — el mensual existe para bajar la
  barrera de entrada, no como opción por defecto.
- Pago único solo como excepción futura (app de escritorio en itch.io, si la
  piden), nunca como plan A.

### 10.2 Producto: los battlemaps mandan, la fantasía viste, el juego espera

**Un solo producto vendible: la herramienta creativa web = `/batalla` +
`/fantasia` juntas** ("del planeta al encuentro": generas el mundo, ves el
mapa de fantasía, haces clic en cualquier punto y sale el battlemap coherente
con ese lugar). Esa integración es lo que NADIE más tiene y es el pitch entero.

| Producto | Papel | % del esfuerzo |
|---|---|---|
| **`/batalla` (battlemaps)** | **El que se vende.** Es el nicho donde está el dinero (Czepeku $76k/pack; un DM consume mapas semanalmente) | **~50%** — más temas/subtipos, variantes (día/noche, estaciones), export directo a VTT (Foundry/Roll20: PNG + tamaño de rejilla) |
| **`/fantasia` (mapa de mundo)** | **El gancho y el diferenciador.** Es lo que se comparte en redes y lo que Dungeondraft no puede ofrecer: contexto planetario real | ~30% — pulido de export, más paletas, rótulos editables |
| **`/juego` (conquista)** | **Congelado como producto.** Se queda como *feature* gratis de la demo (retención y viralidad), y como carta futura para Steam cuando la herramienta ya genere ingresos | ~0% desarrollo nuevo; solo no romperlo |
| Generador científico (`tecto.py`) | El motor y la fábrica de marketing (GIFs de tectónica) — no se vende ni se expone | ~20% restante: plomería de §9.1 |

**Por qué no el juego primero:** necesita 6–12 meses de pulido (tutorial,
balance, IA) contra un mercado de mediana $5–15k *por venta única*; la
herramienta necesita 3–6 semanas de plomería contra un mercado de suscripción
demostrado ($80k/mes el líder). Mismo motor, 10× menos tiempo a caja.

### 10.3 Marketing: vender el battlemap, presumir el planeta

Un embudo, tres piezas:

1. **El contenido viral es la fantasía + tectónica** (TikTok/Reels/Shorts:
   time-lapse de un planeta formándose → zoom al mapa pergamino → clic → el
   battlemap del punto). El GIF de tectónica para el «wow», el battlemap para
   el «lo necesito».
2. **La comunidad objetivo es la de battlemaps**: r/battlemaps y r/FoundryVTT
   (publicar 2 packs gratis/semana con enlace "generado con..."),
   r/worldbuilding y r/mapmaking para la fantasía. La demo web gratis ES el
   funnel — sin descarga, clic y estás dentro.
3. **A los 2–3 meses con tracción: Patreon de mundos curados** (§8.3-2,
   $5/nivel) como segundo ingreso y fábrica de contenido para el punto 2.

Meta del primer año (§9.4): 5,000 usuarios free → ~150 suscriptores →
~$550/mes netos y creciendo. Si a los 6 meses la conversión es <1% o hay
<500 free, revisar precio/product-market-fit antes de meter más features.

### 10.4 Orden de ejecución (empieza hoy)

> El plan operativo completo (diseño, desarrollo semana a semana, marketing,
> métricas y riesgos) vive en [`PLATAFORMA.md`](PLATAFORMA.md).

1. Semanas 1–4: plomería de §9.1 (cuentas, proxy+HTTPS, colas, Paddle) sobre
   la herramienta unificada `/fantasia`+`/batalla`.
2. Semana 5: landing con demo gratis + los dos planes. Lanzar en beta a
   r/battlemaps pidiendo feedback (soft launch honesto).
3. Semanas 6+: ciclo semanal — 1 mejora de battlemaps + 2 posts de contenido.
   El juego y Steam ni se tocan hasta tener 100 suscriptores.

---

## Fuentes

- [games-stats: Age of History II](https://games-stats.com/steam/game/age-of-civilizations-ii/)
- [Steam Revenue Calculator: AoH2](https://steam-revenue-calculator.com/app/603850/age-of-history-ii)
- [Steam: Age of History 3](https://store.steampowered.com/app/2772750/Age_of_History_3/)
- [How To Market A Game: What happened in 2025](https://howtomarketagame.com/2026/01/27/what-the-hell-happened-in-2025/)
- [Steam Page Analyzer: Indie revenue data](https://www.steampageanalyzer.com/blog/indie-game-revenue-data)
- [game-developers.org: Steam Paradox 2025](https://game-developers.org/steam-paradox-2025-revenue-volume)
- [GameDiscoverCo: revenue por género](https://gamedevreports.substack.com/p/gamediscoverco-steam-revenue-distribution)
- [easypc.io: costos de servidores](https://www.easypc.io/game-hosts/cost/)
- [Guía itch.io 2026](https://generalistprogrammer.com/tutorials/how-to-make-money-on-itchio-indie-game-guide)
- [601media: browser games en itch.io](https://www.601media.com/make-money-browser-game-itchio/)
- [Graphtreon: Czepeku](https://graphtreon.com/creator/czepeku)
- [Graphtreon: Tom Cartos](https://graphtreon.com/creator/tomcartos)
- [Patreon: Heroic Maps](https://www.patreon.com/cw/heroicmaps)
- [Patreon de Azgaar](https://www.patreon.com/azgaar)
- [Azgaar's Fantasy Map Generator (GitHub)](https://github.com/Azgaar/Fantasy-Map-Generator)
- [Inkarnate vs Wonderdraft](https://loreteller.com/learn/inkarnate-vs-wonderdraft/)
- [rpgdrop: monetizar Patreon TTRPG](https://www.rpgdrop.com/how-to-build-a-successful-patreon-as-a-ttrpg-creator-a-guide-to-monetization/)

Fuentes de §9 (verificadas 11-jul-2026):

- [Paddle: pricing](https://www.paddle.com/pricing) · [países soportados](https://www.paddle.com/help/start/intro-to-paddle/which-countries-are-supported-by-paddle)
- [Stripe México: pricing](https://stripe.com/mx/pricing)
- [Lemon Squeezy: fees](https://docs.lemonsqueezy.com/help/getting-started/fees) · [estado 2026 / Stripe Managed Payments](https://www.lemonsqueezy.com/blog/2026-update)
- [Gumroad: pricing](https://gumroad.com/pricing)
- [Patreon: comisiones de creador](https://support.patreon.com/hc/en-us/articles/11111747095181-Creator-fees-overview) · [tarifa plana 10% (ago-2025)](https://support.patreon.com/hc/en-us/articles/36426991446797-A-standard-platform-fee-for-new-creators-effective-after-August-4-2025)
- [Inkarnate: FAQ/precios](https://inkarnate.com/faq) · [historial del cambio de precios](https://pricetimeline.com/data/price/inkarnate)
- [Graphtreon: Czepeku](https://graphtreon.com/creator/czepeku) · [Azgaar](https://graphtreon.com/creator/azgaar) · [Watabou](https://graphtreon.com/creator/watawatabou)
- [Czepeku: web vs Patreon](https://www.czepeku.com/blog/website-vs-patreon)
- [Hetzner: ajuste de precios jun-2026 (CX Gen3)](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)
- [DigitalOcean: droplets](https://www.digitalocean.com/pricing/droplets) · [Fly.io: pricing](https://fly.io/docs/about/pricing/) · [Railway: planes](https://docs.railway.com/reference/pricing/plans) · [Render.com: pricing](https://render.com/pricing)
- [Growth Unhinged: Free-to-Paid Conversion Report 2026](https://www.growthunhinged.com/p/free-to-paid-conversion-report)
- [First Page Sage: conversión freemium por industria (jun-2026)](https://firstpagesage.com/seo-blog/saas-freemium-conversion-rates/)
- [RevenueCat: State of Subscription Apps 2026](https://www.revenuecat.com/state-of-subscription-apps/)
