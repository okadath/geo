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
