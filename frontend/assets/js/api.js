// api.js — cliente de la API existente de web.py + módulos *_srv.
// NO inventa endpoints: cada función corresponde a una ruta ya servida por el
// back (ver web.py, fantasia_srv.py, batalla_srv.py). El front es visor
// delgado; la lógica propietaria vive en el servidor.

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
async function _revisar(res) {
  if (res.ok) return res;
  let msg = `HTTP ${res.status}`;
  try {
    const j = await res.json();
    if (j && j.error) msg = j.error;
  } catch (_) {
    /* respuesta no-JSON: se queda el "HTTP N" */
  }
  throw new Error(msg);
}

async function _getJSON(url) {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  await _revisar(res);
  return res.json();
}

async function _postJSON(url, cuerpo) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo || {}),
  });
  await _revisar(res);
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
