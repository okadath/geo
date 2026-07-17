// landing.js — comportamiento de la landing comercial (index.html).
// Solo mejoras progresivas: la página funciona sin JS. Depende de nav.js y,
// opcionalmente, de api.js (mejora del hero con una imagen real del producto).

import { montarNav, montarPie } from "/app/js/nav.js";
import { corridas, urlFantasiaRender } from "/app/js/api.js";

montarNav("");
montarPie({ lab: false });

// --- fade-in por scroll (IntersectionObserver) ------------------------------
const animables = document.querySelectorAll(".aparece");
if ("IntersectionObserver" in window && animables.length) {
  const obs = new IntersectionObserver(
    (entradas) => {
      for (const e of entradas) {
        if (e.isIntersecting) {
          e.target.classList.add("visible");
          obs.unobserve(e.target);
        }
      }
    },
    { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
  );
  animables.forEach((el) => obs.observe(el));
} else {
  // sin soporte: mostrar todo
  animables.forEach((el) => el.classList.add("visible"));
}

// --- mejora progresiva del hero: imagen real si hay una corrida usable -------
// Silenciosa: cualquier fallo deja el arte SVG autocontenido intacto.
async function pintarHeroReal() {
  const marco = document.getElementById("heroArte");
  if (!marco) return;
  try {
    const lista = await corridas();
    if (!Array.isArray(lista)) return;
    // primera corrida con al menos un detalle con mapa (stem = d.d)
    let sello = null;
    let d = null;
    for (const c of lista) {
      const det = (c.detalles || []).find((x) => x && x.d && x.png);
      if (det) {
        sello = c.sello;
        d = det.d;
        break;
      }
    }
    if (!sello || !d) return;
    const url = urlFantasiaRender(sello, d, { px: 720 });
    const img = new Image();
    img.decoding = "async";
    img.loading = "eager";
    img.alt = "Mapa de fantasía generado con Mundaria";
    img.className = "hero-real";
    img.onload = () => {
      marco.appendChild(img);
      // forzar transición
      requestAnimationFrame(() => {
        img.classList.add("cargada");
        const etq = document.getElementById("heroEtq");
        if (etq) etq.classList.add("visible");
      });
    };
    img.onerror = () => {}; // fallback silencioso: se queda el arte SVG
    img.src = url;
  } catch (_) {
    /* sin API o sin corridas: se queda el arte SVG */
  }
}
pintarHeroReal();
