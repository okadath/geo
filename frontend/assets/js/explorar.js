// explorar.js — portada `/` (T08): mundo del día con el visor vivo, tira
// «Más mundos» con filtros (nuevos · al azar · buscador) y estado vacío.
// Solo presentación: la elección del mundo del día, el orden y la búsqueda
// los resuelve el servidor (GET /api/w, /api/w/dia).

import { montarNav, montarPie } from "/app/js/nav.js";
import {
  capas, mundos, mundoDia, urlMundo,
} from "/app/js/api.js";
import { crearVisor } from "/app/js/visor.js";
import { aviso } from "/app/js/ui.js";

// textos visibles de la página (agrupados para la localización, ADR-008)
const TXT = {
  errDia: "No se pudo cargar el mundo del día. Recarga la página en un momento.",
  errCapas: "Este mundo no tiene capas de mapa todavía.",
  errSiguiente: "No se pudo cargar otro mundo.",
  errLista: "No se pudo cargar la lista de mundos.",
  sinResultados: (q) => `Ningún mundo público coincide con «${q}».`,
  verTodos: "Ver todos",
  miniatura: (n) => `Mapa de ${n}`,
};

const $ = (sel) => document.querySelector(sel);

montarNav({ activa: "explorar" });
montarPie();

// estado de la página
const st = {
  dia: null,        // ficha del mundo del día mostrado
  orden: "nuevos",
  q: "",
  genVisor: 0,      // descarta cargas de visor que llegan tarde
  genLista: 0,      // descarta listas que llegan tarde
};

// ============================================================================
//  mundo del día
// ============================================================================

async function cargarDia(desde) {
  const seccion = $("#ex-dia");
  seccion.setAttribute("aria-busy", "true");
  let ficha;
  try {
    ficha = await mundoDia(desde);
  } catch (e) {
    seccion.setAttribute("aria-busy", "false");
    if (e.status === 404) return null;        // sin públicos -> estado vacío
    if (desde) aviso(TXT.errSiguiente, "error");
    else mostrarErrorDia(TXT.errDia);
    return undefined;
  }
  st.dia = ficha;
  pintarCabeceraDia(ficha);
  await montarVisor(ficha);
  seccion.setAttribute("aria-busy", "false");
  return ficha;
}

function pintarCabeceraDia(f) {
  $("#ex-dia-nombre").textContent = `«${f.nombre}»`;
  $("#ex-dia-sello").textContent = `#${f.sello}`;
  $("#ex-dia-ficha").href = urlMundo(f.sello);
  $("#ex-dia-error").classList.add("oculto");
}

function mostrarErrorDia(texto) {
  const el = $("#ex-dia-error");
  el.textContent = texto;
  el.classList.remove("oculto");
}

// Un visor por mundo: se clona la plantilla y se crea un visor nuevo (visor.js
// fija sello/d al crearse). Clic en el mapa -> ficha del mundo (/w/<sello>);
// desde ahí se abre el battlemap (rol) o la conquista.
async function montarVisor(f) {
  const gen = ++st.genVisor;
  let info;
  try {
    info = await capas(f.sello, f.d);
  } catch (_) {
    if (gen === st.genVisor) mostrarErrorDia(TXT.errCapas);
    return;
  }
  if (gen !== st.genVisor) return;

  const caja = $("#ex-visor-caja");
  const plantilla = $("#ex-visor-plantilla");
  const nodo = plantilla.content.firstElementChild.cloneNode(true);
  caja.replaceChildren(plantilla, nodo);

  const visor = crearVisor({ sello: f.sello, d: f.d, elVisor: nodo });
  // sin overlay decorativo (marco, rosa de vientos): cada PNG cuenta como
  // render en el cupo del visitante y la portada ya pide sector + miniaturas
  visor.setEstilo({ deco: false });
  visor.setPick(true);
  visor.onPick = () => {
    location.href = urlMundo(f.sello);
  };
  visor.onEstado = (txt, err) => {
    if (err) mostrarErrorDia(txt);
  };
  visor.cargar(info.resolucion);
}

$("#ex-dia-siguiente").addEventListener("click", async (e) => {
  const boton = e.currentTarget;
  boton.disabled = true;
  try {
    await cargarDia(st.dia && st.dia.sello);
  } finally {
    boton.disabled = false;
  }
});

// ============================================================================
//  tira «Más mundos»
// ============================================================================

function esqueletos(n = 6) {
  return Array.from({ length: n }, () => {
    const el = document.createElement("div");
    el.className = "tarjeta ex-mini ex-mini-esqueleto";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = `<div class="esqueleto ex-mini-img"></div>
      <div class="ex-mini-cuerpo">
        <div class="esqueleto esqueleto-texto"></div>
        <div class="esqueleto esqueleto-texto" style="width:50%"></div>
      </div>`;
    return el;
  });
}

function tarjetaMini(m) {
  const a = document.createElement("a");
  a.className = "tarjeta tarjeta-activable ex-mini";
  a.href = urlMundo(m.sello);
  a.setAttribute("role", "listitem");

  const marco = document.createElement("div");
  marco.className = "ex-mini-img";
  const img = document.createElement("img");
  img.alt = TXT.miniatura(m.nombre);
  img.loading = "lazy";     // solo las visibles: cada miniatura es un render
  img.decoding = "async";
  img.addEventListener("load", () => img.classList.add("cargada"));
  img.addEventListener("error", () => img.remove());
  img.src = m.imagen;
  marco.append(img);

  const cuerpo = document.createElement("div");
  cuerpo.className = "ex-mini-cuerpo";
  const nombre = document.createElement("span");
  nombre.className = "ex-mini-nombre";
  nombre.textContent = m.nombre;
  const sello = document.createElement("span");
  sello.className = "mono tenue ex-mini-sello";
  sello.textContent = `#${m.sello}`;
  cuerpo.append(nombre, sello);

  a.append(marco, cuerpo);
  return a;
}

async function cargarLista() {
  const gen = ++st.genLista;
  const tira = $("#ex-tira");
  const nota = $("#ex-tira-nota");
  tira.setAttribute("aria-busy", "true");
  tira.replaceChildren(...esqueletos());
  nota.classList.add("oculto");
  let lista;
  try {
    lista = await mundos({ orden: st.orden, q: st.q || undefined, n: 12 });
  } catch (_) {
    if (gen !== st.genLista) return null;
    tira.replaceChildren();
    tira.setAttribute("aria-busy", "false");
    nota.textContent = TXT.errLista;
    nota.classList.remove("oculto");
    return null;
  }
  if (gen !== st.genLista) return null;
  tira.setAttribute("aria-busy", "false");
  tira.replaceChildren(...lista.map(tarjetaMini));
  tira.scrollLeft = 0;
  if (!lista.length && st.q) {
    nota.textContent = TXT.sinResultados(st.q);
    const ver = document.createElement("button");
    ver.type = "button";
    ver.className = "btn btn-fantasma btn-sm ex-ver-todos";
    ver.textContent = TXT.verTodos;
    ver.addEventListener("click", () => {
      $("#ex-q").value = "";
      st.q = "";
      cargarLista();
    });
    nota.append(" ", ver);
    nota.classList.remove("oculto");
  }
  return lista;
}

for (const pestana of document.querySelectorAll(".ex-mas .pestana")) {
  pestana.addEventListener("click", () => {
    const orden = pestana.dataset.orden;
    for (const p of document.querySelectorAll(".ex-mas .pestana")) {
      p.setAttribute("aria-selected", String(p === pestana));
    }
    st.orden = orden;
    cargarLista();   // «al azar» vuelve a barajar en cada pulsación
  });
}

$("#ex-buscador").addEventListener("submit", (e) => {
  e.preventDefault();
  st.q = $("#ex-q").value.trim();
  cargarLista();
});
// borrar con la ✕ del campo de búsqueda vuelve a la lista completa
$("#ex-q").addEventListener("search", () => {
  if (!$("#ex-q").value.trim() && st.q) {
    st.q = "";
    cargarLista();
  }
});

// ============================================================================
//  arranque
// ============================================================================

function mostrarVacio() {
  $("#ex-dia").classList.add("oculto");
  $("#ex-mas").classList.add("oculto");
  $("#ex-vacio").classList.remove("oculto");
}

(async function arrancar() {
  const [dia] = await Promise.all([cargarDia(), cargarLista()]);
  if (dia === null) mostrarVacio();
})();
