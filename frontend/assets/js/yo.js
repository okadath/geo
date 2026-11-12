// yo.js — página /yo (cuenta única), heredada de la antigua cuenta.js.
// Anónimo: «Entra con tu correo» (enlace mágico, sin contraseñas), aviso si
//   llega con ?enlace=invalido y, debajo, #pro con la tabla de planes y el
//   checkout (pide el correo, porque no hay sesión).
// Con sesión: plan, uso del día y botones; mundos y battlemaps guardados;
//   «Tus mundos» (los generados, Pro); al final #pro con la tabla de planes
//   (sin checkout si ya es Pro).
// Checkout (ADR-007): POST /api/pagos/checkout; 503 = modo beta sin Paddle ->
// aviso honesto + lista de espera. NUNCA un checkout falso. El front solo
// presenta: plan, límites y guardados los decide el servidor.

import { montarNav, montarPie, refrescarNav } from "/app/js/nav.js";
import { aviso, modal, cuadroCorreo } from "/app/js/ui.js";
import * as api from "/app/js/api.js";

// destino de la lista de espera mientras no haya pasarela (ADR-007)
const LISTA_ESPERA = "gustavo@merauto.com";

const raiz = document.getElementById("yo");

montarNav({ activa: "yo" });
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

// fecha (ISO o epoch en segundos) -> texto corto es-MX; "" si no hay dato
function fechaCorta(v) {
  if (v === null || v === undefined || v === "") return "";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  if (isNaN(d)) return "";
  try {
    return d.toLocaleDateString("es-MX", { day: "numeric", month: "short", year: "numeric" });
  } catch (_) {
    return d.toISOString().slice(0, 10);
  }
}

// nombre legible de un mundo (GET /api/w/<sello>), memoizado; sello si falla
const _nombres = new Map();
function nombreDe(sello) {
  if (!_nombres.has(sello)) {
    _nombres.set(sello, api.mundo(sello).then((m) => (m && m.nombre) || sello)
      .catch(() => sello));
  }
  return _nombres.get(sello);
}

// rellena los [data-nombre-sello] de `cont` con el nombre del mundo
function rellenarNombres(cont) {
  cont.querySelectorAll("[data-nombre-sello]").forEach(async (el) => {
    el.textContent = await nombreDe(el.dataset.nombreSello);
  });
}

async function getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
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

// /yo#pro: el contenido se pinta tarde, así que el salto nativo al ancla no
// ocurre; se repite cuando el bloque ya existe.
function irAlAncla() {
  if (location.hash !== "#pro") return;
  const pro = document.getElementById("pro");
  if (pro) pro.scrollIntoView({ block: "start" });
}

// ---- carga inicial ---------------------------------------------------------

async function cargar() {
  let cuenta = null;
  let config = null;
  try {
    cuenta = await api.cuenta();
  } catch (_) {
    cuenta = { anonimo: true, plan: "free" }; // sin API: tratar como anónimo
  }
  try {
    config = await getJSON("/api/pagos/config");
  } catch (_) {
    config = { activo: false, modo: "beta", planes: [] };
  }
  raiz.removeAttribute("aria-busy");
  if (api.conSesion(cuenta)) await pintarSesion(cuenta, config);
  else pintarAnonimo(config);
  irAlAncla();
}

// ---- anónimo: entrar con correo + planes -----------------------------------

function pintarAnonimo(config) {
  const invalido = new URLSearchParams(location.search).get("enlace") === "invalido";
  raiz.innerHTML = `
    <section class="yo-panel yo-entrar">
      <h1>Tu cuenta</h1>
      ${invalido ? `<div class="aviso aviso-error yo-aviso-fijo" role="alert">
        Ese enlace ya no vale: caducó o ya se usó. Pide uno nuevo abajo.</div>` : ""}
      <div data-correo></div>
    </section>
    ${seccionPlanes()}`;
  // al entrar, el enlace vuelve a /yo (sin ?enlace=invalido)
  cuadroCorreo({
    volver: "/yo",
    montarEn: raiz.querySelector("[data-correo]"),
    titulo: "Entra con tu correo",
    texto: "Te enviamos un enlace para entrar; sin contraseñas. "
      + "Si no tienes cuenta, se crea al entrar.",
  });
  pintarPlanes(config, { plan: "free", anonimo: true });
}

// ---- con sesión ------------------------------------------------------------

async function pintarSesion(cuenta, config) {
  const plan = String(cuenta.plan || "free");
  const pro = api.esPro(cuenta);
  const nombrePlan = capitalizar(plan);
  const uso = cuenta.uso || {};
  const hoy = Number(uso.renders_hoy);
  const tope = uso.tope_dia == null ? NaN : Number(uso.tope_dia);
  const tieneTope = Number.isFinite(hoy) && Number.isFinite(tope) && tope > 0;
  const pct = tieneTope ? Math.min(100, Math.round((hoy / tope) * 100)) : 0;

  const expira = cuenta.expira && plan !== "free"
    ? `<p class="yo-expira tenue">Tu plan ${esc(nombrePlan)} vence el
       <strong>${esc(cuenta.expira)}</strong>.</p>`
    : "";
  const vencido = cuenta.plan_contratado && cuenta.plan_contratado !== plan
    ? `<p class="yo-expira tenue">Tu plan ${esc(capitalizar(cuenta.plan_contratado))}
       venció; vuelves a Free hasta renovarlo.</p>`
    : "";

  const usoHTML = tieneTope ? `
    <div class="yo-uso">
      <div class="yo-uso-cab">
        <span class="campo-etiqueta">Renders de hoy</span>
        <span class="mono yo-uso-cifra">${hoy} / ${tope}</span>
      </div>
      <div class="barra-progreso"><div class="relleno" style="width:${pct}%"></div></div>
    </div>` : `
    <p class="tenue yo-uso-vacio">Renders de hoy: <span class="mono">${
      Number.isFinite(hoy) ? hoy : 0}</span> · sin límite diario en tu plan.</p>`;

  const botonPlan = pro
    ? `<button class="btn" type="button" data-portal>Gestionar suscripción</button>`
    : `<a class="btn btn-oro" href="#pro">Pasar a Pro</a>`;

  raiz.innerHTML = `
    <section class="yo-panel tarjeta">
      <div class="yo-cabecera">
        <div>
          <h1>Tu cuenta</h1>
          <p class="yo-email mono">${esc(cuenta.email)}</p>
        </div>
        <span class="insignia insignia-pro yo-plan" data-plan-actual="${esc(plan)}">${esc(nombrePlan)}</span>
      </div>
      ${expira}${vencido}
      ${usoHTML}
      <div class="yo-acciones">
        ${botonPlan}
        <button class="btn btn-fantasma" type="button" data-salir>Salir</button>
      </div>
    </section>
    <section class="yo-seccion" id="guardados-mundos">
      <h2>Mundos guardados</h2>
      <div data-lista><p class="tenue">Cargando…</p></div>
    </section>
    <section class="yo-seccion" id="guardados-battlemaps">
      <h2>Battlemaps guardados</h2>
      <div data-lista><p class="tenue">Cargando…</p></div>
    </section>
    ${seccionPropios(cuenta)}
    ${seccionPlanes()}`;

  raiz.querySelector("[data-salir]").addEventListener("click", salir);
  const portal = raiz.querySelector("[data-portal]");
  if (portal) portal.addEventListener("click", () => abrirPortal(config));
  pintarPlanes(config, cuenta);
  const propios = raiz.querySelector("#tus-mundos");
  if (propios) rellenarNombres(propios);
  await pintarGuardados();
}

// «Tus mundos»: sellos generados por el usuario (el servidor solo los envía
// para Pro). Sin propios y sin Pro no se pinta la sección.
function seccionPropios(cuenta) {
  const sellos = Array.isArray(cuenta.mundos_propios) ? cuenta.mundos_propios : [];
  if (!sellos.length && !api.esPro(cuenta)) return "";
  const cuerpo = sellos.length
    ? `<ul class="yo-lista">${sellos.map((s) => `
        <li class="yo-fila">
          <a class="yo-fila-enlace" href="${esc(api.urlMundo(s))}">
            <span class="yo-fila-nombre" data-nombre-sello="${esc(s)}">${esc(s)}</span>
            <span class="yo-fila-meta mono">${esc(s)}</span>
          </a>
        </li>`).join("")}</ul>`
    : `<p class="tenue yo-vacio">Aún no has generado mundos.
        <a href="/nuevo">Forja el primero</a>.</p>`;
  return `
    <section class="yo-seccion" id="tus-mundos">
      <h2>Tus mundos</h2>
      ${cuerpo}
    </section>`;
}

async function pintarGuardados() {
  const contM = raiz.querySelector("#guardados-mundos [data-lista]");
  const contB = raiz.querySelector("#guardados-battlemaps [data-lista]");
  let items = [];
  try {
    items = await api.guardados();
  } catch (e) {
    const msg = `<p class="tenue">No se pudieron cargar tus guardados (${esc(e.message)}).</p>`;
    contM.innerHTML = msg;
    contB.innerHTML = msg;
    return;
  }
  const mundos = items.filter((g) => g.tipo === "mundo");
  const bms = items.filter((g) => g.tipo === "battlemap");
  pintarLista(contM, mundos, filaMundo,
    `Aún no guardas mundos. Ábrelos desde <a href="/">Explorar</a> y pulsa ★ Guardar.`);
  pintarLista(contB, bms, filaBattlemap,
    "Aún no guardas battlemaps. En cualquier encuentro, pulsa ★ Guardar.");
}

function filaMundo(g) {
  return `
    <a class="yo-fila-enlace" href="${esc(api.urlMundo(g.sello, g.query || undefined))}">
      <span class="yo-fila-nombre" data-nombre-sello="${esc(g.sello)}">${esc(g.sello)}</span>
      <span class="yo-fila-meta tenue">${esc(fechaCorta(g.creado))}</span>
    </a>`;
}

function filaBattlemap(g) {
  return `
    <a class="yo-fila-enlace" href="${esc(api.urlBattlemap(g.sello, g.x, g.y, g.query || undefined))}">
      <span class="yo-fila-nombre"><span data-nombre-sello="${esc(g.sello)}">${esc(g.sello)}</span>
        <span class="mono yo-fila-coord">${esc(g.x)},${esc(g.y)}</span></span>
      <span class="yo-fila-meta tenue">${esc(fechaCorta(g.creado))}</span>
    </a>`;
}

function pintarLista(cont, lista, fila, vacioHTML) {
  if (!lista.length) {
    cont.innerHTML = `<p class="tenue yo-vacio">${vacioHTML}</p>`;
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "yo-lista";
  for (const g of lista) {
    const li = document.createElement("li");
    li.className = "yo-fila";
    li.innerHTML = `${fila(g)}
      <button class="btn btn-fantasma btn-sm yo-quitar" type="button"
              aria-label="Quitar de guardados">Quitar</button>`;
    li.querySelector(".yo-quitar").addEventListener("click", async (ev) => {
      const b = ev.currentTarget;
      b.disabled = true;
      try {
        await api.quitarGuardado(g);
        li.remove();
        if (!ul.children.length) cont.innerHTML = `<p class="tenue yo-vacio">${vacioHTML}</p>`;
        refrescarNav();
        aviso("Quitado de tus guardados.", "ok");
      } catch (e) {
        b.disabled = false;
        aviso(`No se pudo quitar: ${e.message}`, "error");
      }
    });
    ul.appendChild(li);
  }
  cont.replaceChildren(ul);
  rellenarNombres(cont);
}

// Portal de cliente de Paddle (cambiar o cancelar el plan). Sin pasarela
// activa no hay portal: se explica con honestidad (ADR-007).
function abrirPortal(config) {
  if (config && config.portal) {
    location.href = config.portal;
    return;
  }
  const asunto = "Pangeira — gestionar mi suscripción";
  modal({
    titulo: "Gestionar suscripción",
    cuerpoHTML: `
      <p>El portal de Paddle para cambiar o cancelar el plan se abre cuando
      activemos los pagos. Durante la beta no hay cobros.</p>
      <p class="tenue">¿Necesitas algo con tu plan? Escríbenos.</p>
      <div class="yo-beta-acciones">
        <a class="btn btn-oro" href="mailto:${LISTA_ESPERA}?subject=${encodeURIComponent(asunto)}">
          Escribirnos</a>
        <button class="btn" type="button" data-cerrar>Cerrar</button>
      </div>`,
  });
}

async function salir() {
  try {
    await api.salir();
  } catch (_) { /* aunque falle, recargamos para reflejar el estado */ }
  try { await refrescarNav(); } catch (_) { /* da igual: se recarga */ }
  aviso("Sesión cerrada.", "info");
  setTimeout(() => location.reload(), 300);
}

// ---- planes y checkout (#pro) ----------------------------------------------

function seccionPlanes() {
  return `
    <section class="yo-seccion yo-upgrade" id="pro">
      <h2>Planes</h2>
      <p class="tenue yo-upgrade-intro">
        Facturación anual por defecto (sale más barato). Durante la beta no
        cobramos: te apuntamos a la lista de acceso anticipado.
      </p>
      <div data-correo-pago></div>
      <div class="yo-planes" id="yo-planes"></div>
    </section>`;
}

// cuenta: {plan, anonimo?}. Anónimo -> checkout con correo tecleado; free con
// sesión -> checkout con el correo de la sesión; Pro -> tabla sin checkout.
function pintarPlanes(config, cuenta) {
  const cont = raiz.querySelector("#yo-planes");
  const planActual = String(cuenta.plan || "free");
  const anonimo = !api.conSesion(cuenta);
  const sinCheckout = api.esPro(cuenta);
  const planes = Array.isArray(config.planes) ? config.planes : [];
  if (!planes.length) {
    cont.innerHTML = `<p class="tenue">No se pudieron cargar los planes.</p>`;
    return;
  }

  let inputCorreo = null;
  if (anonimo) {
    const zona = raiz.querySelector("[data-correo-pago]");
    zona.innerHTML = `
      <div class="campo yo-correo-pago">
        <label for="yo-correo-pago">Tu correo</label>
        <input id="yo-correo-pago" type="email" name="email" autocomplete="email"
               placeholder="tu@correo.com" required>
        <span class="tenue yo-correo-nota">Tu cuenta se crea con el pago; luego
          entras con un enlace a este correo.</span>
      </div>`;
    inputCorreo = zona.querySelector("input");
  }

  cont.innerHTML = planes.map((p) => {
    const nombre = capitalizar(p.plan);
    const esActual = p.plan === planActual;
    const destacado = p.destacado ? " yo-plan-destacado" : "";
    const cinta = p.destacado
      ? `<span class="insignia insignia-pro yo-cinta">${esc(p.ciclo)}</span>`
      : "";
    let boton = "";
    if (esActual && !anonimo) {
      boton = `<button class="btn btn-bloque" type="button" disabled>Tu plan actual</button>`;
    } else if (!sinCheckout) {
      boton = `<button class="btn ${p.destacado ? "btn-oro " : ""}btn-bloque"
                 type="button" data-plan="${esc(p.id)}"
                 data-nombre="${esc(nombre)}" data-precio="${esc(p.precio)}"
                 data-ciclo="${esc(p.ciclo)}">Elegir ${esc(nombre)}</button>`;
    }
    return `
      <div class="tarjeta yo-plan-tarjeta${destacado}">
        ${cinta}
        <span class="yo-plan-nombre">${esc(nombre)}</span>
        <span class="yo-plan-ciclo tenue">${esc(p.ciclo)}</span>
        <div class="yo-plan-precio">${esc(p.precio)}</div>
        ${boton}
      </div>`;
  }).join("");

  cont.querySelectorAll("[data-plan]").forEach((b) => {
    b.addEventListener("click", () => elegirPlan(b, inputCorreo));
  });
}

// checkout: hoy 503 (modo beta, sin Paddle) -> aviso honesto + lista de espera.
async function elegirPlan(boton, inputCorreo) {
  const { plan, nombre, precio, ciclo } = boton.dataset;
  const cuerpo = { plan_id: plan };
  if (inputCorreo) {
    const email = inputCorreo.value.trim();
    if (email && !inputCorreo.checkValidity()) {
      aviso("Escribe un correo válido.", "error");
      inputCorreo.focus();
      return;
    }
    if (email) cuerpo.email = email;
  }
  boton.disabled = true;
  try {
    const r = await postJSON("/api/pagos/checkout", cuerpo);
    if (r.ok && r.datos && r.datos.url) {
      location.href = r.datos.url; // pasarela activa -> checkout real
      return;
    }
    if (r.status === 400 && inputCorreo) {
      // con pasarela activa, un anónimo debe dar su correo
      aviso(r.datos.error === "email invalido"
        ? "Escribe tu correo para crear la cuenta con el pago."
        : (r.datos.error || "No se pudo iniciar el pago."), "error");
      inputCorreo.focus();
      return;
    }
    mostrarBeta(nombre, precio, ciclo);
  } catch (_) {
    mostrarBeta(nombre, precio, ciclo);
  } finally {
    boton.disabled = false;
  }
}

function mostrarBeta(nombre, precio, ciclo) {
  const asunto = `Acceso anticipado Pangeira — ${nombre} ${ciclo}`;
  const cuerpo = `Hola, quiero unirme a la beta de Pangeira con el plan `
    + `${nombre} ${ciclo} (${precio}).`;
  const mailto = `mailto:${LISTA_ESPERA}`
    + `?subject=${encodeURIComponent(asunto)}`
    + `&body=${encodeURIComponent(cuerpo)}`;
  modal({
    titulo: "Beta — acceso anticipado",
    cuerpoHTML: `
      <p>La pasarela de pago todavía no está abierta: no simulamos ningún
      cobro.</p>
      <p class="tenue">Apúntate a la lista de acceso anticipado del plan
      <strong>${esc(nombre)} ${esc(ciclo)}</strong> (${esc(precio)}) y te
      avisamos en cuanto activemos los pagos.</p>
      <div class="yo-beta-acciones">
        <a class="btn btn-oro btn-lg" href="${mailto}">Apuntarme a la lista</a>
        <button class="btn" type="button" data-cerrar>Ahora no</button>
      </div>`,
  });
}

cargar();
