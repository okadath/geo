// cuenta.js — página «mi cuenta» (/cuenta).
// Sin sesión: formulario entrar/registro (dos pestañas, un solo form).
// Con sesión: email, plan, uso del día y tabla de upgrade con los precios de
// /api/pagos/config. Los botones de plan llaman a /api/pagos/checkout y, al
// recibir 503 (siempre hoy), muestran el aviso honesto de beta + lista de
// espera (ADR-007: NUNCA un checkout falso). Sin framework, ES modules.

import { montarNav, montarPie } from "/app/js/nav.js";
import { aviso, modal } from "/app/js/ui.js";

// destino de la lista de espera (el mismo que usa la landing / index.html).
const LISTA_ESPERA = "gustavo@merauto.com";

const raiz = document.getElementById("cuenta");

montarNav("cuenta");
montarPie({ lab: false });

// ---- utilidades ------------------------------------------------------------

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function capitalizar(s) {
  s = String(s || "");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// etiquetas visibles de cada difKey interno (las claves NO cambian; solo el
// rótulo que ve el jugador). Réplica del mapa DIF_ETIQUETAS de juego.html.
const DIF_ETIQUETAS = { facil: "fácil", medio: "normal",
                        normal: "difícil", dificil: "experto" };
const difEtiqueta = (k) => DIF_ETIQUETAS[k] || k;

// fecha ISO -> texto corto es-MX (o cadena vacía si no hay dato)
function fechaCorta(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  try {
    return d.toLocaleDateString("es-MX", {
      day: "numeric", month: "short", year: "numeric",
    });
  } catch (_) {
    return d.toISOString().slice(0, 10);
  }
}

// «mundo» abreviado a partir de sello + stem (identifica el detalle sin ruido)
function mundoBreve(sello, stem) {
  const s = String(sello || "").slice(0, 8);            // AAAAMMDD
  const hash = String(stem || "").split("_").pop() || ""; // 6 hex del detalle
  return hash ? `${s}·${hash}` : s;
}

async function postJSON(url, cuerpo) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(cuerpo || {}),
  });
  let datos = {};
  try { datos = await res.json(); } catch (_) { /* respuesta sin JSON */ }
  return { ok: res.ok, status: res.status, datos };
}

async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

// ---- carga inicial ---------------------------------------------------------

async function cargar() {
  let cuenta = null;
  let config = null;
  try {
    cuenta = await getJSON("/api/cuenta");
  } catch (_) {
    cuenta = { anonimo: true, plan: "free" }; // sin API: tratar como anónimo
  }
  try {
    config = await getJSON("/api/pagos/config");
  } catch (_) {
    config = { activo: false, modo: "beta", planes: [] };
  }
  raiz.removeAttribute("aria-busy");
  const anonimo = !cuenta || cuenta.anonimo === true || !cuenta.email;
  if (anonimo) pintarEntrar(config);
  else pintarSesion(cuenta, config);
}

// ---- vista sin sesión: entrar / crear cuenta -------------------------------

function pintarEntrar(config) {
  raiz.innerHTML = `
    <section class="cta-panel tarjeta">
      <h1>Mi cuenta</h1>
      <p class="cta-intro tenue">
        Entra para forjar tus propios mundos y llevar tu plan a cualquier
        dispositivo. Durante la beta el acceso es de facto Pro.
      </p>
      <div class="pestanas cta-tabs" role="tablist">
        <button class="pestana activa" role="tab" aria-selected="true"
                data-modo="entrar">Entrar</button>
        <button class="pestana" role="tab" aria-selected="false"
                data-modo="registro">Crear cuenta</button>
      </div>
      <form class="cta-form" novalidate>
        <div class="campo">
          <label for="cta-email">Correo</label>
          <input id="cta-email" name="email" type="email" autocomplete="email"
                 required placeholder="tu@correo.com">
        </div>
        <div class="campo">
          <label for="cta-clave">Contraseña</label>
          <input id="cta-clave" name="clave" type="password" required
                 autocomplete="current-password" placeholder="········"
                 minlength="6">
        </div>
        <button class="btn btn-oro btn-bloque btn-lg" type="submit"
                data-enviar>Entrar</button>
      </form>
      <p class="cta-precios-nota tenue">
        ¿Solo mirando? <a href="/estudio">Explora mundos de ejemplo</a> sin cuenta.
      </p>
    </section>`;

  let modo = "entrar";
  const tabs = raiz.querySelectorAll(".cta-tabs .pestana");
  const form = raiz.querySelector(".cta-form");
  const btn = raiz.querySelector("[data-enviar]");
  const clave = raiz.querySelector("#cta-clave");

  tabs.forEach((t) => t.addEventListener("click", () => {
    modo = t.dataset.modo;
    tabs.forEach((o) => {
      const act = o === t;
      o.classList.toggle("activa", act);
      o.setAttribute("aria-selected", act ? "true" : "false");
    });
    btn.textContent = modo === "entrar" ? "Entrar" : "Crear cuenta";
    clave.setAttribute("autocomplete",
      modo === "entrar" ? "current-password" : "new-password");
  }));

  montarPartidas(false);     // anónimo: solo si hay partidas locales

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = form.email.value.trim();
    const cl = form.clave.value;
    if (!email || !cl) { aviso("Escribe correo y contraseña.", "error"); return; }
    btn.disabled = true;
    const ruta = modo === "entrar"
      ? "/api/cuenta/entrar" : "/api/cuenta/registro";
    try {
      const r = await postJSON(ruta, { email, clave: cl });
      if (r.ok) {
        aviso(modo === "entrar" ? "Sesión iniciada." : "Cuenta creada.", "ok");
        setTimeout(() => location.reload(), 500);
        return;
      }
      if (r.status === 404) {
        // el back de cuentas aún no está montado (fase paralela)
        aviso("Las cuentas se activan muy pronto. Durante la beta el acceso "
              + "es Pro para todos.", "info", 6000);
      } else {
        aviso(r.datos.error || `No se pudo (${r.status}).`, "error");
      }
    } catch (_) {
      aviso("No se pudo conectar con el servidor.", "error");
    } finally {
      btn.disabled = false;
    }
  });
}

// ---- vista con sesión: plan, uso y upgrade ---------------------------------

function pintarSesion(cuenta, config) {
  const plan = String(cuenta.plan || "free");
  const nombrePlan = capitalizar(plan);
  const uso = cuenta.uso || {};
  const hoy = Number(uso.renders_hoy);
  const tope = Number(uso.tope_dia);
  const tieneUso = Number.isFinite(hoy) && Number.isFinite(tope) && tope > 0;
  const pct = tieneUso ? Math.min(100, Math.round((hoy / tope) * 100)) : 0;

  const expira = cuenta.expira
    ? `<p class="cta-expira tenue">Tu plan ${esc(nombrePlan)} vence el
       <strong>${esc(cuenta.expira)}</strong>.</p>`
    : "";

  const usoHTML = tieneUso ? `
    <div class="cta-uso">
      <div class="cta-uso-cab">
        <span class="campo-etiqueta">Renders de hoy</span>
        <span class="mono cta-uso-cifra">${hoy} / ${tope}</span>
      </div>
      <div class="barra-progreso"><div class="relleno"
           style="width:${pct}%"></div></div>
    </div>` : `
    <p class="tenue cta-uso-vacio">Sin límite diario práctico en tu plan.</p>`;

  raiz.innerHTML = `
    <section class="cta-panel tarjeta">
      <div class="cta-cabecera">
        <div>
          <h1>Mi cuenta</h1>
          <p class="cta-email mono">${esc(cuenta.email)}</p>
        </div>
        <span class="insignia insignia-pro cta-plan">${esc(nombrePlan)}</span>
      </div>
      ${expira}
      ${usoHTML}
      <div class="cta-acciones">
        <a class="btn" href="/estudio">Ir al Estudio</a>
        <button class="btn btn-fantasma" type="button" data-salir>Cerrar sesión</button>
      </div>
    </section>
    <section class="cta-upgrade">
      <h2>Planes</h2>
      <p class="tenue cta-upgrade-intro">
        Facturación anual por defecto (sale más barato). Durante la beta no
        cobramos: te apuntamos a la lista de acceso anticipado.
      </p>
      <div class="cta-planes" id="cta-planes"></div>
    </section>`;

  raiz.querySelector("[data-salir]").addEventListener("click", cerrarSesion);
  pintarPlanes(config, plan);
  montarPartidas(true);      // con sesión: siempre, con vacío amable
}

function pintarPlanes(config, planActual) {
  const cont = raiz.querySelector("#cta-planes");
  const planes = Array.isArray(config.planes) ? config.planes : [];
  if (!planes.length) {
    cont.innerHTML = `<p class="tenue">No se pudieron cargar los planes.</p>`;
    return;
  }
  cont.innerHTML = planes.map((p) => {
    const nombre = capitalizar(p.plan);
    const esActual = p.plan === planActual;
    const destacado = p.destacado ? " cta-plan-destacado" : "";
    const cinta = p.destacado
      ? `<span class="insignia insignia-pro cta-cinta">${esc(p.ciclo)}</span>`
      : "";
    const boton = esActual
      ? `<button class="btn btn-bloque" type="button" disabled>Tu plan actual</button>`
      : `<button class="btn ${p.destacado ? "btn-oro " : ""}btn-bloque"
                 type="button" data-plan="${esc(p.id)}"
                 data-nombre="${esc(nombre)}" data-precio="${esc(p.precio)}"
                 data-ciclo="${esc(p.ciclo)}">Elegir ${esc(nombre)}</button>`;
    return `
      <div class="tarjeta cta-plan-tarjeta${destacado}">
        ${cinta}
        <span class="cta-plan-nombre">${esc(nombre)}</span>
        <span class="cta-plan-ciclo tenue">${esc(p.ciclo)}</span>
        <div class="cta-plan-precio">${esc(p.precio)}</div>
        ${boton}
      </div>`;
  }).join("");

  cont.querySelectorAll("[data-plan]").forEach((b) => {
    b.addEventListener("click", () => elegirPlan(b.dataset));
  });
}

// checkout: hoy siempre 503 -> aviso honesto de beta + lista de espera.
async function elegirPlan(ds) {
  const { plan, nombre, precio, ciclo } = ds;
  try {
    const r = await postJSON("/api/pagos/checkout", { plan_id: plan });
    if (r.ok && r.datos && r.datos.url) {
      // futuro: pasarela activa -> ir al checkout real
      location.href = r.datos.url;
      return;
    }
    // 503 (modo beta) o cualquier otra negativa -> lista de espera honesta
    mostrarBeta(nombre, precio, ciclo);
  } catch (_) {
    mostrarBeta(nombre, precio, ciclo);
  }
}

function mostrarBeta(nombre, precio, ciclo) {
  const asunto = `Acceso anticipado Mundaria — ${nombre} ${ciclo}`;
  const cuerpo = `Hola, quiero unirme a la beta de Mundaria con el plan `
    + `${nombre} ${ciclo} (${precio}).`;
  const mailto = `mailto:${LISTA_ESPERA}`
    + `?subject=${encodeURIComponent(asunto)}`
    + `&body=${encodeURIComponent(cuerpo)}`;
  modal({
    titulo: "Beta — acceso anticipado",
    cuerpoHTML: `
      <p>La pasarela de pago todavía no está abierta: no simulamos ningún
      cobro. Durante la beta el acceso es de facto <strong>Pro</strong> para
      todos.</p>
      <p class="tenue">Apúntate a la lista de acceso anticipado del plan
      <strong>${esc(nombre)} ${esc(ciclo)}</strong> (${esc(precio)}) y te
      avisamos en cuanto activemos los pagos.</p>
      <div class="cta-beta-acciones">
        <a class="btn btn-oro btn-lg" href="${mailto}">
          Apuntarme a la lista</a>
        <button class="btn" type="button" data-cerrar>Ahora no</button>
      </div>`,
  });
}

// ---- sección «Partidas»: historial del juego de conquista -----------------
// Consume /api/juego/partidas (el back filtra por identidad: con sesión, las
// del email; anónimo, las locales sin dueño). `mostrarVacio` = pintar la
// sección aunque no haya partidas (con sesión sí; anónimo no, para no ensuciar
// la pantalla de login con un vacío cuando quizá nunca jugó).
async function montarPartidas(mostrarVacio) {
  let partidas = [];
  try {
    const r = await getJSON("/api/juego/partidas");
    partidas = Array.isArray(r.partidas) ? r.partidas : [];
  } catch (_) {
    partidas = [];
  }
  if (!partidas.length && !mostrarVacio) return;

  const enCurso = partidas.filter((p) => p.fase === "jugando");
  const terminadas = partidas.filter((p) => p.fase !== "jugando");

  const fila = (p) => {
    const estado = p.resultado === "victoria"
      ? `<span class="cta-part-estado es-victoria">🏆 victoria</span>`
      : p.resultado === "derrota"
        ? `<span class="cta-part-estado es-derrota">💀 derrota</span>`
        : `<span class="cta-part-estado es-curso">en curso</span>`;
    const enlace = `/juego?sello=${encodeURIComponent(p.sello)}`
      + `&d=${encodeURIComponent(p.stem)}`
      + (p.pid ? `&p=${encodeURIComponent(p.pid)}` : "")
      + `&ver=1`;   // al llegar se previsualiza en el mapa y se confirma con «entrar»
    return `
      <li class="cta-part-fila">
        <span class="cta-part-fecha tenue">${esc(fechaCorta(p.actualizado || p.creado))}</span>
        <span class="cta-part-mundo mono">${esc(mundoBreve(p.sello, p.stem))}</span>
        <span class="cta-part-turno tenue">turno ${esc(p.turno)}</span>
        <span class="cta-part-dif">${esc(difEtiqueta(p.difKey))}</span>
        ${estado}
        <a class="btn btn-fantasma cta-part-abrir" href="${enlace}">abrir</a>
      </li>`;
  };

  const grupo = (titulo, lista) => lista.length
    ? `<h3 class="cta-part-grupo">${titulo}</h3>
       <ul class="cta-part-lista">${lista.map(fila).join("")}</ul>`
    : "";

  const vacio = partidas.length ? "" : `
    <p class="tenue cta-part-vacio">Aún no hay partidas — ve al
      <a href="/estudio">Estudio</a>, elige un mundo y conquístalo.</p>`;

  const sec = document.createElement("section");
  sec.className = "cta-partidas";
  sec.innerHTML = `
    <h2>🎮 Partidas</h2>
    ${grupo("En curso", enCurso)}
    ${grupo("Terminadas", terminadas)}
    ${vacio}`;
  raiz.appendChild(sec);
}

async function cerrarSesion() {
  try {
    await postJSON("/api/cuenta/salir", {});
  } catch (_) { /* aunque falle, recargamos para reflejar el estado */ }
  aviso("Sesión cerrada.", "info");
  setTimeout(() => location.reload(), 400);
}

cargar();
