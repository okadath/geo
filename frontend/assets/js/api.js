// api.js — cliente de la API de web.py + módulos *_srv.
// NO inventa endpoints: cada función corresponde a una ruta ya servida por el
// back (servidor/rutas_*.py, fantasia_srv.py, batalla_srv.py). El front es
// visor delgado; la lógica propietaria vive en el servidor.
//
// API PÚBLICA (resumen; detalle junto a cada función)
// Las funciones de datos devuelven Promise y, si el servidor responde !ok,
// rechazan con Error{message: <campo error del JSON>, status: <HTTP>}.
//
//   Mundos (servidor/rutas_mundos.py)
//     mundo(sello, d?)             -> ficha {sello, nombre, d, meta, publico,
//                                     dueno, es_dueno, imagen, lugares[]}
//     mundos({orden, q, n}?)       -> [{sello, nombre, d, semilla, creado, imagen}]
//     mundoDia(desde?)             -> ficha (igual que mundo())
//     visibilidad(sello, publico)  -> {sello, publico}
//   Cuenta (servidor/rutas_cuentas.py)
//     cuenta({fresca}?)            -> {plan, limites, uso, email?, expira?,
//                                     plan_contratado?, anonimo?, guardados_n,
//                                     mundos_propios[]}   (memoizada)
//     esPro(c)                     -> bool (plan vigente pro|comercial)
//     conSesion(c)                 -> bool (hay email y no es anónimo)
//     pedirEnlace(email, volver?)  -> {ok, modo: "smtp"|"dev"}
//     salir()                      -> {ok}
//     guardados()                  -> [{tipo, sello, x, y, query, creado}]
//     guardar(item)                -> {ok, nuevo, guardado}
//     quitarGuardado(item)         -> {ok, borrado}
//   URLs de página (string, sin petición)
//     urlMundo(sello, q?)  urlMapa(sello, q?)  urlJugar(sello, q?)
//     urlBattlemap(sello, x, y, q?)   aQuery(q) -> "a=1&b=2" (sin "?")
//   Resto (anterior): corridas, generar, estado, detallar, extrapolar,
//     cancelar, borrarCorrida, esperarTrabajo, capas, repro, urlFantasia*,
//     urlBatallaMapa, batalla*, rotulos, guardarRotulos, avisarLimite.

// ---- validadores de identidad (espejo de RE_SELLO/RE_STEM del servidor) ----
export const RE_SELLO = /^[0-9]{8}-[0-9]{6}(-[0-9]+)?$/;
export const RE_STEM = /^d[0-9]{6}_f[0-9]+_[0-9a-f]{6}$/;

// ---- utilidades internas ----------------------------------------------------

// Construye "?a=1&b=2" a partir de un objeto, omitiendo null/undefined/"".
function _qs(params) {
  if (!params) return "";
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    u.append(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

// Lanza Error con el mensaje {error} del JSON del servidor si !res.ok.
// Para 403 (requiere plan) y 429 (limite), ademas muestra un aviso no intrusivo
// con enlace a /yo y marca el Error como `.manejado` para que el llamador
// no duplique el mensaje. El gating es SIEMPRE del servidor (ADR-007): aqui solo
// se reacciona a lo que el servidor niega, nunca se bloquea nada en JS.
// avisar=false omite ese aviso (endpoints de cuenta/mundos, donde 403/429 no
// significan «límite de plan» y el llamador pinta su propio mensaje).
async function _revisar(res, avisar = true) {
  if (res.ok) return res;
  let msg = `HTTP ${res.status}`;
  try {
    const j = await res.json();
    if (j && j.error) msg = j.error;
  } catch (_) {
    /* respuesta no-JSON: se queda el "HTTP N" */
  }
  const err = new Error(msg);
  err.status = res.status;
  if (avisar && (res.status === 403 || res.status === 429)) {
    err.manejado = true;
    avisarLimite(res.status, msg);
  }
  throw err;
}

// avisarLimite(status, mensaje) — banner/toast efímero del estilo de ui.js
// (clases .avisos/.aviso de base.css) con enlace a /yo (403 -> /yo#pro). Autocontenido para
// funcionar en cualquier página sin importar ui.js. Exportado por si mundo.js
// necesita señalar un límite de una imagen que no pasa por _revisar.
export function avisarLimite(status, mensaje) {
  let caja = document.querySelector(".avisos");
  if (!caja) {
    caja = document.createElement("div");
    caja.className = "avisos";
    document.body.appendChild(caja);
  }
  const cta = status === 403
    ? "Este mundo necesita un plan Pro."
    : "Alcanzaste el límite de renders por ahora.";
  const el = document.createElement("div");
  el.className = "aviso aviso-info";
  el.setAttribute("role", "status");
  el.innerHTML =
    `<span>${mensaje && mensaje !== `HTTP ${status}` ? mensaje : cta} ` +
    `<a href="${status === 403 ? "/yo#pro" : "/yo"}">` +
    `${status === 403 ? "Ver planes" : "Ver mi cuenta"}</a></span>`;
  caja.appendChild(el);
  const quitar = () => {
    el.classList.add("saliendo");
    setTimeout(() => el.remove(), 300);
  };
  setTimeout(quitar, 7000);
  el.addEventListener("click", (e) => {
    if (e.target.tagName !== "A") quitar();
  });
}

async function _getJSON(url, avisar = true) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  await _revisar(res, avisar);
  return res.json();
}

async function _postJSON(url, cuerpo, avisar = true, metodo = "POST") {
  const res = await fetch(url, {
    method: metodo,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(cuerpo || {}),
  });
  await _revisar(res, avisar);
  return res.json();
}

// ---- corridas y generación (web.py) ----------------------------------------

// GET /api/corridas -> lista de descriptores de corrida (sello, params,
// urls de imágenes, detalles[]).
export function corridas() {
  return _getJSON("/api/corridas");
}

// POST /api/generar {tiempo,cada,ms,semilla,resolucion,detalle,...ALGORITMO}
// -> {id, params, sello}. Los valores fuera de rango los acota el servidor.
export function generar(params) {
  return _postJSON("/api/generar", params);
}

// GET /api/estado?id=<job_id> -> estado vivo del trabajo
// {estado:"corriendo"|"listo"|"error"|"cancelado", progreso, ...}.
export function estado(id) {
  return _getJSON(`/api/estado${_qs({ id })}`);
}

// POST /api/detallar {sello, paso, factor, semilla, casquetes, relieve,
//   sinuosidad, temperatura, precipitaciones, semilla_civ, asentamientos,
//   paises, tam_paises} -> {id, params}.
export function detallar(params) {
  return _postJSON("/api/detallar", params);
}

// POST /api/extrapolar {sello, paso, pasos} -> {id, sello}. Rama no destructiva.
export function extrapolar(params) {
  return _postJSON("/api/extrapolar", params);
}

// POST /api/cancelar {id} -> {ok}.
export function cancelar(id) {
  return _postJSON("/api/cancelar", { id });
}

// POST /api/corridas/borrar {sello} -> lista de corridas actualizada.
export function borrarCorrida(sello) {
  return _postJSON("/api/corridas/borrar", { sello });
}

// Helper de polling: consulta /api/estado cada 1.5 s hasta que el trabajo
// llegue a listo/error/cancelado. Llama alProgresar(est) en cada sondeo.
// Devuelve el estado final; lanza Error si terminó en "error".
export function esperarTrabajo(id, alProgresar, intervalo = 1500) {
  return new Promise((resolve, reject) => {
    const tic = async () => {
      try {
        const est = await estado(id);
        if (typeof alProgresar === "function") alProgresar(est);
        if (est.estado === "listo" || est.estado === "cancelado") {
          resolve(est);
        } else if (est.estado === "error") {
          reject(new Error(est.log || "el trabajo terminó con error"));
        } else {
          setTimeout(tic, intervalo);
        }
      } catch (e) {
        reject(e);
      }
    };
    tic();
  });
}

// ---- JSON de datos por corrida/detalle -------------------------------------

// _capas.json de un detalle: vectores/leyendas (ríos, países, asentamientos,
// resolución nx/ny) compartidos por fantasía y battlemap.
export function capas(sello, d) {
  return _getJSON(`/salidas/${sello}/detalles/${d}_capas.json`);
}

// mapa_repro.json de una corrida: timeline de checkpoints del reproductor.
export function repro(sello) {
  return _getJSON(`/salidas/${sello}/mapa_repro.json`);
}

// ---- builders de URL de imagen (fantasía) ----------------------------------
// Devuelven string (para <img src> o descargas). q = query params extra
// (calidad, semilla, paleta, capas, deco, px, cx, cy, w, h, z, paises,
//  npaises, fspais, fsciu). El sello/d se anteponen siempre.

// GET /api/fantasia/render — mapa completo a resolución de trabajo.
export function urlFantasiaRender(sello, d, q) {
  return `/api/fantasia/render${_qs({ sello, d, ...q })}`;
}

// GET /api/fantasia/sector — ventana de mundo re-horneada (nítida a zoom).
export function urlFantasiaSector(sello, d, q) {
  return `/api/fantasia/sector${_qs({ sello, d, ...q })}`;
}

// GET /api/fantasia/deco — capa decorativa de una ventana (sin rótulos).
export function urlFantasiaDeco(sello, d, q) {
  return `/api/fantasia/deco${_qs({ sello, d, ...q })}`;
}

// ---- builder de URL de imagen (battlemap) ----------------------------------

// GET /api/batalla/mapa — PNG de la escena de encuentro. q: rx, ry, tema, sub,
// cols, rows, semilla, px, rejilla, nums, momento, estacion.
export function urlBatallaMapa(sello, d, q) {
  return `/api/batalla/mapa${_qs({ sello, d, ...q })}`;
}

// ---- JSON de battlemap (batalla_srv) ---------------------------------------

// GET /api/batalla/info?sello&d -> {resolucion:[nx,ny], sub_auto, temas[]}.
export function batallaInfo(sello, d) {
  return _getJSON(`/api/batalla/info${_qs({ sello, d })}`);
}

// GET /api/batalla/lugar?sello&d&rx&ry -> ficha del punto (bioma, río, tema...).
export function batallaLugar(sello, d, rx, ry) {
  return _getJSON(`/api/batalla/lugar${_qs({ sello, d, rx, ry })}`);
}

// GET /api/batalla/escena?sello&d&... -> {tema, sub, titulo, momento, ...}.
// q: rx, ry, tema, sub, semilla, cols, rows, momento, estacion.
export function batallaEscena(sello, d, q) {
  return _getJSON(`/api/batalla/escena${_qs({ sello, d, ...q })}`);
}

// GET /api/batalla/vtt?sello&d&...&formato=foundry|roll20 -> manifiesto VTT.
export function batallaVTT(sello, d, q) {
  return _getJSON(`/api/batalla/vtt${_qs({ sello, d, ...q })}`);
}

// ---- rótulos editables (fantasia_srv) --------------------------------------

// GET /api/fantasia/rotulos?sello&d -> {rotulos:[{tipo,id,nombre,override?}]}.
export function rotulos(sello, d) {
  return _getJSON(`/api/fantasia/rotulos${_qs({ sello, d })}`);
}

// POST /api/fantasia/rotulos {sello, d, overrides:{id:{nombre?,oculto?}}}
// -> {ok, n, overrides}. Un mapa vacío restaura todos los rótulos.
export function guardarRotulos(sello, d, overrides) {
  return _postJSON("/api/fantasia/rotulos", { sello, d, overrides });
}

// ---- mundos (servidor/rutas_mundos.py) -------------------------------------

// GET /api/w/<sello>[?d=] -> ficha del mundo:
//   {sello, nombre, d, meta:{semilla, continentes, mar, paises?,
//    asentamientos?, creado, ...}, publico, dueno, es_dueno, imagen,
//    lugares:[{x, y, nombre, bioma, regla}]}
// d omitido -> el servidor resuelve el detalle por defecto. 404 -> Error
// status 404 "mundo no encontrado".
export function mundo(sello, d) {
  return _getJSON(`/api/w/${encodeURIComponent(sello)}${_qs({ d })}`, false);
}

// GET /api/w?orden=nuevos|azar&q=&n=24 -> [{sello, nombre, d, semilla,
// creado, imagen}] (mundos públicos). Todos los campos son opcionales.
export function mundos({ orden, q, n } = {}) {
  return _getJSON(`/api/w${_qs({ orden, q, n })}`, false);
}

// GET /api/w/dia[?desde=<sello>] -> ficha (misma forma que mundo()).
// `desde`: sello actual, para pedir otro mundo distinto («otro mundo»).
// 404 -> Error status 404 "sin mundos".
export function mundoDia(desde) {
  return _getJSON(`/api/w/dia${_qs({ desde })}`, false);
}

// POST /api/w/<sello>/visibilidad {publico} -> {sello, publico}.
// 403 (no eres el dueño) -> Error status 403, sin aviso automático.
export function visibilidad(sello, publico) {
  return _postJSON(`/api/w/${encodeURIComponent(sello)}/visibilidad`,
    { publico: !!publico }, false);
}

// ---- cuenta y guardados (servidor/rutas_cuentas.py) ------------------------

let _cuentaPromesa = null;

// GET /api/cuenta -> {plan, limites, uso:{renders_hoy, tope_dia}, email?,
//   expira?, plan_contratado?, anonimo?, guardados_n, mundos_propios:[sello]}.
// Memoizada: nav.js y la página comparten UNA petición. {fresca:true} fuerza
// pedirla de nuevo. guardar/quitarGuardado/salir invalidan la memo. Si la
// petición falla, la memo se borra y el Error se propaga.
export function cuenta({ fresca = false } = {}) {
  if (fresca || !_cuentaPromesa) {
    _cuentaPromesa = _getJSON("/api/cuenta", false).catch((e) => {
      _cuentaPromesa = null;
      throw e;
    });
  }
  return _cuentaPromesa;
}

// esPro(c) -> true si el plan vigente de la cuenta `c` es pro o comercial.
export function esPro(c) {
  const plan = c && c.plan;
  return plan === "pro" || plan === "comercial";
}

// conSesion(c) -> true si la cuenta `c` tiene sesión (email y no anónima).
export function conSesion(c) {
  return !!(c && c.email && !c.anonimo);
}

// POST /api/cuenta/enlace {email, volver?} -> {ok:true, modo:"smtp"|"dev"}.
// volver: ruta interna donde aterriza el enlace (p. ej. pathname + search);
// el servidor la valida. Errores: 400 (correo inválido), 429 (demasiados
// enlaces), 502 (fallo de envío) -> Error con status y mensaje del servidor.
export function pedirEnlace(email, volver) {
  const cuerpo = { email: String(email || "").trim() };
  if (volver) cuerpo.volver = String(volver);
  return _postJSON("/api/cuenta/enlace", cuerpo, false);
}

// POST /api/cuenta/salir -> cierra la sesión (borra la cookie).
export async function salir() {
  const r = await _postJSON("/api/cuenta/salir", {}, false);
  _cuentaPromesa = null;
  return r;
}

// GET /api/yo/guardados -> [{tipo:"mundo"|"battlemap", sello, x, y, query,
// creado}] (ya desempaquetado). Sin sesión -> Error status 401.
export async function guardados() {
  const j = await _getJSON("/api/yo/guardados", false);
  return (j && j.guardados) || [];
}

// item: {tipo:"mundo"|"battlemap", sello, x?, y?, query?}. x/y obligatorios
// en battlemap; query admite string, objeto o URLSearchParams (aQuery).
function _item({ tipo, sello, x, y, query } = {}) {
  const c = { tipo, sello };
  if (x !== undefined && x !== null) c.x = Number(x);
  if (y !== undefined && y !== null) c.y = Number(y);
  if (query !== undefined && query !== null) c.query = aQuery(query);
  return c;
}

// POST /api/yo/guardados item -> {ok, nuevo, guardado}. Idempotente
// (duplicado -> nuevo=false). Sin sesión -> Error status 401.
export async function guardar(item) {
  const r = await _postJSON("/api/yo/guardados", _item(item), false);
  _cuentaPromesa = null; // guardados_n cambió
  return r;
}

// DELETE /api/yo/guardados {tipo, sello, x?, y?} -> {ok, borrado}
// (borrado=false si no existía). Sin sesión -> Error status 401.
export async function quitarGuardado(item) {
  const cuerpo = _item(item);
  delete cuerpo.query; // query no identifica el guardado
  const r = await _postJSON("/api/yo/guardados", cuerpo, false, "DELETE");
  _cuentaPromesa = null;
  return r;
}

// ---- URLs de página (servidor/rutas_paginas.py) ----------------------------

// aQuery(q) -> "a=1&b=2" sin "?". q: objeto (omite null/undefined/""),
// URLSearchParams o string (con o sin "?" inicial). Falsy -> "".
export function aQuery(q) {
  if (!q) return "";
  if (typeof q === "string") return q.charAt(0) === "?" ? q.slice(1) : q;
  if (q instanceof URLSearchParams) return q.toString();
  return _qs(q).slice(1);
}

function _conQuery(ruta, q) {
  const s = aQuery(q);
  return s ? `${ruta}?${s}` : ruta;
}

// /w/<sello>[?q] — ficha del mundo. q típico: {d}.
export function urlMundo(sello, q) {
  return _conQuery(`/w/${encodeURIComponent(sello)}`, q);
}

// /w/<sello>/mapa[?q] — visor del mapa de fantasía. q típico: {d}.
export function urlMapa(sello, q) {
  return _conQuery(`/w/${encodeURIComponent(sello)}/mapa`, q);
}

// /w/<sello>/<x>,<y>[?q] — battlemap del punto. x, y se redondean a enteros
// >= 0 (el servidor exige [0-9]+,[0-9]+). q: objeto, URLSearchParams o string
// (d, tema, px, ...).
export function urlBattlemap(sello, x, y, q) {
  const ix = Math.max(0, Math.round(Number(x) || 0));
  const iy = Math.max(0, Math.round(Number(y) || 0));
  return _conQuery(`/w/${encodeURIComponent(sello)}/${ix},${iy}`, q);
}

// /w/<sello>/jugar[?q] — juego de conquista. q típico: {d}.
export function urlJugar(sello, q) {
  return _conQuery(`/w/${encodeURIComponent(sello)}/jugar`, q);
}
