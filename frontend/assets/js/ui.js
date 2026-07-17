// ui.js — utilidades de presentación compartidas por el workspace:
// avisos (toasts) y modal. Usan las clases de base.css (.avisos/.aviso/.modal…).
// Español en la UI (ADR-008).

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
