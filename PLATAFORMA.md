# PLATAFORMA.md — plan para levantar la plataforma

Plan operativo de diseño, desarrollo, marketing y lanzamiento de la
**herramienta creativa web** (`/fantasia` + `/batalla`, pitch «del planeta al
encuentro»). Deriva de la estrategia decidida en [`NEGOCIO.md`](NEGOCIO.md)
§9–10: suscripción freemium vía Paddle, battlemaps como producto principal,
`/juego` congelado como feature gratis de la demo.

Estado de partida (12-jul-2026): toda la lógica propietaria ya corre en el
servidor (`juego_srv.py`, `fantasia_srv.py`, `batalla_srv.py` sobre `web.py`);
los HTML son solo presentación. Lo que falta es **plomería de plataforma**,
no producto.

---

## 1. Diseño (producto y experiencia)

### 1.1 El producto unificado

Hoy `/fantasia` y `/batalla` son dos páginas separadas que comparten query
(`?sello=…&d=…`). Para vender hay que presentarlas como **una sola
herramienta** con un flujo continuo:

1. **Elegir mundo** → galería de mundos precocinados (free) o «generar el
   mío» (Pro: semilla + diales).
2. **Ver el planeta** → mapa fantasía navegable (ya existe: sectores al hacer
   zoom).
3. **Clic en un punto** → ficha del lugar + battlemap generado (ya existe).
4. **Exportar** → PNG (free: 70 px con marca de agua; Pro: 140 px/8K limpio;
   Comercial: + licencia).

Trabajo de diseño concreto:

- **Página de inicio de la herramienta** (nueva): galería de mundos con
  miniaturas, buscador por semilla, botón «generar mundo» (gateado por plan).
- **Navegación entre las dos vistas** sin volver al índice: desde el mapa
  fantasía, clic-derecho o botón «⚔ battlemap aquí» que lleva a `/batalla`
  con el punto preseleccionado (hoy el enlace cruzado existe pero sin punto).
- **Marca de agua y límites free**: se aplican **en el servidor** (los módulos
  `_srv` ya reciben todos los parámetros; añadir el plan del usuario al
  contexto de render). Nunca en JS.
- Nombre y dominio del producto: decidir antes de la landing (pendiente del
  dueño; todo lo demás no depende de esto).

### 1.2 Free vs Pro vs Comercial (qué gatea el servidor)

| Capacidad | Free | Pro | Comercial |
|---|---|---|---|
| Mundos precocinados | ✔ | ✔ | ✔ |
| Generar mundo propio (semilla + diales) | ✖ | ✔ | ✔ |
| Fantasía: calidad | 1× | hasta 4× | hasta 4× |
| Fantasía: export | 2K con marca | 8K limpio | 8K limpio |
| Battlemap: export | 70 px con marca | 140 px | 140 px |
| Renders/día | ~20 | sin límite práctico | sin límite práctico |
| Licencia comercial | ✖ | ✖ | ✔ |
| Cola de render | normal | normal | prioritaria |
| `/juego` (conquista) | ✔ gratis para todos (retención) | ✔ | ✔ |

Precios: **Pro $4.99/mes o $29/año · Comercial $9.99/mes o $59/año**, anual
por defecto (`NEGOCIO.md` §9.4).

---

## 2. Desarrollo (plomería, en orden)

Presupuesto total honesto: **3–6 semanas** a tiempo completo.

### Semana 1–2 — cuentas y planes

- [ ] Tabla de usuarios (email + hash de contraseña o magic link) y sesiones
  con cookie firmada. SQLite basta de sobra al inicio (un archivo junto a
  `salidas/`).
- [ ] Campo `plan` (free/pro/comercial) + fecha de expiración en el usuario.
- [ ] Middleware en `web.py`: resolver el usuario de la cookie y pasar el plan
  a los módulos `_srv` (parámetro nuevo en `manejar_get/manejar_post` o
  atributo en el handler).
- [ ] Aplicar los gates de §1.2 dentro de `fantasia_srv.py` / `batalla_srv.py`
  (marca de agua, calidad máxima, contador de renders/día por usuario).
- [ ] Los mundos free precocinados: elegir 6–10 corridas buenas de `salidas/`
  y marcarlas como públicas.

### Semana 2–3 — despliegue endurecido

- [ ] `web.py` sigue siendo `http.server` mono-hilo por diseño local. Para
  producción: **Caddy** delante (HTTPS automático) + N procesos de `web.py`
  detrás, o migración ligera del `Manejador` a WSGI (waitress/gunicorn). Los
  módulos `_srv` no cambian: su contrato es `(handler, url/ruta, datos)`.
- [ ] **Cola de renders**: los renders fríos de fantasía toman 4–9 s; con
  varios usuarios simultáneos hay que serializarlos por worker (cola en
  proceso con N workers = nº de vCPU − 1) y responder 202 + polling o
  mantener la conexión. La caché en disco ya absorbe lo repetido.
- [ ] **Rate-limiting** por usuario/IP (renders fríos por minuto) — es también
  la defensa anti-scraping del free tier.
- [ ] Servidor: empezar en **Fly.io** (scale-to-zero, ~$12/mes tope) o
  directo **Hetzner CX33** (€9/mes, aguanta miles de usuarios — §9.3).
  Backups diarios de la BD de usuarios y de `salidas/` públicos.
- [ ] Logs mínimos: renders/día, cache hit rate, errores 5xx.

### Semana 3–4 — pasarela

- [ ] Alta en **Paddle** (aprobación manual: iniciarla la semana 1, en
  paralelo).
- [ ] Checkout overlay de Paddle en la landing (no requiere backend propio de
  pagos).
- [ ] **Webhooks**: `subscription.created/updated/canceled` → actualizar
  `plan` y expiración del usuario. Un solo endpoint POST, verificando la
  firma de Paddle.
- [ ] Página «mi cuenta»: plan actual, botón al portal de Paddle (cancelar/
  cambiar plan lo gestiona Paddle, no nosotros).

### Semana 5 — landing y beta

- [ ] Landing: demo embebida o GIF del flujo completo (planeta → pergamino →
  battlemap), tabla de planes, FAQ corta (licencia comercial, «¿mis mapas son
  míos?» → sí).
- [ ] Onboarding: al entrar sin cuenta se puede usar el free tier con límites
  por IP; crear cuenta solo para guardar mundos o pagar (menos fricción).
- [ ] Soft launch en r/battlemaps (ver §3).

### Explícitamente fuera de alcance del lanzamiento

Generación de corridas nuevas por usuarios anónimos (cara: minutos de CPU —
los mundos Pro se generan con cola y límite), APK móvil, multijugador,
Steam, editor manual de mapas. Nada de esto antes de 100 suscriptores.

---

## 3. Marketing (embudo y calendario)

Principio (`NEGOCIO.md` §10.3): **vender el battlemap, presumir el planeta.**

### 3.1 Antes del lanzamiento (semanas 1–4, en paralelo al desarrollo)

- Crear cuentas: TikTok/YouTube Shorts/Instagram Reels (mismo video en los
  tres), Reddit con karma real (participar, no solo publicar), X/Bluesky.
- Producir el **video semilla**: time-lapse de tectónica → zoom al mapa
  pergamino → clic → battlemap del punto. 30–45 s, sin voz, texto sobreimpreso.
  Es el activo de marketing nº 1; hacer 3–4 variantes (mundos distintos).
- **2 packs de battlemaps gratis por semana** en r/battlemaps y r/FoundryVTT
  (PNG listos para VTT, con «generado con [herramienta] — beta pronto» en el
  comentario, no en la imagen). Esto construye el público ANTES de tener qué
  vender.

### 3.2 Lanzamiento (semana 5)

- Post honesto de beta en r/battlemaps y r/worldbuilding: qué hace, qué no,
  free tier real, pedir feedback. Los subreddits castigan el marketing
  encubierto y premian al dev solo que muestra su trabajo.
- Publicar el video semilla en TikTok/Shorts/Reels el mismo día.
- Descuento de lanzamiento en el anual (p. ej. $19 el primer año) por tiempo
  limitado — al anual, nunca al mensual.

### 3.3 Ritmo permanente (semana 6+)

Ciclo semanal fijo: **1 mejora visible de battlemaps + 2 piezas de contenido**
(1 pack gratis + 1 video corto). Mensual: 1 post largo tipo devlog
(r/proceduralgeneration adora los GIFs de tectónica; es tráfico de devs pero
da enlaces y credibilidad).

A los 2–3 meses con tracción: **Patreon de mundos curados** ($5/mes: semilla +
mapa rotulado + 8–10 battlemaps + lore) como segundo ingreso, enlazando cada
mundo a la herramienta.

### 3.4 Métricas y umbrales de decisión

| Métrica | Meta 3 meses | Meta 12 meses | Umbral de alarma |
|---|---|---|---|
| Usuarios free registrados | 1,000 | 5,000+ | <500 a los 6 meses |
| Conversión free→pago | ≥2% | 3–5% | <1% a los 6 meses |
| Suscriptores de pago | ~20 | ~150 | — |
| Neto mensual | ~$75 | ~$550 | — |
| Churn mensual | — | <5% | >10% sostenido |

Si se cruza un umbral de alarma: **revisar precio y product-market-fit antes
de construir más features** (`NEGOCIO.md` §10.3). Si se llega a 100
suscriptores: descongelar la ruta Steam de `/juego` (§10.2).

---

## 4. Pasos inmediatos (checklist de arranque)

1. [ ] Elegir nombre y comprar dominio.
2. [ ] Iniciar el alta en Paddle (tarda; hacerlo ya).
3. [ ] Commitear la migración al back (los tres `_srv.py` + fronts + docs) —
   es la base de todo lo anterior y sigue sin commit.
4. [ ] Elegir los 6–10 mundos precocinados del free tier.
5. [ ] Empezar semana 1 del plan de desarrollo (§2) y el §3.1 en paralelo.
6. [ ] Grabar el video semilla en cuanto el flujo unificado (§1.1) exista.

---

## Riesgos y mitigaciones

- **Paddle rechaza o tarda la cuenta** → plan B: Lemon Squeezy / Stripe
  Managed Payments (mismo modelo MoR, §9.2); no cambia nada del diseño.
- **El render frío satura el servidor en un pico de Reddit** → la cola + el
  free tier limitado por IP + caché en disco absorben; si no basta, subir a
  CX43 son minutos y ~€7 más.
- **Copia del concepto** → la ventaja no es la idea sino el motor (tectónica/
  clima/hidrología reales, años de trabajo) que ahora vive solo en el
  servidor; publicar mucho y rápido es la mejor defensa.
- **Conversión bajo el umbral** → antes de tocar features, probar: precio
  anual más agresivo, marca de agua más visible en free, o límite de
  renders/día más estricto (las tres palancas son de configuración, no de
  código).
