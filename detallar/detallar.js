// Módulo del detallado de UN cuadro (script clásico, sin ESM: el proyecto no
// usa bundler). Reúne aquí la galería «Cuadros detallados» (PNG gigantes de un
// solo frame con geografía por ruido), el visor de clima HD interactivo (capas
// Köppen/vientos/cuencas/inspector con zoom/paneo) y los controles laterales de
// la sección «Detallar cuadro».
//
// Se expone como window.Detallar. El script inline lo inicializa con un contexto
// mínimo para no duplicar el estado del reproductor:
//   Detallar.init({
//     $, fmtMa, detenerRepro,
//     getRepro: () => ({ repro, sello, idx }),   // estado vivo del reproductor
//     setSondeo: t => { clearInterval(sondeo); sondeo = t; },
//   });
//   Detallar.pintar(lista)        -> repinta la galería de cuadros detallados
//   Detallar.habilitar(bool)      -> muestra/oculta la sección lateral según
//                                    haya corrida con checkpoints cargada
(function () {
  "use strict";

  // dependencias inyectadas desde el script inline (ver init)
  let $, fmtMa, detenerRepro, getRepro, setSondeo;

  // ---- cuadros detallados: PNG gigante de UN frame con geografía por ruido ----
  function pieDetalle(d) {
    const res = d.resolucion ? ` (${d.resolucion[0]}×${d.resolucion[1]}px)` : "";
    // los detalles viejos no traen clima ajustable: solo lo rotulamos si vino
    // (y guardan el dial con la clave "humedad"; los nuevos, "precipitaciones")
    const prec = (d.precipitaciones != null ? d.precipitaciones : d.humedad);
    const clima = "temperatura" in d
      ? ` · ${Math.round(d.temperatura * 16 + 14)} °C · precipitaciones ${Math.round(prec * 100)} %` : "";
    return `cuadro del paso ${d.paso} · ${fmtMa(d.ma || 0)} · ${d.factor}×${res}` +
      ` · ruido ${d.semilla_detalle} · casquetes ${d.casquetes} · relieve ${d.relieve}` +
      clima;
  }

  function pintarDetalles(lista) {
    const caja = $("detalles-lista");
    caja.textContent = "";
    $("detalles").hidden = !lista.length;
    for (const d of lista) {     // el servidor ya devuelve el más nuevo primero
      // detalle nuevo (con clima HD) -> visor interactivo; viejo -> como siempre
      if (d.climahd) { caja.appendChild(crearVisorHD(d)); continue; }
      const div = document.createElement("div");
      div.className = "detalle";
      div.innerHTML = `<a target="_blank"><img loading="lazy"></a>
        <div class="pie-img"></div>`;
      div.querySelector("a").href = d.png;
      div.querySelector("img").src = d.png;
      div.querySelector(".pie-img").textContent = pieDetalle(d);
      if (d.clima) {
        const a = document.createElement("a");
        a.target = "_blank"; a.href = d.clima;
        const im = document.createElement("img");
        im.loading = "lazy"; im.src = d.clima;
        a.appendChild(im);
        const pie = document.createElement("div");
        pie.className = "pie-img";
        pie.textContent = "clima del mismo cuadro: biomas, ríos, corrientes y hielo";
        div.appendChild(a);
        div.appendChild(pie);
      }
      caja.appendChild(div);
    }
  }

  // ---- visor de clima HD: base climahd + capas combinables (Köppen, vientos e
  // isoyetas, cuencas y ríos, inspector) con zoom hacia el cursor y paneo. Todas
  // las capas viven en el mismo lienzo transformado. capas.json se carga perezoso.
  function crearVisorHD(d) {
    const [nx, ny] = d.resolucion || [1024, 1024];
    const st = { scale: 1, tx: 0, ty: 0, capas: null, cargando: null,
                 insp: null, inspCargando: false };

    const wrap = document.createElement("div");
    wrap.className = "detalle detalle-hd";

    const pie = document.createElement("div");
    pie.className = "pie-img";
    pie.textContent = pieDetalle(d) + " · clima HD interactivo";

    const ctrl = document.createElement("div");
    ctrl.className = "visor-ctrl";
    ctrl.innerHTML =
      `<label><input type="checkbox" data-capa="koppen">Köppen</label>` +
      `<label><input type="checkbox" data-capa="vientos">vientos e isoyetas</label>` +
      `<label><input type="checkbox" data-capa="corrientes">corrientes marinas</label>` +
      `<label><input type="checkbox" data-capa="cuencas">cuencas y ríos</label>` +
      `<label><input type="checkbox" data-capa="paises">países</label>` +
      `<label><input type="checkbox" data-capa="civ">asentamientos, caminos y rutas</label>` +
      `<label><input type="checkbox" data-capa="inspector">inspector</label>` +
      `<button type="button" class="reset">⟲ zoom</button>` +
      `<a class="abrir" target="_blank">abrir HD</a>` +
      (d.civ ? `<a class="abrir abrir-civ" target="_blank">mapa político</a>` : "") +
      (d.regiones ? `<a class="abrir abrir-reg" target="_blank">subregiones</a>` : "");
    ctrl.querySelector(".abrir").href = d.climahd;
    if (d.civ) ctrl.querySelector(".abrir-civ").href = d.civ;
    if (d.regiones) {
      // /salidas/{sello}/detalles/{stem}_regiones.png -> /regiones?sello&d=stem
      const m = d.regiones.match(/^\/salidas\/([^/]+)\/detalles\/(.+)_regiones\.png$/);
      if (m) ctrl.querySelector(".abrir-reg").href =
        `/regiones?sello=${encodeURIComponent(m[1])}&d=${encodeURIComponent(m[2])}`;
    }

    const fila = document.createElement("div");
    fila.className = "visor-fila";

    const visor = document.createElement("div");
    visor.className = "visor";
    visor.style.aspectRatio = nx + " / " + ny;

    const lienzo = document.createElement("div");
    lienzo.className = "visor-lienzo";

    const base = new Image();
    base.className = "capa capa-base"; base.alt = "clima HD"; base.src = d.climahd;
    const koppen = new Image();
    koppen.className = "capa capa-koppen"; koppen.hidden = true;
    const cuencas = new Image();
    cuencas.className = "capa capa-cuencas"; cuencas.hidden = true;
    const paises = new Image();
    paises.className = "capa capa-paises"; paises.hidden = true;
    const cvVec = document.createElement("canvas");
    cvVec.className = "capa capa-vec"; cvVec.hidden = true;
    const cvCor = document.createElement("canvas");
    cvCor.className = "capa capa-cor"; cvCor.hidden = true;
    const cvRio = document.createElement("canvas");
    cvRio.className = "capa capa-rio"; cvRio.hidden = true;
    const cvCiv = document.createElement("canvas");
    cvCiv.className = "capa capa-civ"; cvCiv.hidden = true;
    lienzo.append(base, koppen, cuencas, paises, cvVec, cvCor, cvRio, cvCiv);

    const tip = document.createElement("div");
    tip.className = "tip-rio"; tip.hidden = true;
    visor.append(lienzo, tip);

    const lado = document.createElement("div");
    lado.className = "visor-lado";
    const insp = document.createElement("div");
    insp.className = "inspector"; insp.hidden = true;
    insp.innerHTML = `<h3>inspector</h3><div class="insp-cuerpo">` +
      `<div class="vacio">mueve el cursor sobre el mapa</div></div>`;
    const leyK = document.createElement("div");
    leyK.className = "leyenda-koppen"; leyK.hidden = true;
    const leyP = document.createElement("div");
    leyP.className = "leyenda-paises"; leyP.hidden = true;
    lado.append(insp, leyP, leyK);

    fila.append(visor, lado);
    wrap.append(pie, ctrl, fila);

    // -- carga perezosa de capas.json (primera capa encendida o primera interacción)
    function asegurarCapas() {
      if (st.capas) return Promise.resolve(st.capas);
      if (st.cargando) return st.cargando;
      st.cargando = fetch(d.capas).then(r => r.json())
        .then(j => { st.capas = j; return j; }).catch(() => null);
      return st.cargando;
    }

    // -- transformación (zoom/paneo) compartida por todas las capas
    function aplicar() {
      lienzo.style.transform =
        `translate(${st.tx}px,${st.ty}px) scale(${st.scale})`;
    }
    function acotar() {
      const W = visor.clientWidth, H = visor.clientHeight;
      const sw = W * st.scale, sh = H * st.scale;
      st.tx = sw <= W ? (W - sw) / 2 : Math.min(0, Math.max(W - sw, st.tx));
      st.ty = sh <= H ? (H - sh) / 2 : Math.min(0, Math.max(H - sh, st.ty));
    }
    function redibujar() {
      if (!cvVec.hidden) dibujarVec();
      if (!cvCor.hidden) dibujarCor();
      if (!cvRio.hidden) dibujarRio();
      if (!cvCiv.hidden) dibujarCiv();
    }

    visor.addEventListener("wheel", e => {
      e.preventDefault();
      asegurarCapas();
      const r = visor.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const wx = (mx - st.tx) / st.scale, wy = (my - st.ty) / st.scale;
      const f = e.deltaY < 0 ? 1.2 : 1 / 1.2;
      const ns = Math.min(16, Math.max(1, st.scale * f));
      st.tx = mx - wx * ns; st.ty = my - wy * ns; st.scale = ns;
      acotar(); aplicar(); redibujar();
    }, { passive: false });

    let arr = false, lx = 0, ly = 0;
    visor.addEventListener("mousedown", e => {
      arr = true; lx = e.clientX; ly = e.clientY; visor.classList.add("agarrando");
    });
    window.addEventListener("mouseup", () => {
      if (arr) { arr = false; visor.classList.remove("agarrando"); }
    });
    visor.addEventListener("mousemove", e => {
      if (arr) {
        st.tx += e.clientX - lx; st.ty += e.clientY - ly;
        lx = e.clientX; ly = e.clientY;
        acotar(); aplicar(); return;
      }
      hover(e);
    });
    visor.addEventListener("mouseleave", () => { tip.hidden = true; });

    ctrl.querySelector(".reset").onclick = () => {
      st.scale = 1; st.tx = 0; st.ty = 0; acotar(); aplicar(); redibujar();
    };

    // -- coordenadas del cursor en píxeles de render (donde viven los vectores)
    function coord(e) {
      const r = visor.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const W = visor.clientWidth, H = visor.clientHeight;
      const wx = (mx - st.tx) / st.scale, wy = (my - st.ty) / st.scale;
      return { mx, my, W, H, rx: wx * nx / W, ry: wy * ny / H };
    }

    // -- lienzo de un canvas de capa, nítido según el zoom (supermuestreo ≤8×)
    function prep(cv) {
      const W = visor.clientWidth, H = visor.clientHeight;
      const ss = Math.min(8, Math.max(1, st.scale));
      const bw = Math.max(1, Math.round(W * ss)), bh = Math.max(1, Math.round(H * ss));
      cv.style.width = W + "px"; cv.style.height = H + "px";
      cv.width = bw; cv.height = bh;
      const ctx = cv.getContext("2d");
      ctx.clearRect(0, 0, bw, bh);
      // px de pantalla -> px de backing (para grosores de línea constantes)
      const aPx = p => p * ss / st.scale;
      return { ctx, kx: bw / nx, ky: bh / ny, aPx };
    }

    function flecha(ctx, x0, y0, x1, y1, cab) {
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
      const a = Math.atan2(y1 - y0, x1 - x0);
      ctx.beginPath(); ctx.moveTo(x1, y1);
      ctx.lineTo(x1 - cab * Math.cos(a - 0.4), y1 - cab * Math.sin(a - 0.4));
      ctx.moveTo(x1, y1);
      ctx.lineTo(x1 - cab * Math.cos(a + 0.4), y1 - cab * Math.sin(a + 0.4));
      ctx.stroke();
    }

    function dibujarVec() {
      if (cvVec.hidden || !st.capas) return;
      const c = st.capas, { ctx, kx, ky, aPx } = prep(cvVec);
      // isoyetas (polilíneas azules por nivel)
      const iso = (c.isoyetas && c.isoyetas.lineas) || [];
      ctx.lineWidth = aPx(1.2); ctx.strokeStyle = "rgba(70,150,235,.85)";
      ctx.lineJoin = "round";
      for (const ln of iso) {
        const p = ln.puntos || [];
        if (p.length < 2) continue;
        ctx.beginPath(); ctx.moveTo(p[0][0] * kx, p[0][1] * ky);
        for (let i = 1; i < p.length; i++) ctx.lineTo(p[i][0] * kx, p[i][1] * ky);
        ctx.stroke();
      }
      // vientos (gris claro sobre tierra)
      const vi = c.vientos || [];
      let mv = 1e-6; for (const a of vi) mv = Math.max(mv, Math.hypot(a.u, a.v));
      const objetivo = (nx / 26) * 0.8, cab = aPx(4);
      ctx.lineWidth = aPx(1.1); ctx.strokeStyle = "rgba(210,214,224,.85)";
      for (const a of vi) {
        const L = objetivo / mv;
        flecha(ctx, a.x * kx, a.y * ky, (a.x + a.u * L) * kx, (a.y + a.v * L) * ky, cab);
      }
    }

    function dibujarCor() {
      if (cvCor.hidden || !st.capas) return;
      const c = st.capas, { ctx, kx, ky, aPx } = prep(cvCor);
      // corrientes marinas (tintadas por anomalía: cálida rojo, fría azul);
      // el grosor crece con la rapidez: las corrientes marcadas destacan
      const co = c.corrientes || [];
      let mc = 1e-6; for (const a of co) mc = Math.max(mc, Math.hypot(a.u, a.v));
      const objetivo = (nx / 26) * 0.8;
      ctx.lineCap = "round";
      for (const a of co) {
        const L = objetivo / mc;
        const rel = Math.hypot(a.u, a.v) / mc;           // 0..1 rapidez relativa
        const t = Math.max(0, Math.min(1, Math.abs(a.anom || 0)));
        ctx.lineWidth = aPx(1.8 + 2.2 * rel);
        ctx.strokeStyle = (a.anom || 0) >= 0
          ? `rgba(230,80,60,${0.5 + 0.45 * t})` : `rgba(90,150,235,${0.5 + 0.45 * t})`;
        flecha(ctx, a.x * kx, a.y * ky, (a.x + a.u * L) * kx, (a.y + a.v * L) * ky,
          aPx(4 + 3 * rel));
      }
      // circuitos (giros oceánicos): los CIRCUITOS DEL MAPA PEQUEÑO de clima
      // (el backend los calcula sobre el cuadro original, donde salen bien
      // formados) re-renderizados aquí con más calidad: curvas cuadráticas por
      // los puntos medios (lazos redondos al hacer zoom, no poligonales);
      // troceados donde cruzan el borde Este-Oeste (la longitud envuelve;
      // los polos no) para no rayar el lienzo
      ctx.lineJoin = "round";
      const traza = tr => {
        if (tr.length < 2) return;
        ctx.beginPath(); ctx.moveTo(tr[0][0] * kx, tr[0][1] * ky);
        for (let i = 1; i < tr.length - 1; i++) {
          ctx.quadraticCurveTo(tr[i][0] * kx, tr[i][1] * ky,
            (tr[i][0] + tr[i + 1][0]) / 2 * kx, (tr[i][1] + tr[i + 1][1]) / 2 * ky);
        }
        const u = tr[tr.length - 1];
        ctx.lineTo(u[0] * kx, u[1] * ky); ctx.stroke();
      };
      for (const g of (c.circuitos || [])) {
        const p = g.puntos || [];
        if (p.length < 8) continue;
        const col = (g.anom || 0) >= 0 ? "230,80,60" : "90,150,235";
        const cerr = p.concat([p[0]]);
        const tramos = [[cerr[0]]];
        for (let i = 1; i < cerr.length; i++) {
          if (Math.abs(cerr[i][0] - cerr[i - 1][0]) > nx / 2 ||
              Math.abs(cerr[i][1] - cerr[i - 1][1]) > ny / 2) tramos.push([]);
          tramos[tramos.length - 1].push(cerr[i]);
        }
        for (const pase of [[aPx(5.5), "rgba(255,255,255,.5)"],
                            [aPx(3.2), `rgba(${col},.9)`]]) {
          ctx.lineWidth = pase[0]; ctx.strokeStyle = pase[1];
          for (const tr of tramos) traza(tr);
        }
        // tres puntas de flecha marcan el sentido del giro
        ctx.strokeStyle = `rgba(${col},.95)`; ctx.lineWidth = aPx(3.2);
        for (let k = 0; k < 3; k++) {
          const i = Math.floor(k * p.length / 3), j = (i + 2) % p.length;
          if (Math.abs(p[j][0] - p[i][0]) > nx / 2 ||
              Math.abs(p[j][1] - p[i][1]) > ny / 2) continue;
          const a2 = Math.atan2((p[j][1] - p[i][1]) * ky, (p[j][0] - p[i][0]) * kx);
          const X = p[j][0] * kx, Y = p[j][1] * ky, cab = aPx(8);
          ctx.beginPath(); ctx.moveTo(X, Y);
          ctx.lineTo(X - cab * Math.cos(a2 - 0.45), Y - cab * Math.sin(a2 - 0.45));
          ctx.moveTo(X, Y);
          ctx.lineTo(X - cab * Math.cos(a2 + 0.45), Y - cab * Math.sin(a2 + 0.45));
          ctx.stroke();
        }
      }
    }

    function dibujarRio() {
      if (cvRio.hidden || !st.capas) return;
      const c = st.capas, { ctx, kx, ky, aPx } = prep(cvRio);
      ctx.strokeStyle = "rgba(40,90,180,.9)"; ctx.lineCap = "round"; ctx.lineJoin = "round";
      for (const r of (c.rios || [])) {
        const p = r.puntos || [];
        if (p.length < 2) continue;
        ctx.lineWidth = aPx(1 + 3 * Math.max(0, Math.min(1, r.caudal || 0)));
        ctx.beginPath(); ctx.moveTo(p[0][0] * kx, p[0][1] * ky);
        for (let i = 1; i < p.length; i++) ctx.lineTo(p[i][0] * kx, p[i][1] * ky);
        ctx.stroke();
      }
    }

    // -- civilización: caminos, rutas comerciales y asentamientos (un canvas)
    function poli(ctx, p, kx, ky) {
      ctx.beginPath(); ctx.moveTo(p[0][0] * kx, p[0][1] * ky);
      for (let i = 1; i < p.length; i++) ctx.lineTo(p[i][0] * kx, p[i][1] * ky);
      ctx.stroke();
    }
    // paleta de asentamientos por rango: 0 aldea, 1 pueblo, 2 ciudad, 3 capital
    const RANGO_R = [1.6, 2.6, 3.8, 5.2];
    function dibujarCiv() {
      if (cvCiv.hidden || !st.capas) return;
      const c = st.capas, { ctx, kx, ky, aPx } = prep(cvCiv);
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      // 1. caminos (marrón claro, finos)
      ctx.strokeStyle = "rgba(150,110,70,.85)"; ctx.lineWidth = aPx(1.1);
      for (const r of (c.caminos || [])) {
        if ((r.puntos || []).length >= 2) poli(ctx, r.puntos, kx, ky);
      }
      // 2. rutas comerciales: terrestres (oro, gruesas) y marítimas (turquesa, discontinuas)
      for (const r of (c.rutas || [])) {
        const p = r.puntos || [];
        if (p.length < 2) continue;
        if (r.mar) {
          ctx.setLineDash([aPx(7), aPx(5)]);
          ctx.strokeStyle = "rgba(40,180,190,.9)"; ctx.lineWidth = aPx(1.8);
        } else {
          ctx.setLineDash([]);
          ctx.strokeStyle = "rgba(220,175,50,.95)"; ctx.lineWidth = aPx(2.4);
        }
        poli(ctx, p, kx, ky);
      }
      ctx.setLineDash([]);
      // 3. asentamientos: punto por rango; capital con anillo; nombre al hacer zoom
      const asent = c.asentamientos || [];
      const escP = Math.max(1, st.scale);
      for (const a of asent) {
        const x = a.x * kx, y = a.y * ky, rr = aPx(RANGO_R[a.rango] || 1.6);
        ctx.beginPath(); ctx.arc(x, y, rr, 0, 6.2832);
        ctx.fillStyle = a.rango >= 2 ? "#f4f0e6" : "#d8d2c2";
        ctx.fill();
        ctx.lineWidth = aPx(a.rango === 3 ? 1.6 : 1.0);
        ctx.strokeStyle = a.rango === 3 ? "#b02a2a" : "#5a4632";
        ctx.stroke();
        if (a.rango === 3) {                       // anillo de capital
          ctx.beginPath(); ctx.arc(x, y, rr + aPx(2.2), 0, 6.2832);
          ctx.strokeStyle = "rgba(176,42,42,.85)"; ctx.lineWidth = aPx(1.1); ctx.stroke();
        }
        // rótulos: siempre capitales y ciudades; el resto solo con zoom
        if (a.rango >= 2 || escP >= 3.5) {
          const fs = aPx(a.rango === 3 ? 9 : 7.5);
          ctx.font = `${fs}px system-ui, sans-serif`;
          ctx.textBaseline = "middle";
          ctx.lineWidth = aPx(2.4); ctx.strokeStyle = "rgba(20,18,14,.8)";
          ctx.strokeText(a.nombre, x + rr + aPx(2), y);
          ctx.fillStyle = "#f6f3ea"; ctx.fillText(a.nombre, x + rr + aPx(2), y);
        }
      }
    }

    // -- leyenda de países desde capas.json: nombre, población por región y
    // % del suelo que domina (los detalles viejos no traen población)
    function construirLeyendaPaises() {
      if (leyP.dataset.listo || !st.capas) return;
      const ls = (st.capas.paises && st.capas.paises.lista) || [];
      if (!ls.length) { leyP.innerHTML = ""; return; }
      const tierra = st.capas.paises.tierra || 0;
      const filas = ls.slice().sort((a, b) => (b.poblacion || 0) - (a.poblacion || 0))
        .map(p => {
          const hab = p.poblacion != null
            ? `<small>${p.poblacion.toLocaleString("es")} hab.` +
              (tierra ? ` · ${(100 * p.area / tierra).toFixed(1)} % del suelo` : "") +
              `</small>` : "";
          return `<span><i class="cuad" style="background:rgb(${(p.rgb || [0, 0, 0]).join(",")})">` +
            `</i><span class="ley-pais">${p.nombre}${hab}</span></span>`;
        }).join("");
      // suelo sin reclamar (países chicos): se rotula si queda una franja real
      const reclamado = ls.reduce((s, p) => s + (p.area || 0), 0);
      const libre = tierra > 0 ? 100 * (tierra - reclamado) / tierra : 0;
      const pieLibre = libre >= 1
        ? `<span><i class="cuad" style="background:#555"></i>` +
          `<span class="ley-pais">tierras libres<small>${libre.toFixed(1)} % del suelo</small></span></span>`
        : "";
      leyP.innerHTML = `<div class="ley-tit">países</div>` + filas + pieLibre;
      leyP.dataset.listo = "1";
    }

    // -- leyenda de clases Köppen desde capas.json
    function construirLeyenda() {
      if (leyK.dataset.listo || !st.capas) return;
      const cl = (st.capas.koppen && st.capas.koppen.clases) || [];
      leyK.innerHTML = `<div class="ley-tit">Köppen</div>` + cl.map(c =>
        `<span><i class="cuad" style="background:rgb(${(c.rgb || [0, 0, 0]).join(",")})">` +
        `</i>${c.cod} · ${c.nombre}</span>`).join("");
      leyK.dataset.listo = "1";
    }

    // -- inspector: datos.png/datos2.png a canvas offscreen, getImageData una vez
    function cargarImg(url) {
      return new Promise((ok, mal) => {
        const im = new Image();
        im.onload = () => ok(im); im.onerror = mal; im.src = url;
      });
    }
    function pixeles(im) {
      const cv = document.createElement("canvas");
      cv.width = im.naturalWidth; cv.height = im.naturalHeight;
      const ctx = cv.getContext("2d");
      ctx.drawImage(im, 0, 0);
      return { d: ctx.getImageData(0, 0, cv.width, cv.height).data,
               w: cv.width, h: cv.height };
    }
    function cargarInspector() {
      if (st.insp || st.inspCargando || !d.datos || !d.datos2) return;
      st.inspCargando = true;
      Promise.all([cargarImg(d.datos), cargarImg(d.datos2)])
        .then(([a, b]) => { st.insp = { a: pixeles(a), b: pixeles(b) }; })
        .catch(() => {});
    }
    const CUAL_T = ["muy fría", "fría", "templada", "cálida", "muy cálida"];
    const CUAL_LL = ["árida", "seca", "media", "húmeda", "muy húmeda"];
    const CUAL_ALT = ["baja", "media", "alta", "muy alta"];
    function cual(t, etq) {
      return etq[Math.min(etq.length - 1, Math.max(0, Math.floor(t * etq.length)))];
    }
    function muestra(P, rx, ry) {
      let x = Math.floor(rx * P.w / nx), y = Math.floor(ry * P.h / ny);
      x = Math.max(0, Math.min(P.w - 1, x)); y = Math.max(0, Math.min(P.h - 1, y));
      const o = (y * P.w + x) * 4; return [P.d[o], P.d[o + 1], P.d[o + 2]];
    }
    function filaDato(rot, val) {
      return `<div class="fila-dato"><span>${rot}</span><b>${val}</b></div>`;
    }
    function actualizarInspector(c) {
      if (!st.insp || !st.capas) return;
      const esc = st.capas.escalas || {};
      const [tr, tp, ta] = muestra(st.insp.a, c.rx, c.ry);   // tair, precip, alt
      const [bi, ko, hi] = muestra(st.insp.b, c.rx, c.ry);   // bioma, köppen, hielo
      const mar = bi === 255;
      const tair = esc.tair
        ? esc.tair[0] + (tr / 255) * (esc.tair[1] - esc.tair[0]) : tr / 255;
      // tair abstracto -> °C con el mismo mapeo del pie (14 °C = 0, escala 16)
      const tempC = tair * 16 + 14;
      const precip = tp / 255, alt = ta / 255, hielo = hi / 255;
      const bioma = mar ? "mar"
        : (((st.capas.biomas || []).find(x => x.id === bi) || {}).nombre || `#${bi}`);
      let kop = "mar";
      if (!mar) {
        const k = ((st.capas.koppen && st.capas.koppen.clases) || []).find(x => x.id === ko);
        kop = k ? `${k.cod} · ${k.nombre}` : `#${ko}`;
      }
      const hlab = hielo > 0.5 ? "hielo permanente" : hielo > 0.05 ? "algo de hielo" : "sin hielo";
      insp.querySelector(".insp-cuerpo").innerHTML =
        filaDato("bioma", bioma) + filaDato("Köppen", kop) +
        filaDato("temperatura", `${tempC.toFixed(1)} °C · ${cual(tr / 255, CUAL_T)}`) +
        filaDato("lluvia", `${Math.round(precip * 100)} % · ${cual(precip, CUAL_LL)}`) +
        filaDato("altitud", mar ? "— (mar)" : `${Math.round(alt * 100)} % · ${cual(alt, CUAL_ALT)}`) +
        filaDato("hielo", `${Math.round(hielo * 100)} % · ${hlab}`);
    }

    // -- hover: inspector + tooltip de río bajo el cursor
    function distSeg2(px, py, a, b) {
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const l = dx * dx + dy * dy || 1e-9;
      let t = ((px - a[0]) * dx + (py - a[1]) * dy) / l;
      t = Math.max(0, Math.min(1, t));
      const cx = a[0] + t * dx, cy = a[1] + t * dy;
      return (px - cx) ** 2 + (py - cy) ** 2;
    }
    const RANGO_NOM = ["aldea", "pueblo", "ciudad", "capital"];
    function hover(e) {
      const c = coord(e);
      if (!insp.hidden) actualizarInspector(c);
      // 1. asentamiento bajo el cursor (tiene prioridad sobre el río)
      if (!cvCiv.hidden && st.capas) {
        const tolA = 9 * nx / (c.W * st.scale);
        let mejor = null, md = tolA * tolA;
        for (const a of (st.capas.asentamientos || [])) {
          const dd = (c.rx - a.x) ** 2 + (c.ry - a.y) ** 2;
          if (dd < md) { md = dd; mejor = a; }
        }
        if (mejor) {
          const ls = (st.capas.paises && st.capas.paises.lista) || [];
          const p = ls.find(x => x.id === mejor.pais);
          tip.hidden = false; tip.style.left = c.mx + "px"; tip.style.top = c.my + "px";
          tip.textContent = `${mejor.nombre} · ${RANGO_NOM[mejor.rango]} · ` +
            `${mejor.poblacion.toLocaleString("es")} hab.` + (p ? ` · ${p.nombre}` : "");
          return;
        }
      }
      // 2. río bajo el cursor
      if (!cvRio.hidden && st.capas) {
        const tol = 6 * nx / (c.W * st.scale);   // 6 px de pantalla en px de render
        let best = null, bd = tol * tol;
        for (const r of (st.capas.rios || [])) {
          const p = r.puntos || [];
          for (let i = 1; i < p.length; i++) {
            const dd = distSeg2(c.rx, c.ry, p[i - 1], p[i]);
            if (dd < bd) { bd = dd; best = r; }
          }
        }
        if (best) {
          tip.hidden = false; tip.style.left = c.mx + "px"; tip.style.top = c.my + "px";
          tip.textContent = `${best.nombre} · caudal ${(best.caudal || 0).toFixed(2)}`;
          return;
        }
      }
      tip.hidden = true;
    }

    // -- toggles independientes y combinables
    ctrl.addEventListener("change", e => {
      const cb = e.target;
      if (!cb.dataset || !cb.dataset.capa) return;
      const capa = cb.dataset.capa, on = cb.checked;
      asegurarCapas().then(() => {
        if (capa === "koppen") {
          if (on && d.koppen && !koppen.src) koppen.src = d.koppen;
          koppen.hidden = !(on && d.koppen);
          leyK.hidden = !on; if (on) construirLeyenda();
        } else if (capa === "vientos") {
          cvVec.hidden = !on; if (on) dibujarVec();
        } else if (capa === "corrientes") {
          cvCor.hidden = !on; if (on) dibujarCor();
        } else if (capa === "cuencas") {
          if (on && d.cuencas && !cuencas.src) cuencas.src = d.cuencas;
          cuencas.hidden = !(on && d.cuencas);
          cvRio.hidden = !on; if (on) dibujarRio(); else tip.hidden = true;
        } else if (capa === "paises") {
          if (on && d.paises && !paises.src) paises.src = d.paises;
          paises.hidden = !(on && d.paises);
          leyP.hidden = !on; if (on) construirLeyendaPaises();
        } else if (capa === "civ") {
          cvCiv.hidden = !on; if (on) dibujarCiv(); else tip.hidden = true;
        } else if (capa === "inspector") {
          insp.hidden = !on; if (on) cargarInspector();
        }
      });
    });

    aplicar();
    // detalle con civilización: países + asentamientos encendidos de entrada
    // (los detalles previos a la capa civ no traen d.civ y quedan como antes)
    if (d.civ) {
      for (const nombre of ["paises", "civ"]) {
        const cb = ctrl.querySelector(`input[data-capa="${nombre}"]`);
        cb.checked = true;
        cb.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    return wrap;
  }

  // ---- controles laterales «Detallar cuadro»: detalla el cuadro pausado del
  // reproductor (PNG gigante con geografía menor por ruido); no toca la corrida.
  function conectarControles() {
    $("det-casq").addEventListener("input",
      () => $("v-det-casq").textContent = $("det-casq").value);
    $("det-relieve").addEventListener("input",
      () => $("v-det-relieve").textContent = parseFloat($("det-relieve").value).toFixed(1));
    $("det-sinu").addEventListener("input",
      () => $("v-det-sinu").textContent = parseFloat($("det-sinu").value).toFixed(1));
    $("det-temp").addEventListener("input",
      () => $("v-det-temp").textContent = $("det-temp").value);
    $("det-prec").addEventListener("input",
      () => $("v-det-prec").textContent = $("det-prec").value);

    // salidas de la sección «Detallar con civilización» (0 = automático)
    $("civ-asent").addEventListener("input", () => {
      const v = parseInt($("civ-asent").value);
      $("v-civ-asent").textContent = v ? String(v) : "auto";
    });
    $("civ-paises").addEventListener("input", () => {
      const v = parseInt($("civ-paises").value);
      $("v-civ-paises").textContent = v ? String(v) : "auto";
    });

    // lanzamiento compartido por ambas secciones: POST /api/detallar + sondeo.
    // `extra` aporta los diales propios (factor/semilla y, en la sección de
    // civilización, semilla_civ/asentamientos/paises); casquetes, relieve,
    // sinuosidad, temperatura y precipitaciones salen SIEMPRE de «Detallar cuadro».
    async function lanzarDetalle(boton, extra, rotulo) {
      const { repro, sello, idx } = getRepro();
      if (!repro || !sello) return;
      const f = repro.frames[idx];
      detenerRepro();
      boton.disabled = true;
      $("estado").className = "";
      $("estado").textContent =
        `${rotulo} el cuadro de ${fmtMa(f.ma)} a ${extra.factor}×…`;
      $("barra").hidden = false;
      let res;
      try {
        res = await (await fetch("/api/detallar", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(Object.assign({
            sello: sello, paso: f.paso,
            casquetes: parseFloat($("det-casq").value),
            relieve: parseFloat($("det-relieve").value),
            sinuosidad: parseFloat($("det-sinu").value),
            // diales reales de la UI -> dial abstracto que espera el backend:
            // °C -> temperatura en [-1,1] (14 °C = 0), % -> precipitaciones en [0.2,2]
            temperatura: Math.max(-1, Math.min(1, (parseFloat($("det-temp").value) - 14) / 16)),
            precipitaciones: parseFloat($("det-prec").value) / 100,
          }, extra)),
        })).json();
      } catch (e) { res = { error: "sin conexión" }; }
      if (res.error) {
        $("estado").textContent = "No se pudo detallar: " + res.error;
        $("estado").className = "error";
        boton.disabled = false; $("barra").hidden = true; return;
      }
      const t0 = Date.now();
      setSondeo(setInterval(async () => {
        const e = await (await fetch("/api/estado?id=" + res.id)).json();
        const segs = Math.round((Date.now() - t0) / 1000);
        $("barra").firstElementChild.style.width = (e.progreso * 100) + "%";
        if (e.estado === "corriendo") {
          $("estado").textContent = `${rotulo}… ${segs} s`;
          return;
        }
        setSondeo(null);
        boton.disabled = false; $("barra").hidden = true;
        if (e.estado === "listo") {
          $("estado").textContent =
            `Cuadro de ${fmtMa(f.ma)} detallado en ${segs} s.`;
          pintarDetalles(e.detalles || []);
          $("detalles").scrollIntoView({ behavior: "smooth" });
        } else {
          $("estado").textContent = "El detallado falló.";
          $("estado").className = "error"; $("log").textContent = e.log || "";
        }
      }, 700));
    }

    $("b-detalle").onclick = () => lanzarDetalle($("b-detalle"), {
      factor: parseInt($("det-factor").value),
      semilla: Math.max(0, parseInt($("det-semilla").value) || 0),
    }, "Detallando");

    $("b-civilizar").onclick = () => lanzarDetalle($("b-civilizar"), {
      factor: parseInt($("civ-factor").value),
      semilla: Math.max(0, parseInt($("civ-semilla").value) || 0),
      semilla_civ: Math.max(0, parseInt($("civ-semciv").value) || 0),
      asentamientos: Math.max(0, parseInt($("civ-asent").value) || 0),
      paises: Math.max(0, parseInt($("civ-paises").value) || 0),
      tam_paises: Math.max(0, parseInt($("civ-tam").value) || 0),
    }, "Civilizando");
  }

  // muestra u oculta las secciones laterales según haya corrida con checkpoints
  function habilitar(extrapolable) {
    $("sec-detallar").hidden = !extrapolable;
    $("sec-civilizar").hidden = !extrapolable;
  }

  function init(ctx) {
    $ = ctx.$; fmtMa = ctx.fmtMa; detenerRepro = ctx.detenerRepro;
    getRepro = ctx.getRepro; setSondeo = ctx.setSondeo;
    conectarControles();
  }

  window.Detallar = { init, pintar: pintarDetalles, habilitar };
})();
