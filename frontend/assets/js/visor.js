// visor.js — visor pan/zoom del mapa de fantasía, LIENZO principal del
// workspace (ADR-006). Portado fielmente de fantasia.html: todo el dibujo
// (pergamino, ríos, rótulos, decoración) se hornea en el servidor
//   GET /api/fantasia/render  -> mapa completo (exportar)
//   GET /api/fantasia/sector  -> ventana de mundo re-horneada (nítida a zoom)
//   GET /api/fantasia/deco    -> overlay transparente (marco, rosa de vientos)
// El visor es delgado: solo presentación (pan/zoom + carga de PNGs).
//
// Además del rol de fantasía, este visor es el tablero del modo Battlemap:
// expone un modo «puntería» que traduce un clic a la rejilla (rx,ry) del mundo
// y pinta un pin. Un solo lienzo, tres modos (ADR-006).

import {
  urlFantasiaRender, urlFantasiaSector, urlFantasiaDeco,
} from "./api.js";

// color de papel del visor por paleta (solo UI): las zonas de mundo que el
// sector aún no cubre se ven «papel cargando», no negras.
const FONDO_UI = {
  claro: "#e9dcbf", sepia: "#dcc79a", noche: "#22303f",
  imprenta: "#fafafa", esmeralda: "#dee3c7", carmesi: "#ebdfc5",
  oceanico: "#e2ecf2",
};

// crearVisor({sello, d, elVisor, elCargador}) -> API del visor.
export function crearVisor({ sello, d, elVisor }) {
  const lienzo = elVisor.querySelector(".vs-lienzo");
  const mapa = elVisor.querySelector(".vs-mapa");
  const deco = elVisor.querySelector(".vs-deco");
  const pin = elVisor.querySelector(".vs-pin");

  // ---- estado (solo presentación) ----
  const st = {
    scale: 1, tx: 0, ty: 0,
    nx: 1536, ny: 768,             // resolución (coords de mundo del detalle; 2:1 por defecto)
    semilla: d,
    paleta: "claro",
    calidad: 1,
    capas: {
      relieve: true, veg: true, rios: true, caminos: true,
      asent: true, rotulos: true, tinte: false,
    },
    paises: "grandes", npaises: 8, fspais: 1, fsciu: 1.8,
    deco: true,                    // overlay decorativo visible
    win: null,                     // ventana de mundo del PNG mostrado
    listo: false,
    rotver: 0,                     // versión de overrides de rótulos (bust caché)
    pick: false,                   // modo puntería (battlemap)
    punto: null,                   // {rx, ry} elegido (pin)
  };

  const api = {
    onPick: null,                  // callback(rx, ry) del modo puntería
    onEstado: null,                // callback(texto, esError) para barra de estado
  };

  elVisor.style.background = FONDO_UI[st.paleta];

  // ---- parámetros de render (misma API que fantasia.html) ----
  function capasActivas() {
    return Object.entries(st.capas)
      .filter(([, v]) => v).map(([k]) => k).join(",");
  }
  function paramsBase() {
    const q = {
      calidad: st.calidad, semilla: st.semilla, paleta: st.paleta,
      capas: capasActivas(), paises: st.paises,
    };
    if (st.paises === "grandes") q.npaises = Math.max(1, Math.min(64, st.npaises | 0 || 8));
    if (st.fspais !== 1) q.fspais = st.fspais.toFixed(1);
    if (st.fsciu !== 1) q.fsciu = st.fsciu.toFixed(1);
    return q;
  }
  function urlSector(win, extras) {
    const q = paramsBase();
    q.cx = (win.x0 + win.w / 2).toFixed(3);
    q.cy = (win.y0 + win.h / 2).toFixed(3);
    q.w = win.w.toFixed(3);
    q.h = win.h.toFixed(3);
    if (st.rotver) q.rv = st.rotver;
    Object.assign(q, extras || {});
    return urlFantasiaSector(sello, d, q);
  }
  function urlDeco(win) {
    return urlFantasiaDeco(sello, d, {
      calidad: st.calidad, paleta: st.paleta,
      cx: (win.x0 + win.w / 2).toFixed(3), cy: (win.y0 + win.h / 2).toFixed(3),
      w: win.w.toFixed(3), h: win.h.toFixed(3), px: 1200,
    });
  }

  function estado(txt, err = false) {
    if (typeof api.onEstado === "function") api.onEstado(txt, err);
  }

  // ---- ventana de mundo visible según zoom/paneo actual ----
  function winVisible(pad) {
    const W = elVisor.clientWidth || 1, Hv = elVisor.clientHeight || 1;
    let w = st.nx / st.scale, h = st.ny / st.scale;
    let x0 = -st.tx / st.scale / W * st.nx;
    let y0 = -st.ty / st.scale / Hv * st.ny;
    x0 -= w * pad; y0 -= h * pad;
    w *= 1 + 2 * pad; h *= 1 + 2 * pad;
    if (w > st.nx) { w = st.nx; h = st.ny; }
    x0 = Math.max(0, Math.min(st.nx - w, x0));
    y0 = Math.max(0, Math.min(st.ny - h, y0));
    return { x0, y0, w, h };
  }

  // ---- carga del sector renderizado en el servidor ----
  let genRender = 0;               // descarta respuestas viejas fuera de orden
  function renderVisible() {
    if (!st.listo) return;
    const win = winVisible(0.18);
    const gen = ++genRender;
    const url = urlSector(win);
    elVisor.classList.add("cargando");
    estado("pintando el mapa…");
    const im = new Image();
    im.onload = () => {
      if (gen !== genRender) return;             // llegó tarde: ya hay otra vista
      elVisor.classList.remove("cargando");
      mapa.src = url;
      st.win = win;
      colocarMapa();
      estado("");
    };
    im.onerror = () => {
      if (gen !== genRender) return;
      elVisor.classList.remove("cargando");
      estado("el servidor no pudo renderizar el sector", true);
    };
    im.src = url;
    deco.src = st.deco ? urlDeco(winVisible(0)) : "";
    deco.style.display = st.deco ? "block" : "none";
  }

  // coloca la imagen (que contiene solo st.win) dentro del lienzo, para que
  // coincida pixel-perfecto con la posición de esa ventana en el mundo.
  function colocarMapa() {
    if (!st.win) return;
    mapa.style.transform =
      `translate(${st.win.x0 / st.nx * 100}%, ${st.win.y0 / st.ny * 100}%) ` +
      `scale(${st.win.w / st.nx})`;
  }

  // re-render diferido: durante la interacción el PNG viejo se escala por CSS
  // (rápido) y ~220 ms después de soltar se pide nítido el sector.
  let tmrRender = 0;
  function programarRender() {
    clearTimeout(tmrRender);
    elVisor.classList.add("cargando");
    tmrRender = setTimeout(renderVisible, 220);
  }

  // ---- zoom / paneo (patrón de fantasia.html) ----
  function aplicar() {
    lienzo.style.transform = `translate(${st.tx}px,${st.ty}px) scale(${st.scale})`;
  }
  function zoomMax() { return 6 + 12 * st.calidad; }
  function acotar() {
    const W = elVisor.clientWidth, H = elVisor.clientHeight;
    const sw = W * st.scale, sh = H * st.scale;
    st.tx = sw <= W ? (W - sw) / 2 : Math.min(0, Math.max(W - sw, st.tx));
    st.ty = sh <= H ? (H - sh) / 2 : Math.min(0, Math.max(H - sh, st.ty));
  }

  function zoomEn(mx, my, f) {
    const wx = (mx - st.tx) / st.scale, wy = (my - st.ty) / st.scale;
    const ns = Math.min(zoomMax(), Math.max(1, st.scale * f));
    if (ns === st.scale) return;
    st.tx = mx - wx * ns; st.ty = my - wy * ns; st.scale = ns;
    acotar(); aplicar(); pintarPin(); programarRender();
  }

  elVisor.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = elVisor.getBoundingClientRect();
    zoomEn(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.2 : 1 / 1.2);
  }, { passive: false });

  // pan + clic-para-elegir (battlemap). Distinguimos clic de arrastre por
  // umbral de movimiento, como batalla.html.
  let abajo = null, movio = false;
  elVisor.addEventListener("mousedown", (e) => {
    abajo = { x: e.clientX, y: e.clientY }; movio = false;
  });
  window.addEventListener("mouseup", (e) => {
    if (abajo && !movio && st.pick && typeof api.onPick === "function") {
      const c = pantallaARender(e.clientX, e.clientY);
      if (c.rx >= 0 && c.ry >= 0 && c.rx < st.nx && c.ry < st.ny) {
        api.onPick(c.rx, c.ry);
      }
    }
    abajo = null; elVisor.classList.remove("agarrando");
  });
  window.addEventListener("mousemove", (e) => {
    if (!abajo) return;
    if (Math.abs(e.clientX - abajo.x) + Math.abs(e.clientY - abajo.y) > 4) {
      movio = true; elVisor.classList.add("agarrando");
    }
    if (movio) {
      st.tx += e.movementX; st.ty += e.movementY;
      acotar(); aplicar(); pintarPin(); programarRender();
    }
  });

  new ResizeObserver(() => {
    if (!st.listo || !st.win) return;
    acotar(); aplicar(); colocarMapa(); pintarPin(); programarRender();
  }).observe(elVisor);

  // ==========================================================================
  //  CONVERSIÓN DE COORDENADAS clic-de-pantalla -> rejilla del mundo (rx, ry)
  // --------------------------------------------------------------------------
  //  Idéntica a la función coord() de batalla.html, y es correcta porque el
  //  visor de fantasía usa EXACTAMENTE el mismo modelo de lienzo que el de
  //  batalla: un <div> (#lienzo) del tamaño del visor (W×H a scale=1) sobre el
  //  que el mundo entero (0..nx, 0..ny) se mapea llenando el 100%, y al que se
  //  le aplica `translate(tx,ty) scale(scale)` para el pan/zoom.
  //
  //    1. (mx,my) = posición del clic relativa al visor (restamos el rect).
  //    2. (wx,wy) = deshacer el transform del lienzo: (m - t)/scale  -> da la
  //       posición en el lienzo sin transformar, en px de PANTALLA (0..W,0..H).
  //    3. (rx,ry) = escalar de px de pantalla a px de RENDER/mundo:
  //       rx = wx * nx / W ,  ry = wy * ny / H.
  //
  //  nx,ny provienen de _capas.json/batallaInfo().resolucion, la MISMA
  //  resolución común a fantasía y battlemap, así que (rx,ry) es directamente
  //  la coordenada que /api/batalla/lugar y /api/batalla/mapa esperan.
  // ==========================================================================
  function pantallaARender(clientX, clientY) {
    const r = elVisor.getBoundingClientRect();
    const mx = clientX - r.left, my = clientY - r.top;
    const W = elVisor.clientWidth, H = elVisor.clientHeight;
    const wx = (mx - st.tx) / st.scale, wy = (my - st.ty) / st.scale;
    return { rx: wx * st.nx / W, ry: wy * st.ny / H };
  }

  // ---- pin del punto elegido (canvas sobre el lienzo, en coords de mundo) ----
  // El canvas tiene backing-store nx×ny y CSS 100%, así que vive en el mismo
  // espacio que el mapa y se transforma con el lienzo (igual que batalla.html).
  function pintarPin() {
    pin.width = st.nx; pin.height = st.ny;
    const ctx = pin.getContext("2d");
    ctx.clearRect(0, 0, pin.width, pin.height);
    if (!st.punto) return;
    const z = Math.max(1, st.scale);       // tamaño constante en pantalla
    // los símbolos se derivan del eje menor para que un mundo 2:1 tenga pines
    // proporcionados al alto, no al doble de ancho
    const m = Math.min(st.nx, st.ny);
    const r = Math.max(3, m / 90 / z);
    ctx.lineCap = "round";
    for (let paso = 0; paso < 2; paso++) {
      ctx.strokeStyle = paso === 0 ? "rgba(0,0,0,0.6)" : "#d4a94e";
      ctx.lineWidth = paso === 0 ? Math.max(1, m / 300 / z)
                                 : Math.max(0.6, m / 600 / z);
      ctx.beginPath();
      ctx.moveTo(st.punto.rx - r, st.punto.ry - r);
      ctx.lineTo(st.punto.rx + r, st.punto.ry + r);
      ctx.moveTo(st.punto.rx + r, st.punto.ry - r);
      ctx.lineTo(st.punto.rx - r, st.punto.ry + r);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(st.punto.rx, st.punto.ry, r * 1.5, 0, 7);
      ctx.stroke();
    }
  }

  // ==========================================================================
  //  API pública del visor
  // ==========================================================================
  return Object.assign(api, {
    // arranca el visor con la resolución del detalle (de _capas.json).
    cargar(resolucion) {
      [st.nx, st.ny] = resolucion || [1536, 768];
      elVisor.style.setProperty("--ar", `${st.nx} / ${st.ny}`);
      st.listo = true;
      aplicar();
      requestAnimationFrame(() => requestAnimationFrame(renderVisible));
    },
    reRender: renderVisible,
    get nx() { return st.nx; },
    get ny() { return st.ny; },
    get semilla() { return st.semilla; },
    get calidad() { return st.calidad; },
    get zoom() { return st.scale; },

    // fija estilo (paleta/calidad/capas/semilla/paises/deco/tipografías) y
    // re-renderiza. Recibe un patch parcial.
    setEstilo(patch) {
      if ("paleta" in patch) {
        st.paleta = patch.paleta;
        elVisor.style.background = FONDO_UI[st.paleta] || FONDO_UI.claro;
      }
      if ("calidad" in patch) {
        st.calidad = Math.max(1, Math.min(4, patch.calidad | 0 || 1));
        st.scale = Math.min(st.scale, zoomMax());
        acotar(); aplicar();
      }
      if ("capas" in patch) Object.assign(st.capas, patch.capas);
      if ("semilla" in patch) st.semilla = patch.semilla || d;
      if ("paises" in patch) st.paises = patch.paises;
      if ("npaises" in patch) st.npaises = patch.npaises;
      if ("fspais" in patch) st.fspais = patch.fspais;
      if ("fsciu" in patch) st.fsciu = patch.fsciu;
      if ("deco" in patch) st.deco = !!patch.deco;
      renderVisible();
    },

    // zoom por teclado/botones: f>1 acerca, f<1 aleja; centrado en el visor.
    zoomBoton(f) {
      const W = elVisor.clientWidth / 2, H = elVisor.clientHeight / 2;
      zoomEn(W, H, f);
    },
    reset() {
      st.scale = 1; st.tx = 0; st.ty = 0;
      acotar(); aplicar(); pintarPin(); renderVisible();
    },

    // modo puntería (battlemap): retícula + clic elige punto.
    setPick(activo) {
      st.pick = !!activo;
      elVisor.classList.toggle("puntear", st.pick);
    },
    setPin(rx, ry) { st.punto = { rx, ry }; pintarPin(); },
    limpiarPin() { st.punto = null; pintarPin(); },
    get punto() { return st.punto; },

    // bust de caché tras guardar rótulos.
    rotverBump() { st.rotver++; },

    // URL del render completo para exportar (deco + px).
    urlExport({ deco, px }) {
      const q = paramsBase();
      q.deco = deco ? 1 : 0;
      q.px = px;
      if (st.rotver) q.rv = st.rotver;
      return urlFantasiaRender(sello, d, q);
    },
  });
}
