// landing.js — comportamiento de la landing comercial (index.html).
// Solo mejoras progresivas: la página funciona sin JS. Depende de nav.js y,
// opcionalmente, de api.js (mejora del hero con una imagen real del producto).

import { montarNav, montarPie } from "/app/js/nav.js";
import { corridas, urlFantasiaRender } from "/app/js/api.js";

montarNav("");
montarPie({ lab: false });

// --- botones de plan: intentan el checkout; hoy siempre 503 (modo beta) y se
// cae al mailto de lista de espera que ya trae el propio <a> (ADR-007: nunca un
// checkout falso). Sin JS, el enlace mailto funciona igual (mejora progresiva).
for (const a of document.querySelectorAll(".plan [data-plan]")) {
  a.addEventListener("click", async (e) => {
    const plan_id = a.dataset.plan;
    e.preventDefault();
    try {
      const res = await fetch("/api/pagos/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id }),
      });
      if (res.ok) {
        const j = await res.json().catch(() => ({}));
        if (j && j.url) { location.href = j.url; return; } // pasarela activa
      }
    } catch (_) { /* sin API: cae al mailto */ }
    // 503 modo beta o cualquier fallo -> el mailto de lista de espera del <a>
    location.href = a.href;
  });
}

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
