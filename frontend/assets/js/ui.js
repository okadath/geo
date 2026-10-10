// ui.js — utilidades de presentación compartidas por las páginas: avisos
// (toasts), modal, cuadro de correo (enlace mágico) y muro Pro. Usan solo
// clases de base.css (.avisos/.aviso/.modal/.tarjeta/.campo/.btn…).
// Español en la UI (ADR-008).
//
// API PÚBLICA
//   aviso(texto, tipo?, ms?) -> función quitar()
//     tipo: "ok" | "error" | "info" | "" (oro); ms=0 lo deja fijo.
//   modal({titulo, cuerpoHTML}) -> nodo .modal-fondo (con .cerrar()).
//   cuadroCorreo({volver?, montarEn?, titulo?, texto?, alEnviar?})
//     -> HTMLElement <div class="tarjeta cuadro-correo">
//     Campo de correo + «Enviarme el enlace». Llama a api.pedirEnlace(email,
//     volver) y, si va bien, sustituye el formulario por el estado «enviado»
//     (con «Usar otro correo»); en modo "dev" añade el aviso de que el enlace
//     está en el log del servidor. Errores (400/429/502) se muestran dentro
//     del cuadro. volver por defecto = ruta actual (pathname+search+hash).
//     montarEn: elemento o selector CSS donde se anexa (si no, no se inserta).
//     alEnviar(respuesta {ok, modo}, email): callback opcional.
//     Uso típico: ★ Guardar sin sesión -> modal + cuadroCorreo({montarEn}).
//   muroPro(texto?) -> HTMLElement <div class="tarjeta muro-pro">
//     Bloque con el texto y botón «Ver Pro» -> /yo#pro. No se inserta solo.

import { pedirEnlace } from "./api.js";

// ---- avisos (toasts efímeros, esquina inferior derecha) --------------------
let _cajaAvisos = null;
function _caja() {
  if (!_cajaAvisos) {
    _cajaAvisos = document.createElement("div");
    _cajaAvisos.className = "avisos";
    document.body.appendChild(_cajaAvisos);
  }
  return _cajaAvisos;
}

// aviso(texto, tipo, ms) — tipo: "ok" | "error" | "info" | "" (oro). ms=0 fija.
export function aviso(texto, tipo = "", ms = 4200) {
  const el = document.createElement("div");
  el.className = "aviso" + (tipo ? ` aviso-${tipo}` : "");
  el.setAttribute("role", tipo === "error" ? "alert" : "status");
  el.textContent = texto;
  _caja().appendChild(el);
  const quitar = () => {
    el.classList.add("saliendo");
    setTimeout(() => el.remove(), 300);
  };
  if (ms > 0) setTimeout(quitar, ms);
  el.addEventListener("click", quitar);
  return quitar;
}

// ---- modal (overlay con título + contenido HTML) ---------------------------
// modal({titulo, cuerpoHTML}) -> devuelve el nodo; se cierra por la ✕, el fondo,
// Escape, o cualquier elemento con [data-cerrar].
export function modal({ titulo = "", cuerpoHTML = "" } = {}) {
  const fondo = document.createElement("div");
  fondo.className = "modal-fondo";
  fondo.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="${titulo}">
      <div class="modal-cabecera">
        <h3 style="margin:0">${titulo}</h3>
        <button class="modal-cerrar" data-cerrar aria-label="cerrar">✕</button>
      </div>
      <div class="modal-cuerpo">${cuerpoHTML}</div>
    </div>`;
  const cerrar = () => {
    document.removeEventListener("keydown", alTecla);
    fondo.remove();
  };
  const alTecla = (e) => { if (e.key === "Escape") cerrar(); };
  fondo.addEventListener("click", (e) => {
    if (e.target === fondo || e.target.closest("[data-cerrar]")) cerrar();
  });
  document.addEventListener("keydown", alTecla);
  document.body.appendChild(fondo);
  fondo.cerrar = cerrar;
  return fondo;
}

// escape mínimo para interpolar texto del usuario en HTML.
function _esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function _destino(montarEn) {
  if (!montarEn) return null;
  return typeof montarEn === "string" ? document.querySelector(montarEn) : montarEn;
}

// ---- cuadro de correo (enlace mágico) --------------------------------------
// Ver cabecera. Cada cuadro usa ids únicos para label/input.
let _nCuadros = 0;
export function cuadroCorreo({
  volver,
  montarEn,
  titulo = "Entra con tu correo",
  texto = "Te enviamos un enlace para entrar; sin contraseñas.",
  alEnviar,
} = {}) {
  const id = `correo-${++_nCuadros}`;
  const caja = document.createElement("div");
  caja.className = "tarjeta cuadro-correo";
  const ruta = volver || (location.pathname + location.search + location.hash);

  const pintarFormulario = (valor = "") => {
    caja.innerHTML = `
      ${titulo ? `<h3>${_esc(titulo)}</h3>` : ""}
      ${texto ? `<p class="tenue">${_esc(texto)}</p>` : ""}
      <form class="campo" novalidate>
        <label for="${id}">Correo</label>
        <input id="${id}" type="email" name="email" required
               autocomplete="email" placeholder="tu@correo.com"
               value="${_esc(valor)}">
        <button class="btn btn-oro" type="submit">Enviarme el enlace</button>
        <p class="tenue" role="alert" data-estado></p>
      </form>`;
    const form = caja.querySelector("form");
    const input = caja.querySelector("input");
    const boton = caja.querySelector("button");
    const estado = caja.querySelector("[data-estado]");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = input.value.trim();
      if (!email || !input.checkValidity()) {
        estado.textContent = "Escribe un correo válido.";
        input.focus();
        return;
      }
      boton.disabled = true;
      estado.textContent = "Enviando…";
      try {
        const r = await pedirEnlace(email, ruta);
        pintarEnviado(email, r && r.modo);
        if (typeof alEnviar === "function") alEnviar(r, email);
      } catch (err) {
        boton.disabled = false;
        estado.textContent = err.status === 429
          ? "Demasiados enlaces pedidos; prueba dentro de una hora."
          : err.status === 502
            ? "No pudimos enviar el correo. Inténtalo de nuevo en un rato."
            : (err.message || "No se pudo enviar el enlace.");
      }
    });
  };

  const pintarEnviado = (email, modo) => {
    const dev = modo === "dev"
      ? `<p class="aviso aviso-info" role="note">Modo desarrollo: no se envió
           ningún correo; el enlace está en el log del servidor.</p>`
      : "";
    caja.innerHTML = `
      <h3>Revisa tu correo</h3>
      <p>Te enviamos un enlace a <strong>${_esc(email)}</strong>. Ábrelo para
         entrar; caduca en 15 minutos.</p>
      ${dev}
      <button class="btn btn-fantasma btn-sm" type="button" data-otro>
        Usar otro correo</button>`;
    caja.querySelector("[data-otro]")
      .addEventListener("click", () => pintarFormulario(email));
  };

  pintarFormulario();
  const destino = _destino(montarEn);
  if (destino) destino.appendChild(caja);
  return caja;
}

// ---- muro Pro --------------------------------------------------------------
// muroPro(texto) -> bloque con el texto y botón a /yo#pro (ver cabecera).
export function muroPro(texto = "Esta función es parte del plan Pro.") {
  const caja = document.createElement("div");
  caja.className = "tarjeta muro-pro";
  caja.innerHTML = `
    <p>${_esc(texto)}</p>
    <a class="btn btn-oro" href="/yo#pro">Ver Pro · $29/año</a>`;
  return caja;
}
