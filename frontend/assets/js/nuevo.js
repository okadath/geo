// nuevo.js — página /nuevo: asistente «Forjar mundo» (ADR-005), heredado de
// la antigua estudio.js. Presets, semilla (prellenada con ?semilla=), ajustes
// avanzados plegados y la cadena generar → esperar → detallar → esperar con la
// barra de progreso de dos fases. Al terminar abre la ficha del mundo nuevo.
//
// Gating (ADR-007): generar mundos propios es Pro. Sin Pro el formulario se
// pinta igual (para ver lo que se compra) pero deshabilitado y bajo el muro
// Pro, y NUNCA se llama a api.generar. El servidor es quien decide de verdad
// (POST /api/generar responde 403 a free); aquí solo se presenta.

import { montarNav, montarPie } from "/app/js/nav.js";
import { logoSVG } from "/app/js/marca.js";
import { aviso, muroPro } from "/app/js/ui.js";
import * as api from "/app/js/api.js";

/* =========================================================================
   Configuración: presets y diales
   ========================================================================= */

// Valores por defecto de generación (espejo de PARAMS en servidor/config.py).
// Cada preset solo sobreescribe lo que le da carácter; el resto hereda esto.
const GEN_DEFAULTS = {
  tiempo: 800, cada: 8, ms: 60, resolucion: 256, detalle: 0.6,
  velocidad: 18, mar: 0.52, continentes: 0.55, plumas: 70, erosion: 0.008,
  empuje: 0.15, momento: 0.02, rigidez: 0.85, deriva: 8, anos_paso: 1,
};

// Valores por defecto del detallado (espejo de DETALLE). semilla=0 y las de
// civilización en 0 significan «automático»: producen ciudades, países y
// regiones — justo lo que las herramientas necesitan (ADR-005).
const DET_DEFAULTS = {
  factor: 8, semilla: 0, casquetes: 0.18, relieve: 1.2, sinuosidad: 1.0,
  temperatura: 0.0, precipitaciones: 1.0,
  semilla_civ: 0, asentamientos: 0, paises: 0, tam_paises: 0,
};

// 4 presets (ADR-005). `mar` = nivel del mar (↑ = más océano), `continentes`
// = umbral continental (↑ = masas más grandes), `plumas` = pasos ENTRE plumas
// del manto (↓ = más puntos calientes = más islas volcánicas). Resolución
// rebajada (160) para que la forja termine en un tiempo razonable.
const PRESETS = {
  continentes: {
    nombre: "Continentes", icono: "🗺️",
    desc: "Equilibrado: varias masas de tierra, mares abiertos. Lo típico.",
    gen: { resolucion: 160, tiempo: 800, mar: 0.52, continentes: 0.55, plumas: 70 },
  },
  pangea: {
    nombre: "Pangea", icono: "🌋",
    desc: "Un supercontinente que domina el planeta, rodeado de un océano único.",
    gen: {
      resolucion: 160, tiempo: 1200, mar: 0.46, continentes: 1.0,
      plumas: 160, rigidez: 0.95, deriva: 6,
    },
  },
  archipielago: {
    nombre: "Archipiélago", icono: "🏝️",
    desc: "Mares extensos salpicados de cadenas de islas volcánicas.",
    gen: {
      resolucion: 160, tiempo: 800, mar: 0.63, continentes: 0.24,
      plumas: 20, rigidez: 0.7, detalle: 0.8,
    },
  },
  sorpresa: {
    nombre: "Sorpréndeme", icono: "🎲",
    desc: "Semilla al azar y una forma de mundo al azar. A ver qué sale.",
    sorpresa: true, // se resuelve a otro preset + semilla aleatoria al forjar
  },
};
const ORDEN_PRESETS = ["continentes", "pangea", "archipielago", "sorpresa"];

// Diales avanzados de generación (todos los de PARAMS salvo la semilla, que
// tiene su propio campo). [clave, etiqueta, min, max, paso].
const DIALES_GEN = [
  ["tiempo", "Tiempo (pasos)", 50, 6000, 50],
  ["cada", "Frame cada N pasos", 1, 50, 1],
  ["ms", "ms por frame", 20, 300, 10],
  ["resolucion", "Resolución (px de alto)", 96, 512, 32],
  ["detalle", "Detalle fractal", 0, 1.5, 0.1],
  ["velocidad", "Velocidad de deriva", 2, 40, 1],
  ["mar", "Nivel del mar", 0.35, 0.7, 0.01],
  ["continentes", "Umbral continental", 0.1, 1.2, 0.05],
  ["plumas", "Pasos entre plumas", 10, 300, 10],
  ["erosion", "Erosión", 0, 0.03, 0.001],
  ["empuje", "Empuje de dorsal", 0, 0.6, 0.05],
  ["momento", "Momento de placa", 0.005, 0.2, 0.005],
  ["rigidez", "Rigidez de placa", 0, 1, 0.05],
  ["deriva", "Deriva continental", 1, 10, 0.5],
  ["anos_paso", "Escala de tiempo", 0.1, 10, 0.1],
];

// Diales avanzados del detallado (todos los de DETALLE).
const DIALES_DET = [
  ["factor", "Factor de detalle (×)", 2, 16, 2],
  ["semilla", "Semilla de detalle (0 = auto)", 0, 2147483647, 1],
  ["casquetes", "Casquetes polares", 0, 0.45, 0.01],
  ["relieve", "Relieve", 0.2, 3, 0.1],
  ["sinuosidad", "Sinuosidad de ríos", 0, 3, 0.1],
  ["temperatura", "Temperatura (−1 frío · +1 cálido)", -1, 1, 0.1],
  ["precipitaciones", "Precipitaciones (×)", 0.2, 2, 0.1],
  ["semilla_civ", "Semilla de civilización (0 = auto)", 0, 2147483647, 1],
  ["asentamientos", "Asentamientos (0 = auto)", 0, 200, 5],
  ["paises", "Países (0 = auto)", 0, 48, 1],
  ["tam_paises", "Tamaño de países (0 auto · 1 imperios · 2 reinos)", 0, 2, 1],
];

// Frases narrativas por fase (ADR-005: el costo en CPU se vuelve espectáculo).
const FRASES_1 = [
  "elevando cordilleras…", "enfriando la corteza…", "abriendo dorsales…",
  "arrastrando los continentes…", "encendiendo volcanes…", "hundiendo fosas…",
];
const FRASES_2 = [
  "esculpiendo la costa…", "trazando ríos…", "sembrando bosques…",
  "levantando ciudades…", "fundando reinos…", "dibujando fronteras…",
];

const SEMILLA_MAX = 2147483647;
const semillaAzar = () => Math.floor(Math.random() * SEMILLA_MAX);

/* =========================================================================
   Utilidades de DOM
   ========================================================================= */

// h("div.clase#id", {props}, ...hijos) — mini-constructor de elementos. Si el
// 2º argumento es nodo, texto, número o array, se toma como primer hijo.
function h(sel, props, ...hijos) {
  if (props !== null && props !== undefined &&
      (props.nodeType || Array.isArray(props) || typeof props !== "object")) {
    hijos = [props, ...hijos];
    props = null;
  }
  const m = sel.match(/^([a-z0-9]+)?(.*)$/i);
  const el = document.createElement(m[1] || "div");
  const clases = (m[2].match(/\.[^.#]+/g) || []).map((c) => c.slice(1));
  const idm = m[2].match(/#([^.#]+)/);
  if (clases.length) el.className = clases.join(" ");
  if (idm) el.id = idm[1];
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "html") el.innerHTML = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") {
        el.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (k in el && k !== "list") {
        try { el[k] = v; } catch { el.setAttribute(k, v); }
      } else el.setAttribute(k, v);
    }
  }
  for (const hijo of hijos.flat()) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo.nodeType ? hijo : document.createTextNode(String(hijo)));
  }
  return el;
}

// semilla inicial: ?semilla=<entero válido> o una al azar
function semillaInicial() {
  const s = new URLSearchParams(location.search).get("semilla");
  if (s !== null && /^[0-9]+$/.test(s.trim())) {
    const n = Number(s.trim());
    if (n >= 0 && n <= SEMILLA_MAX) return n;
  }
  return semillaAzar();
}

/* =========================================================================
   Arranque
   ========================================================================= */

const zona = document.getElementById("nuevo");
let PUEDE_GENERAR = false;

async function init() {
  montarNav({ activa: "nuevo" });
  montarPie({ lab: true });
  let c = null;
  try {
    c = await api.cuenta();
  } catch (_) {
    c = null; // sin API: se trata como no Pro (no se llama a generar)
  }
  PUEDE_GENERAR = api.esPro(c);
  pintarFormulario(semillaInicial());
  zona.removeAttribute("aria-busy");
}

/* =========================================================================
   Formulario del asistente
   ========================================================================= */

// lee el valor actual de los diales (o su default) del formulario avanzado
function leerDiales(cont, diales, defaults) {
  const out = { ...defaults };
  for (const [clave] of diales) {
    const inp = cont.querySelector(`[name="${clave}"]`);
    if (inp) out[clave] = Number(inp.value);
  }
  return out;
}

// bloque de diales (sliders con valor visible)
function bloqueDiales(diales, valores) {
  const grid = h("div.diales");
  for (const [clave, etiqueta, min, max, paso] of diales) {
    const val = valores[clave] ?? 0;
    const out = h("span.valor.mono", {}, String(val));
    const inp = h("input", {
      type: "range", name: clave, min, max, step: paso, value: val,
      onInput: (e) => { out.textContent = e.target.value; },
    });
    grid.append(h("div.dial.campo",
      h("span.campo-etiqueta", {}, h("span", {}, etiqueta), out),
      inp));
  }
  return grid;
}

function pintarFormulario(semilla) {
  let preset = "continentes";

  // --- presets ---
  const tarjetasPreset = ORDEN_PRESETS.map((clave) => {
    const p = PRESETS[clave];
    return h("button.preset", {
      type: "button", "aria-pressed": clave === preset ? "true" : "false",
      "data-preset": clave,
      onClick: () => elegirPreset(clave),
    },
      h("div.preset-icono", {}, p.icono),
      h("div.preset-nombre", {}, p.nombre),
      h("div.preset-desc", {}, p.desc));
  });
  function elegirPreset(clave) {
    preset = clave;
    for (const t of tarjetasPreset) {
      t.setAttribute("aria-pressed", t.dataset.preset === clave ? "true" : "false");
    }
    // reprellenar los diales de generación (no toca los de detalle)
    if (!PRESETS[clave].sorpresa) aplicarPresetADiales(clave);
  }
  const gridPresets = h("div.presets", { role: "group", "aria-label": "Forma del mundo" },
    ...tarjetasPreset);

  // --- semilla ---
  const inpSemilla = h("input", {
    type: "number", name: "semilla", id: "forja-semilla",
    min: 0, max: SEMILLA_MAX, step: 1, value: semilla, inputMode: "numeric",
  });
  const semillaFila = h("div.semilla-fila",
    h("div.campo",
      h("label", { htmlFor: "forja-semilla" }, "Semilla"),
      inpSemilla),
    h("button.btn.dado", {
      type: "button", "aria-label": "Semilla aleatoria", title: "Semilla aleatoria",
      onClick: () => { inpSemilla.value = semillaAzar(); },
    }, "🎲"));

  // --- ajustes avanzados (plegados) ---
  const gridGen = bloqueDiales(DIALES_GEN, { ...GEN_DEFAULTS, ...PRESETS.continentes.gen });
  const gridDet = bloqueDiales(DIALES_DET, DET_DEFAULTS);
  const avanzado = h("details.avanzado",
    h("summary", {}, "Ajustes avanzados"),
    h("div.avanzado-grupo",
      h("h4", {}, "Geología (generación)"), gridGen),
    h("div.avanzado-grupo",
      h("h4", {}, "Geografía y civilización (detallado)"), gridDet));

  function aplicarPresetADiales(clave) {
    const vals = { ...GEN_DEFAULTS, ...PRESETS[clave].gen };
    for (const [k] of DIALES_GEN) {
      const inp = gridGen.querySelector(`[name="${k}"]`);
      if (!inp) continue;
      inp.value = vals[k];
      const out = inp.parentElement.querySelector(".valor");
      if (out) out.textContent = String(vals[k]);
    }
  }

  // --- acción de forja ---
  const btnForjar = h("button.btn.btn-oro.btn-lg", { type: "button" }, "✦ Forjar mundo");
  btnForjar.addEventListener("click", () => {
    if (!PUEDE_GENERAR) return; // defensa: el muro ya lo impide
    let clave = preset;
    if (PRESETS[clave].sorpresa) {
      const opciones = ["continentes", "pangea", "archipielago"];
      clave = opciones[Math.floor(Math.random() * opciones.length)];
      inpSemilla.value = semillaAzar();
      aplicarPresetADiales(clave);
    }
    // los diales avanzados son la fuente de verdad (prellenados por el preset)
    const gen = leerDiales(gridGen, DIALES_GEN, { ...GEN_DEFAULTS, ...PRESETS[clave].gen });
    gen.semilla = Math.max(0, Math.min(SEMILLA_MAX, Math.floor(Number(inpSemilla.value) || 0)));
    const det = leerDiales(gridDet, DIALES_DET, DET_DEFAULTS);
    forjar(gen, det, PRESETS[clave].nombre, gen.semilla);
  });

  const tarjeta = h("div.tarjeta.nvo-tarjeta",
    h("p.paso-etiqueta", {}, "Elige una forma de mundo. Ajusta la semilla si quieres repetir uno."),
    gridPresets,
    semillaFila,
    avanzado,
    h("div.forja-pie",
      h("span.crece", {}, "La forja tarda unos minutos: geología primero, geografía después."),
      btnForjar));

  zona.classList.remove("nvo-bloqueado");
  zona.replaceChildren(tarjeta);

  if (!PUEDE_GENERAR) bloquear(tarjeta);
}

// Sin Pro: todo el formulario disabled + opacidad, inerte, y el muro encima.
function bloquear(tarjeta) {
  for (const el of tarjeta.querySelectorAll("input, button, select, textarea")) {
    el.disabled = true;
  }
  const resumen = tarjeta.querySelector("summary");
  if (resumen) resumen.tabIndex = -1;
  tarjeta.inert = true;
  tarjeta.setAttribute("aria-hidden", "true");
  zona.classList.add("nvo-bloqueado");
  zona.append(h("div.nvo-muro", {}, muroPro("Generar mundos propios es Pro")));
}

/* =========================================================================
   Cadena de forja: generar → detallar → ficha (ADR-005)
   ========================================================================= */

// Sustituye el formulario por el panel de progreso de dos fases.
function montarProgreso(titulo) {
  const frase = h("div.frase", {}, FRASES_1[0]);
  const faseNota = h("div.fase-nota", {}, "Fase 1 de 2 · levantando la geología");
  const relleno = h("div.relleno");
  const barra = h("div.barra-progreso.indeterminada",
    { role: "progressbar", "aria-label": "Progreso de la forja",
      "aria-valuemin": "0", "aria-valuemax": "100" }, relleno);
  const pct = h("span", {}, "0%");
  const reloj = h("span", {}, "0s");
  const chip1 = h("div.fase-chip.activa", {}, h("span.punto"), "Geología");
  const chip2 = h("div.fase-chip", {}, h("span.punto"), "Geografía");
  const zonaError = h("div.forja-error");
  const btnCancelar = h("button.btn", { type: "button" }, "Cancelar");
  const pie = h("div.forja-pie", h("span.crece"), btnCancelar);

  zona.replaceChildren(h("div.tarjeta.nvo-tarjeta", { "aria-live": "polite" },
    h("h2.forja-titulo", {}, `Forjando ${titulo}…`),
    h("div.forja-progreso",
      h("div.glifo", { html: logoSVG(40) }),
      frase, faseNota, barra,
      h("div.contador", {}, pct, reloj),
      h("div.fases", {}, chip1, chip2)),
    zonaError,
    pie));

  return { frase, faseNota, barra, relleno, pct, reloj, chip1, chip2, zonaError, btnCancelar, pie };
}

async function forjar(gen, det, tituloPreset, semilla) {
  const ui = montarProgreso(tituloPreset);
  const t0 = Date.now();
  let jobActual = null;
  let cancelado = false;
  let fase = 1;

  const relojID = setInterval(() => {
    ui.reloj.textContent = `${Math.floor((Date.now() - t0) / 1000)}s`;
  }, 1000);
  const frasesID = setInterval(() => {
    const fuente = fase === 1 ? FRASES_1 : FRASES_2;
    ui.frase.classList.add("cambiando");
    setTimeout(() => {
      ui.frase.textContent = fuente[Math.floor(Math.random() * fuente.length)];
      ui.frase.classList.remove("cambiando");
    }, 160);
  }, 3200);
  const limpiar = () => { clearInterval(relojID); clearInterval(frasesID); };
  const volverAlFormulario = () => pintarFormulario(semilla);

  // progreso 0..1 de la fase -> tramo global (fase 1: 0-50, fase 2: 50-100)
  const fijarProgreso = (p) => {
    const base = fase === 1 ? 0 : 50;
    const global = Math.round(base + Math.max(0, Math.min(1, p || 0)) * 50);
    ui.barra.classList.toggle("indeterminada", !p);
    ui.relleno.style.width = `${global}%`;
    ui.pct.textContent = `${global}%`;
    ui.barra.setAttribute("aria-valuenow", String(global));
  };

  ui.btnCancelar.addEventListener("click", async () => {
    cancelado = true;
    ui.btnCancelar.disabled = true;
    ui.btnCancelar.textContent = "Cancelando…";
    if (jobActual) { try { await api.cancelar(jobActual); } catch { /* da igual */ } }
  });

  const fallar = (msg) => {
    limpiar();
    ui.zonaError.replaceChildren(h("div.aviso.aviso-error", { role: "alert" }, msg));
    const volver = h("button.btn", { type: "button", onClick: volverAlFormulario }, "Volver");
    const reintentar = h("button.btn.btn-oro", {
      type: "button", onClick: () => forjar(gen, det, tituloPreset, semilla),
    }, "Reintentar");
    ui.pie.replaceChildren(h("span.crece"), volver, reintentar);
  };

  const cancelada = (texto) => {
    limpiar();
    volverAlFormulario();
    aviso(texto, "info");
  };

  try {
    // ---- fase 1: geología ----
    fijarProgreso(0);
    const g = await api.generar(gen);
    jobActual = g.id;
    const sello = g.sello;
    const estGen = await api.esperarTrabajo(g.id, (est) => fijarProgreso(est.progreso));
    if (cancelado || estGen.estado === "cancelado") {
      cancelada("Forja cancelada.");
      return;
    }

    const paso = await ultimoCheckpoint(sello);

    // ---- fase 2: geografía + civilización ----
    fase = 2;
    ui.chip1.classList.replace("activa", "hecha");
    ui.chip2.classList.add("activa");
    ui.faseNota.textContent = "Fase 2 de 2 · trazando la geografía";
    ui.frase.textContent = FRASES_2[0];
    fijarProgreso(0);

    const d = await api.detallar({ sello, paso, ...det });
    jobActual = d.id;
    const estDet = await api.esperarTrabajo(d.id, (est) => fijarProgreso(est.progreso));
    if (cancelado || estDet.estado === "cancelado") {
      cancelada("Forja cancelada. La geología quedó guardada.");
      return;
    }

    // ---- listo: a la ficha del mundo nuevo ----
    limpiar();
    fase = 2;
    fijarProgreso(1);
    ui.frase.textContent = "¡mundo listo!";
    const stem = stemDelEstado(estDet);
    location.href = api.urlMundo(sello, stem ? { d: stem } : undefined);
  } catch (e) {
    if (cancelado) { cancelada("Forja cancelada."); return; }
    // 403/429: api.js ya mostró el aviso con enlace a /yo#pro; no duplicar
    if (e.manejado) { limpiar(); volverAlFormulario(); return; }
    fallar(`La forja falló: ${e.message}`);
  }
}

// `paso` del ÚLTIMO frame con checkpoint de mapa_repro.json (0 si no hay).
async function ultimoCheckpoint(sello) {
  try {
    const repro = await api.repro(sello);
    const frames = (repro && repro.frames) || [];
    const conCheck = frames.filter((f) => f.checkpoint);
    if (conCheck.length) return conCheck[conCheck.length - 1].paso;
    if (frames.length) return frames[frames.length - 1].paso;
  } catch { /* sin repro: usar 0 */ }
  return 0;
}

// stem del detalle recién creado a partir del estado del job (`detalle` = url
// del png). null si no viene: la ficha resuelve entonces el detalle por defecto.
function stemDelEstado(estado) {
  if (!estado || !estado.detalle) return null;
  const base = String(estado.detalle).split("/").pop().replace(/\.png$/, "");
  return api.RE_STEM.test(base) ? base : null;
}

init();
