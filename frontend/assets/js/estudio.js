// estudio.js — galería de mundos + asistente «Forjar mundo» (ADR-005).
// Front delgado: toda la lógica pesada vive en el servidor; aquí orquestamos
// las llamadas del cliente api.js y pintamos la UI del sistema «atlas nocturno».

import { montarNav, montarPie } from "/app/js/nav.js";
import { MARCA, logoSVG } from "/app/js/marca.js";
import * as api from "/app/js/api.js";

/* =========================================================================
   Configuración: presets y diales
   ========================================================================= */

// Valores por defecto de generación (espejo de PARAMS en web.py). Cada preset
// solo sobreescribe lo que le da carácter; el resto hereda esto.
const GEN_DEFAULTS = {
  tiempo: 800, cada: 8, ms: 60, resolucion: 256, detalle: 0.6,
  velocidad: 18, mar: 0.52, continentes: 0.55, plumas: 70, erosion: 0.008,
  empuje: 0.15, momento: 0.02, rigidez: 0.85, deriva: 8, anos_paso: 1,
};

// Valores por defecto del detallado (espejo de DETALLE en web.py). semilla=0 y
// las de civilización en 0 significan «automático»: producen ciudades, países
// y regiones — justo lo que las herramientas necesitan (ADR-005).
const DET_DEFAULTS = {
  factor: 8, semilla: 0, casquetes: 0.18, relieve: 1.2, sinuosidad: 1.0,
  temperatura: 0.0, precipitaciones: 1.0,
  semilla_civ: 0, asentamientos: 0, paises: 0, tam_paises: 0,
};

// 4 presets (ADR-005). Los valores nacen del significado de los diales de
// web.py: `mar` = nivel del mar (↑ = más océano), `continentes` = umbral
// continental (↑ = masas más grandes), `plumas` = pasos ENTRE plumas del manto
// (↓ = más puntos calientes = más islas volcánicas). Se baja la resolución
// respecto al default (256) para que la forja termine en un tiempo razonable
// sin perder un mundo usable.
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
    // se resuelve a otro preset + semilla aleatoria al forjar
    sorpresa: true,
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

// Frases narrativas por fase (ADR-005: el costo en CPU se convierte en
// espectáculo).
const FRASES_1 = [
  "elevando cordilleras…", "enfriando la corteza…", "abriendo dorsales…",
  "arrastrando los continentes…", "encendiendo volcanes…", "hundiendo fosas…",
];
const FRASES_2 = [
  "esculpiendo la costa…", "trazando ríos…", "sembrando bosques…",
  "levantando ciudades…", "fundando reinos…", "dibujando fronteras…",
];

const SEMILLA_MAX = 2147483647;

/* =========================================================================
   Utilidades de DOM
   ========================================================================= */

// h("div.clase#id", {props}, ...hijos) — mini-constructor de elementos.
// El 2º argumento (props) es opcional: si es un nodo, texto, número o array,
// se interpreta como el primer hijo (no como el objeto de propiedades).
function h(sel, props, ...hijos) {
  if (props !== null && props !== undefined &&
      (props.nodeType || Array.isArray(props) || typeof props !== "object")) {
    hijos = [props, ...hijos];
    props = null;
  }
  const m = sel.match(/^([a-z0-9]+)?(.*)$/i);
  const tag = m[1] || "div";
  const el = document.createElement(tag);
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

/* =========================================================================
   Avisos (toasts) no intrusivos
   ========================================================================= */

function contenedorAvisos() {
  let c = document.querySelector(".avisos");
  if (!c) {
    c = h("div.avisos", { "aria-live": "polite", "aria-atomic": "false" });
    document.body.append(c);
  }
  return c;
}

function aviso(mensaje, tipo = "info", ms = 4200) {
  const el = h(`div.aviso.aviso-${tipo}`, { role: "status" }, mensaje);
  contenedorAvisos().append(el);
  const quitar = () => {
    el.classList.add("saliendo");
    setTimeout(() => el.remove(), 300);
  };
  const t = setTimeout(quitar, ms);
  el.addEventListener("click", () => { clearTimeout(t); quitar(); });
  return el;
}

/* =========================================================================
   Modelo de datos: qué es un «mundo usable»
   ========================================================================= */

// Un detalle es un mundo abrible por las herramientas si trae los archivos que
// fantasia_srv / batalla_srv / juego_srv exigen para cargar:
//   fantasía  → _capas.json + _datos2.png
//   batalla   → _capas.json + _datos.png + _datos2.png
//   juego     → _capas.json + _regiones.png
// La unión (lo que hace que TODOS los botones de la tarjeta funcionen) es:
const CLAVES_USABLES = ["capas", "datos", "datos2", "regiones"];
function esUsable(det) {
  return CLAVES_USABLES.every((k) => k in det && det[k]);
}

// stem del detalle a partir de la URL de su PNG: .../<stem>.png
function stemDe(det) {
  if (!det || !det.png) return null;
  const base = det.png.split("/").pop().replace(/\.png$/, "");
  return api.RE_STEM.test(base) ? base : null;
}

function fmtFecha(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  return d.toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" });
}

// Nombre legible y ÚNICO de un mundo: se sintetiza determinísticamente a
// partir del identificador (stem del detalle, o sello de la corrida), de modo
// que dos mundos distintos nunca compartan nombre aunque compartan semilla.
const SIL_INI = ["Val", "Mor", "Thal", "Ker", "Ael", "Dun", "Bra", "Isla", "Or", "Vey", "Cal", "Nym", "Ther", "Gal", "Rho", "Zan"];
const SIL_MED = ["do", "ra", "ve", "mi", "sha", "lu", "ta", "ri", "go", "en", "ka", "so", "dre", "va", "ni", "or"];
const SIL_FIN = ["ria", "gard", "mar", "thia", "dor", "heim", "una", "eth", "os", "ara", "wyn", "il", "onte", "ath", "ur", "ia"];

function nombreMundo(corrida, det) {
  const clave = stemDe(det) || corrida?.sello || "";
  let h = 0;
  for (const c of clave) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  if (!clave) return `Mundo del ${fmtFecha(det?.creado || corrida?.creado)}`;
  return SIL_INI[h % 16] + SIL_MED[(h >>> 4) % 16] + SIL_FIN[(h >>> 8) % 16];
}

// ¿Es un mundo «propio con semilla» (elegible para insignias Pro informativas,
// ADR-007)? Cualquier corrida con semilla explícita lo es en la beta.
function tieneSemillaPropia(corrida) {
  return corrida?.params?.semilla !== undefined && corrida.params.semilla !== null;
}

/* =========================================================================
   Estado y arranque
   ========================================================================= */

const refs = {};
let CORRIDAS = [];

function init() {
  montarNav("estudio");
  montarPie({ lab: true });
  refs.galeria = document.getElementById("galeria");
  refs.seccionGaleria = document.getElementById("seccion-galeria");
  refs.seccionMedio = document.getElementById("seccion-medio");
  refs.galeriaMedio = document.getElementById("galeria-medio");
  document.getElementById("btn-forjar")
    .addEventListener("click", () => abrirForja());
  cargar();
}

/* =========================================================================
   Carga y pintado de la galería
   ========================================================================= */

function esqueletos(n = 6) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) {
    frag.append(h("div.tarjeta.mundo.esq-mundo", { "aria-hidden": "true" },
      h("div.esqueleto.esq-lienzo"),
      h("div.esq-txt",
        h("div.esqueleto.esqueleto-titulo"),
        h("div.esqueleto.esqueleto-texto"),
        h("div.esqueleto.esqueleto-texto", { style: "width:40%" }))));
  }
  return frag;
}

async function cargar() {
  refs.seccionGaleria.setAttribute("aria-busy", "true");
  refs.galeria.replaceChildren(esqueletos());
  try {
    CORRIDAS = await api.corridas();
    pintar();
  } catch (e) {
    refs.galeria.replaceChildren(
      h("div.aviso.aviso-error", { role: "alert", style: "position:static" },
        `No se pudieron cargar tus mundos: ${e.message}. `,
        h("button.btn.btn-sm", { type: "button", onClick: cargar }, "Reintentar")));
  } finally {
    refs.seccionGaleria.setAttribute("aria-busy", "false");
  }
}

function pintar() {
  // mundos usables: un item por detalle usable
  const usables = [];
  for (const c of CORRIDAS) {
    for (const d of (c.detalles || [])) {
      if (esUsable(d) && stemDe(d)) usables.push([c, d]);
    }
  }
  // corridas «a medio forjar»: tienen mundo de checkpoints (extrapolable) pero
  // ningún detalle usable — se pueden terminar de forjar
  const medio = CORRIDAS.filter(
    (c) => c.extrapolable && !(c.detalles || []).some((d) => esUsable(d)));

  if (!usables.length) {
    refs.galeria.replaceChildren(estadoVacio());
  } else {
    refs.galeria.replaceChildren(
      ...usables.map(([c, d]) => tarjetaMundo(c, d)));
  }

  if (medio.length) {
    refs.seccionMedio.classList.remove("oculto");
    refs.galeriaMedio.replaceChildren(...medio.map(tarjetaMedio));
  } else {
    refs.seccionMedio.classList.add("oculto");
    refs.galeriaMedio.replaceChildren();
  }
}

function estadoVacio() {
  return h("div.vacio",
    h("div.logo-grande", { html: logoSVG(72) }),
    h("h2", {}, "Aún no has forjado ningún mundo"),
    h("p", {}, `Empieza con un preset, deja que ${MARCA.nombre} levante la ` +
      "geología y la geografía, y ábrelo como tu primer mapa."),
    h("button.btn.btn-oro.btn-lg",
      { type: "button", onClick: () => abrirForja() }, "✦ Forjar mi primer mundo"));
}

// Imagen con carga perezosa y desvanecido al llegar.
function miniatura(det, corrida, alt) {
  const src = (det && det.png) || corrida.png || "";
  const img = h("img", { loading: "lazy", decoding: "async", alt, src });
  img.addEventListener("load", () => img.classList.add("cargada"));
  img.addEventListener("error", () => {
    if (corrida.png && img.src.indexOf(corrida.png) < 0) img.src = corrida.png; // fallback
    else img.classList.add("cargada");
  });
  return h("div.mundo-lienzo", {}, img);
}

function tarjetaMundo(corrida, det) {
  const stem = stemDe(det);
  const sello = corrida.sello;
  const nombre = nombreMundo(corrida, det);
  const q = `sello=${encodeURIComponent(sello)}&d=${encodeURIComponent(stem)}`;

  const insignias = [];
  if (tieneSemillaPropia(corrida)) {
    insignias.push(h("span.insignia.insignia-pro",
      { title: "Ventaja Pro (informativa): calidad 4×, export 8K" }, "Pro"));
  }
  if (det.climahd) insignias.push(h("span.insignia.insignia-mar", {}, "HD"));

  const lienzo = miniatura(det, corrida, `Miniatura de ${nombre}`);
  if (insignias.length) {
    lienzo.append(h("div.mundo-insignias", {}, ...insignias));
  }

  // menú secundario (details/summary nativo)
  const menu = h("details.menu",
    h("summary", { "aria-label": "Más acciones", title: "Más acciones" }, "⋯"),
    h("div.menu-lista", { role: "menu" },
      h("a.menu-item", { role: "menuitem", href: `/estudio/mundo?${q}&modo=conquistar` }, "⚔ Conquistar"),
      h("button.menu-item.peligro",
        { type: "button", role: "menuitem", onClick: () => confirmarBorrar(corrida) },
        "🗑 Eliminar mundo")));
  // cerrar el menú al hacer clic fuera / al elegir una opción
  menu.addEventListener("toggle", () => {
    if (!menu.open) return;
    const fuera = (ev) => {
      if (!menu.contains(ev.target)) { menu.open = false; document.removeEventListener("click", fuera); }
    };
    setTimeout(() => document.addEventListener("click", fuera), 0);
  });

  return h("article.tarjeta.mundo.tarjeta-activable", { role: "listitem" },
    lienzo,
    h("div.mundo-cuerpo",
      h("h3.mundo-titulo", {}, nombre),
      h("div.mundo-meta",
        h("span", {}, fmtFecha(det.creado || corrida.creado)),
        det.resolucion ? h("span.mono", {}, `${det.resolucion[0]}×${det.resolucion[1]}`) : null),
      h("div.mundo-acciones",
        h("a.btn.btn-oro.abrir", { href: `/estudio/mundo?${q}` }, "Abrir"),
        menu)));
}

function tarjetaMedio(corrida) {
  return h("article.tarjeta.mundo", { role: "listitem" },
    miniatura(null, corrida, `Geología de ${nombreMundo(corrida, null)}`),
    h("div.mundo-cuerpo",
      h("h3.mundo-titulo", {}, nombreMundo(corrida, null)),
      h("div.mundo-meta",
        h("span", {}, fmtFecha(corrida.creado)),
        h("span", {}, "sin geografía")),
      h("div.mundo-acciones",
        h("button.btn.btn-oro.abrir",
          { type: "button", onClick: () => terminarForja(corrida) },
          "Terminar de forjar"))));
}

/* =========================================================================
   Borrado de corrida (con confirmación en modal)
   ========================================================================= */

function confirmarBorrar(corrida) {
  const dlg = h("dialog.modal.confirmar");
  const cerrar = () => { dlg.close(); dlg.remove(); };
  const nMundos = (corrida.detalles || []).filter(esUsable).length;
  const btnBorrar = h("button.btn.btn-peligro", { type: "button" }, "Eliminar mundo");

  dlg.append(
    h("div.modal-cabecera",
      h("h3", {}, "¿Eliminar este mundo?"),
      h("button.modal-cerrar", { type: "button", "aria-label": "Cerrar", onClick: cerrar }, "×")),
    h("div.confirmar-cuerpo",
      h("p", {}, "Vas a borrar la corrida ",
        h("strong", {}, nombreMundo(corrida, (corrida.detalles || [])[0])),
        nMundos > 1
          ? ` y todos sus ${nMundos} mundos detallados.`
          : " y todo su contenido detallado."),
      h("p", {}, "Esta acción borra la corrida entera del disco y no se puede deshacer."),
      h("div.confirmar-acciones",
        h("button.btn", { type: "button", onClick: cerrar }, "Cancelar"),
        btnBorrar)));

  btnBorrar.addEventListener("click", async () => {
    btnBorrar.disabled = true;
    btnBorrar.textContent = "Eliminando…";
    try {
      CORRIDAS = await api.borrarCorrida(corrida.sello);
      cerrar();
      pintar();
      aviso("Mundo eliminado.", "ok");
    } catch (e) {
      btnBorrar.disabled = false;
      btnBorrar.textContent = "Eliminar mundo";
      aviso(`No se pudo eliminar: ${e.message}`, "error");
    }
  });

  dlg.addEventListener("cancel", (e) => { e.preventDefault(); cerrar(); });
  document.body.append(dlg);
  dlg.showModal();
}

/* =========================================================================
   Asistente «Forjar mundo»
   ========================================================================= */

// lee el valor actual de un dial (o su default) desde el formulario avanzado
function leerDiales(form, diales, defaults) {
  const out = { ...defaults };
  for (const [clave] of diales) {
    const inp = form.querySelector(`[name="${clave}"]`);
    if (inp) out[clave] = Number(inp.value);
  }
  return out;
}

// construye un bloque de diales (sliders con valor visible)
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

function abrirForja() {
  const dlg = h("dialog.modal.forja");
  let preset = "continentes"; // default
  const cerrar = () => { dlg.close(); dlg.remove(); };

  // --- selección de preset ---
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
    // reprellenar diales de generación con los del preset (no toca los de detalle)
    if (!PRESETS[clave].sorpresa) aplicarPresetADiales(clave);
  }
  const gridPresets = h("div.presets", { role: "group", "aria-label": "Forma del mundo" },
    ...tarjetasPreset);

  // --- semilla ---
  const inpSemilla = h("input", {
    type: "number", name: "semilla", id: "forja-semilla",
    min: 0, max: SEMILLA_MAX, step: 1,
    value: GEN_DEFAULTS.semilla, inputmode: "numeric",
  });
  const semillaFila = h("div.semilla-fila",
    h("div.campo",
      h("label", { htmlFor: "forja-semilla" }, "Semilla"),
      inpSemilla),
    h("button.btn.dado", {
      type: "button", "aria-label": "Semilla aleatoria", title: "Semilla aleatoria",
      onClick: () => { inpSemilla.value = Math.floor(Math.random() * SEMILLA_MAX); },
    }, "🎲"));

  // --- acordeón de ajustes avanzados ---
  const gridGen = bloqueDiales(DIALES_GEN, { ...GEN_DEFAULTS, ...PRESETS.continentes.gen });
  const gridDet = bloqueDiales(DIALES_DET, DET_DEFAULTS);
  const avanzado = h("details.avanzado",
    h("summary", {}, "Ajustes avanzados"),
    h("div.avanzado-grupo",
      h("h4", {}, "Geología (generación)"), gridGen),
    h("div.avanzado-grupo",
      h("h4", {}, "Geografía y civilización (detallado)"), gridDet));

  // reaplica los diales de generación de un preset al formulario avanzado
  function aplicarPresetADiales(clave) {
    const vals = { ...GEN_DEFAULTS, ...PRESETS[clave].gen };
    for (const [k] of DIALES_GEN) {
      const inp = gridGen.querySelector(`[name="${k}"]`);
      if (inp) {
        inp.value = vals[k];
        const out = inp.parentElement.querySelector(".valor");
        if (out) out.textContent = String(vals[k]);
      }
    }
  }

  // --- pie con acción de forja ---
  const btnForjar = h("button.btn.btn-oro.btn-lg", { type: "button" }, "✦ Forjar mundo");
  btnForjar.addEventListener("click", () => {
    // resolver preset (sorpresa → uno real + semilla aleatoria)
    let clave = preset;
    if (PRESETS[clave].sorpresa) {
      const opciones = ["continentes", "pangea", "archipielago"];
      clave = opciones[Math.floor(Math.random() * opciones.length)];
      inpSemilla.value = Math.floor(Math.random() * SEMILLA_MAX);
      aplicarPresetADiales(clave);
    }
    // los diales avanzados son la fuente de verdad (ya prellenados por el preset)
    const gen = leerDiales(gridGen, DIALES_GEN, { ...GEN_DEFAULTS, ...PRESETS[clave].gen });
    gen.semilla = Math.max(0, Math.min(SEMILLA_MAX, Number(inpSemilla.value) || 0));
    const det = leerDiales(gridDet, DIALES_DET, DET_DEFAULTS);
    // conmutar el modal a modo progreso y arrancar la cadena
    forjar(dlg, gen, det, PRESETS[clave].nombre);
  });

  dlg.append(
    h("div.modal-cabecera",
      h("h3.forja-titulo", {}, h("span", { html: logoSVG(24) }), "Forjar mundo"),
      h("button.modal-cerrar", { type: "button", "aria-label": "Cerrar", onClick: cerrar }, "×")),
    h("p.paso-etiqueta", {}, "Elige una forma de mundo. Ajusta la semilla si quieres repetir uno."),
    gridPresets,
    semillaFila,
    avanzado,
    h("div.forja-pie",
      h("span.crece", {}, "La forja tarda unos minutos: geología primero, geografía después."),
      btnForjar));

  dlg.addEventListener("cancel", (e) => { e.preventDefault(); cerrar(); });
  document.body.append(dlg);
  dlg.showModal();
}

/* =========================================================================
   Cadena de forja: generar → detallar → abrir (ADR-005)
   ========================================================================= */

// Convierte el contenido del modal en un panel de progreso de dos fases.
function montarProgreso(dlg, titulo) {
  const frase = h("div.frase", {}, FRASES_1[0]);
  const faseNota = h("div.fase-nota", {}, "Fase 1 de 2 · levantando la geología");
  const relleno = h("div.relleno");
  const barra = h("div.barra-progreso.indeterminada", { role: "progressbar", "aria-label": "Progreso de la forja" }, relleno);
  const pct = h("span", {}, "0%");
  const reloj = h("span", {}, "0s");
  const chip1 = h("div.fase-chip.activa", {}, h("span.punto"), "Geología");
  const chip2 = h("div.fase-chip", {}, h("span.punto"), "Geografía");
  const zonaError = h("div.forja-error");
  const btnCancelar = h("button.btn", { type: "button" }, "Cancelar");

  dlg.replaceChildren(
    h("div.modal-cabecera",
      h("h3", {}, `Forjando ${titulo}…`)),
    h("div.forja-progreso",
      h("div.glifo", {}, "✦"),
      frase, faseNota, barra,
      h("div.contador", {}, pct, reloj),
      h("div.fases", {}, chip1, chip2)),
    zonaError,
    h("div.forja-pie", h("span.crece"), btnCancelar));

  return { frase, faseNota, barra, relleno, pct, reloj, chip1, chip2, zonaError, btnCancelar };
}

async function forjar(dlg, gen, det, tituloPreset) {
  const ui = montarProgreso(dlg, tituloPreset);
  const t0 = Date.now();
  let jobActual = null;
  let cancelado = false;
  let fase = 1;

  // reloj
  const relojID = setInterval(() => {
    ui.reloj.textContent = `${Math.floor((Date.now() - t0) / 1000)}s`;
  }, 1000);
  // frases rotando
  const frasesID = setInterval(() => {
    const fuente = fase === 1 ? FRASES_1 : FRASES_2;
    ui.frase.classList.add("cambiando");
    setTimeout(() => {
      ui.frase.textContent = fuente[Math.floor(Math.random() * fuente.length)];
      ui.frase.classList.remove("cambiando");
    }, 160);
  }, 3200);

  const limpiar = () => { clearInterval(relojID); clearInterval(frasesID); };

  // mapea el progreso 0..1 de una fase al tramo global (fase1: 0-50, fase2: 50-100)
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
    ui.zonaError.replaceChildren(
      h("div.aviso.aviso-error", { role: "alert" }, msg));
    ui.btnCancelar.textContent = "Cerrar";
    ui.btnCancelar.disabled = false;
    ui.btnCancelar.onclick = () => { dlg.close(); dlg.remove(); };
    // botón de reintento: relanza el asistente con los mismos valores
    const reintentar = h("button.btn.btn-oro", { type: "button" }, "Reintentar");
    reintentar.addEventListener("click", () => forjar(dlg, gen, det, tituloPreset));
    dlg.querySelector(".forja-pie").prepend(reintentar);
  };

  try {
    // ---- Fase 1: generar geología ----
    fijarProgreso(0);
    const g = await api.generar(gen);
    jobActual = g.id;
    const sello = g.sello;
    const estGen = await api.esperarTrabajo(g.id, (est) => fijarProgreso(est.progreso));
    if (cancelado || estGen.estado === "cancelado") {
      limpiar(); dlg.close(); dlg.remove();
      aviso("Forja cancelada.", "info");
      return;
    }

    // ---- elegir el último checkpoint del reproductor ----
    const paso = await ultimoCheckpoint(sello);

    // ---- Fase 2: detallar geografía + civilización ----
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
      limpiar(); dlg.close(); dlg.remove();
      aviso("Forja cancelada. La geología quedó guardada en «a medio forjar».", "info");
      cargar();
      return;
    }

    // ---- localizar el stem del detalle nuevo y abrir ----
    const stem = await stemDelDetalle(sello, estDet);
    limpiar();
    if (!stem) {
      dlg.close(); dlg.remove();
      aviso("Mundo forjado, pero no pude abrirlo automáticamente. Está en tu galería.", "info");
      cargar();
      return;
    }
    fijarProgreso(1);
    ui.frase.textContent = "¡mundo listo!";
    dlg.close(); dlg.remove();
    location.href = `/estudio/mundo?sello=${encodeURIComponent(sello)}&d=${encodeURIComponent(stem)}`;
  } catch (e) {
    if (cancelado) {
      limpiar(); dlg.close(); dlg.remove();
      aviso("Forja cancelada.", "info");
      return;
    }
    // 403/429: api.js ya mostró el aviso con enlace a /cuenta; cerrar el
    // asistente sin duplicar el mensaje (el gating es del servidor, ADR-007).
    if (e.manejado) { limpiar(); dlg.close(); dlg.remove(); return; }
    fallar(`La forja falló: ${e.message}`);
  }
}

// Lee mapa_repro.json y devuelve el `paso` del ÚLTIMO frame con checkpoint.
async function ultimoCheckpoint(sello) {
  try {
    const repro = await api.repro(sello);
    const frames = (repro && repro.frames) || [];
    const conCheck = frames.filter((f) => f.checkpoint);
    if (conCheck.length) return conCheck[conCheck.length - 1].paso;
    if (frames.length) return frames[frames.length - 1].paso; // fallback
  } catch { /* sin repro: usar 0 */ }
  return 0;
}

// Obtiene el stem del detalle recién creado: primero del estado del job (trae
// `detalle` = url del png), y si no, refrescando corridas y buscando el más
// reciente del sello.
async function stemDelDetalle(sello, estado) {
  if (estado && estado.detalle) {
    const base = estado.detalle.split("/").pop().replace(/\.png$/, "");
    if (api.RE_STEM.test(base)) return base;
  }
  // fallback: recargar y buscar el detalle usable más reciente de esta corrida
  try {
    CORRIDAS = await api.corridas();
    pintar();
    const c = CORRIDAS.find((x) => x.sello === sello);
    const det = (c?.detalles || []).find((d) => esUsable(d) && stemDe(d))
      || (c?.detalles || []).find((d) => stemDe(d));
    return det ? stemDe(det) : null;
  } catch { return null; }
}

/* =========================================================================
   «Terminar de forjar»: solo la fase de detallado sobre una corrida existente
   ========================================================================= */

async function terminarForja(corrida) {
  const dlg = h("dialog.modal.forja");
  dlg.addEventListener("cancel", (e) => e.preventDefault());
  document.body.append(dlg);
  dlg.showModal();

  const ui = montarProgreso(dlg, nombreMundo(corrida, null));
  // esta variante arranca directamente en fase 2
  ui.chip1.classList.replace("activa", "hecha");
  ui.chip1.classList.add("hecha");
  ui.chip2.classList.add("activa");
  ui.faseNota.textContent = "Trazando la geografía sobre la geología existente";
  ui.frase.textContent = FRASES_2[0];

  const t0 = Date.now();
  let jobActual = null;
  let cancelado = false;
  const relojID = setInterval(() => {
    ui.reloj.textContent = `${Math.floor((Date.now() - t0) / 1000)}s`;
  }, 1000);
  const frasesID = setInterval(() => {
    ui.frase.classList.add("cambiando");
    setTimeout(() => {
      ui.frase.textContent = FRASES_2[Math.floor(Math.random() * FRASES_2.length)];
      ui.frase.classList.remove("cambiando");
    }, 160);
  }, 3200);
  const limpiar = () => { clearInterval(relojID); clearInterval(frasesID); };
  const fijar = (p) => {
    const g = Math.round(Math.max(0, Math.min(1, p || 0)) * 100);
    ui.barra.classList.toggle("indeterminada", !p);
    ui.relleno.style.width = `${g}%`;
    ui.pct.textContent = `${g}%`;
  };

  ui.btnCancelar.addEventListener("click", async () => {
    cancelado = true;
    ui.btnCancelar.disabled = true;
    ui.btnCancelar.textContent = "Cancelando…";
    if (jobActual) { try { await api.cancelar(jobActual); } catch { /* */ } }
  });

  try {
    fijar(0);
    const paso = await ultimoCheckpoint(corrida.sello);
    const d = await api.detallar({ sello: corrida.sello, paso, ...DET_DEFAULTS });
    jobActual = d.id;
    const est = await api.esperarTrabajo(d.id, (e) => fijar(e.progreso));
    limpiar();
    if (cancelado || est.estado === "cancelado") {
      dlg.close(); dlg.remove();
      aviso("Forja cancelada.", "info");
      cargar();
      return;
    }
    const stem = await stemDelDetalle(corrida.sello, est);
    dlg.close(); dlg.remove();
    if (stem) {
      location.href = `/estudio/mundo?sello=${encodeURIComponent(corrida.sello)}&d=${encodeURIComponent(stem)}`;
    } else {
      aviso("Mundo terminado. Está en tu galería.", "ok");
      cargar();
    }
  } catch (e) {
    limpiar();
    if (cancelado) { dlg.close(); dlg.remove(); aviso("Forja cancelada.", "info"); return; }
    if (e.manejado) { dlg.close(); dlg.remove(); return; } // 403/429 ya avisado
    ui.zonaError.replaceChildren(h("div.aviso.aviso-error", { role: "alert" }, `Falló: ${e.message}`));
    ui.btnCancelar.textContent = "Cerrar";
    ui.btnCancelar.disabled = false;
    ui.btnCancelar.onclick = () => { dlg.close(); dlg.remove(); };
  }
}

/* =========================================================================
   Arranque
   ========================================================================= */
init();
