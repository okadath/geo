"""Render del mapa de fantasia en el servidor (PIL + numpy).

Portea a Python el render procedural que antes vivia en `fantasia.html`
(pergamino, mar por distancia a costa, glifos de relieve/vegetacion, rios,
caminos, asentamientos, rotulos y decoracion). El navegador queda como visor
delgado: pide PNG a estos endpoints y solo compone la imagen. Asi la logica
propietaria de dibujo no viaja al cliente (protegible, pasarela de pago y
cliente APK a futuro).

Expone, para el enchufe de `web.py`:
    manejar_get(handler, url) -> bool
    manejar_post(handler, ruta, datos) -> bool

Endpoints:
    GET /api/fantasia/render?sello&d&calidad&semilla&paleta&capas&deco
        -> PNG del mapa completo a la resolucion de trabajo.
    GET /api/fantasia/sector?sello&d&...&cx&cy&w&h  (o &z)
        -> PNG re-horneado de una ventana de mundo (nitido a cualquier zoom).

Los renders se cachean en disco por hash de parametros en
    salidas/<sello>/detalles/fantasia_cache/
y se sirven con cache=True para que el paneo/zoom sea usable.

Geometria: el mundo envuelve solo en X; los polos son borde (nunca wrap en Y).
Solo se usa biblioteca estandar + numpy + Pillow.
"""
import hashlib
import math
import os
import re
import threading
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
SALIDAS = BASE / "salidas"

RE_SELLO = re.compile(r"^[0-9]{8}-[0-9]{6}(?:-[0-9]+)?$")
RE_STEM = re.compile(r"^d[0-9]{6}_f[0-9]+_[0-9a-f]{6}$")

CAPAS_VALIDAS = ("relieve", "veg", "rios", "caminos", "asent", "rotulos", "tinte")
PALETAS_VALIDAS = ("claro", "sepia", "noche")

_LOCK = threading.Lock()
_CACHE_DATOS = {}     # (sello,stem) -> (mtime, dict con arrays y capas)
_CACHE_GLIFOS = {}    # (sello,stem,semilla,calidad) -> lista de glifos
_CACHE_FUENTES = {}   # (clase,px) -> ImageFont

# ==========================================================================
#  paletas de estilo (portadas de fantasia.html)
#  Los colores hex se guardan como tuplas RGB; los rgba con alfa aparte.
# ==========================================================================
def _hx(s):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


PALETAS = {
    "claro": {
        "papelA": (233, 220, 189), "papelB": (214, 197, 158), "marco": (120, 96, 58),
        "mar": (188, 206, 205), "marHondo": (150, 176, 178), "agua": (150, 174, 176),
        "tinta": (74, 59, 40), "costa": (92, 74, 48),
        "montF": (224, 210, 176), "montI": (92, 74, 48), "montS": (176, 158, 120),
        "colina": (106, 86, 54), "veg": (76, 103, 47), "conif": (61, 90, 52),
        "desierto": (165, 138, 82),
        "rio": (63, 93, 120), "texto": (64, 49, 28),
        "textoHalo": (236, 226, 198, 217), "mareText": (77, 113, 128),
        "hielo": (143, 166, 176), "vineta": (70, 52, 28, 87), "fondoUI": (233, 220, 191),
    },
    "sepia": {
        "papelA": (220, 199, 154), "papelB": (196, 172, 124), "marco": (96, 72, 40),
        "mar": (199, 181, 142), "marHondo": (176, 156, 116), "agua": (168, 148, 108),
        "tinta": (67, 51, 31), "costa": (78, 58, 32),
        "montF": (210, 190, 148), "montI": (74, 55, 32), "montS": (168, 146, 104),
        "colina": (90, 68, 31), "veg": (95, 86, 38), "conif": (76, 70, 32),
        "desierto": (154, 130, 74),
        "rio": (90, 74, 42), "texto": (58, 43, 22),
        "textoHalo": (226, 208, 166, 217), "mareText": (106, 90, 46),
        "hielo": (176, 160, 114), "vineta": (52, 36, 16, 107), "fondoUI": (220, 199, 154),
    },
    "noche": {
        "papelA": (43, 58, 77), "papelB": (32, 45, 61), "marco": (150, 172, 196),
        "mar": (22, 34, 47), "marHondo": (14, 24, 35), "agua": (58, 82, 106),
        "tinta": (198, 212, 226), "costa": (150, 172, 196),
        "montF": (53, 72, 93), "montI": (205, 216, 228), "montS": (36, 50, 66),
        "colina": (159, 179, 200), "veg": (126, 160, 122), "conif": (111, 154, 114),
        "desierto": (162, 152, 106),
        "rio": (111, 159, 208), "texto": (219, 230, 241),
        "textoHalo": (16, 26, 38, 209), "mareText": (147, 182, 204),
        "hielo": (188, 204, 220), "vineta": (6, 12, 20, 140), "fondoUI": (34, 48, 63),
    },
}


# ==========================================================================
#  PRNG determinista y ruido de valor (portados 1:1 de fantasia.html)
# ==========================================================================
def hash_str(s):
    """FNV-1a 32 bit (identico a hashStr del front)."""
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF
    return h & 0xFFFFFFFF


def _imul(a, b):
    return (a * b) & 0xFFFFFFFF


class Mulberry32:
    """Generador identico a mulberry32(a) del front; misma semilla -> misma
    secuencia de flotantes en [0,1)."""
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a & 0xFFFFFFFF

    def __call__(self):
        self.a = (self.a + 0x6D2B79F5) & 0xFFFFFFFF
        a = self.a
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        t &= 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0


def _h2_vec(x, y, s):
    """Ruido de valor por celda (vectorizado; identico a h2 del front)."""
    x = x.astype(np.int64)
    y = y.astype(np.int64)
    n = (x * 374761393 + y * 668265263 + s * 362437) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) & 0xFFFFFFFF
    n = (n * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFFFF) / 4294967296.0


def _vnoise(x, y, s):
    """Ruido de valor interpolado (smoothstep), vectorizado sobre grillas."""
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = x - x0
    fy = y - y0
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    c00 = _h2_vec(x0, y0, s)
    c10 = _h2_vec(x0 + 1, y0, s)
    c01 = _h2_vec(x0, y0 + 1, s)
    c11 = _h2_vec(x0 + 1, y0 + 1, s)
    return (c00 * (1 - fx) * (1 - fy) + c10 * fx * (1 - fy) +
            c01 * (1 - fx) * fy + c11 * fx * fy)


# ==========================================================================
#  carga de datos del detalle (cacheada en memoria por mtime)
# ==========================================================================
def _cargar_datos(sello, stem):
    import json
    carpeta = SALIDAS / sello / "detalles"
    fcapas = carpeta / f"{stem}_capas.json"
    fd2 = carpeta / f"{stem}_datos2.png"
    if not fcapas.exists() or not fd2.exists():
        return None
    mt = max(fcapas.stat().st_mtime, fd2.stat().st_mtime)
    clave = (sello, stem)
    with _LOCK:
        hit = _CACHE_DATOS.get(clave)
        if hit and hit[0] == mt:
            return hit[1]

    capas = json.loads(fcapas.read_text(encoding="utf-8"))
    nx, ny = capas.get("resolucion", [1536, 1536])
    d2 = np.asarray(Image.open(fd2).convert("RGB"))     # (H,W,3)
    ndy, ndx = d2.shape[0], d2.shape[1]
    bioma = d2[:, :, 0]                                  # canal R (255 = mar)
    hielo = d2[:, :, 2].astype(np.float32) / 255.0       # canal B
    # altura del canal B de _datos.png (relieve mont/colina); opcional
    fd = carpeta / f"{stem}_datos.png"
    if fd.exists():
        d1 = np.asarray(Image.open(fd).convert("RGB"))
        altura = d1[:, :, 2].astype(np.float32) / 255.0
    else:
        altura = np.full((ndy, ndx), 0.5, np.float32)
    # raster de ids de subregiones (para centroides de rotulos y tinte)
    ids = None
    rw = rh = 0
    freg = carpeta / f"{stem}_regiones.png"
    if freg.exists():
        reg = np.asarray(Image.open(freg).convert("RGB")).astype(np.uint32)
        ids = reg[:, :, 0] | (reg[:, :, 1] << 8)
        rh, rw = ids.shape

    d = {
        "capas": capas, "nx": int(nx), "ny": int(ny),
        "ndx": ndx, "ndy": ndy, "bioma": bioma, "hielo": hielo, "altura": altura,
        "ids": ids, "rw": rw, "rh": rh,
        "esmar": (bioma == 255),
    }
    with _LOCK:
        _CACHE_DATOS[clave] = (mt, d)
    return d


# muestreadores escalares (coords en pixeles de 'resolucion')
def _dpx(d, x, y):
    px = int(x * d["ndx"] / d["nx"])
    py = int(y * d["ndy"] / d["ny"])
    if px < 0:
        px = 0
    elif px >= d["ndx"]:
        px = d["ndx"] - 1
    if py < 0:
        py = 0
    elif py >= d["ndy"]:
        py = d["ndy"] - 1
    return px, py


# ==========================================================================
#  fuentes (Georgia/Times de Windows; fallback a la de PIL)
# ==========================================================================
def _fuente(clase, px):
    px = max(6, int(round(px)))
    clave = (clase, px)
    hit = _CACHE_FUENTES.get(clave)
    if hit:
        return hit
    wf = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    candidatos = {
        "serif": ["georgia.ttf", "times.ttf"],
        "italic": ["georgiai.ttf", "timesi.ttf"],
        "bold": ["georgiab.ttf", "timesbd.ttf"],
        "fantasy": ["constanb.ttf", "constan.ttf", "georgiab.ttf", "times.ttf"],
    }.get(clase, ["georgia.ttf"])
    fnt = None
    for nombre in candidatos:
        try:
            fnt = ImageFont.truetype(str(wf / nombre), px)
            break
        except OSError:
            continue
    if fnt is None:
        fnt = ImageFont.load_default()
    _CACHE_FUENTES[clave] = fnt
    return fnt


def _mezcla(c, otro, a):
    """Mezcla opaca de color `c` sobre `otro` con alfa `a` (0..1)."""
    return (int(c[0] * a + otro[0] * (1 - a)),
            int(c[1] * a + otro[1] * (1 - a)),
            int(c[2] * a + otro[2] * (1 - a)))


# ==========================================================================
#  base de pergamino + mar + waterlines (numpy)
# ==========================================================================
def _construir_base(d, pal, win, calidad, workres):
    """Devuelve una imagen PIL RGB del tamano de salida (outW,outH) con el
    pergamino, el mar por distancia a costa y las waterlines de la ventana
    `win` = (x0,y0,w,h) en coords de mundo. Umbrales en unidades de mundo
    (calibrados a la base clasica de 512 px), asi el dibujo es identico en
    cualquier sector."""
    nx, ny = d["nx"], d["ny"]
    x0, y0, w, h = win
    outW = workres
    outH = max(1, int(round(outW * h / w)))

    u0 = nx / 512.0
    zf = math.sqrt(max(1.0, nx / w))
    costaW = 1.6 * u0 / zf
    profW = 26.0 * u0
    bandasW = (3.2 * u0, 7.4 * u0, 12.0 * u0)
    marg = profW + 2 * u0
    ex0, ey0 = x0 - marg, y0 - marg
    ew, eh = w + 2 * marg, h + 2 * marg

    BW = min(1536, max(640, workres // 2))
    BH = max(1, int(round(BW * eh / ew)))
    cel = ew / BW
    anchoW = max(0.55 * u0 / zf, cel * 0.9)

    # coords de mundo del centro de cada celda de la base extendida
    wx = ex0 + (np.arange(BW) + 0.5) * cel
    wy = ey0 + (np.arange(BH) + 0.5) * cel
    WX, WY = np.meshgrid(wx, wy)

    # fraccion de mar bilineal (costa suave, sin escalera del raster)
    marfrac = _marfrac_grid(d, WX, WY)
    land = (marfrac < 0.5)

    dist = _chamfer(land, cel)     # distancia (mundo) del mar a la costa

    # manchas de pergamino: dos ruidos suaves anclados al mundo
    bl1, bl2 = nx / 64.0, nx / 16.0
    n = (_vnoise(WX / bl1, WY / bl1, 11) * 0.6 +
         _vnoise(WX / bl2, WY / bl2, 7) * 0.4)

    img = np.zeros((BH, BW, 3), np.float32)
    pA = np.array(pal["papelA"], np.float32)
    pB = np.array(pal["papelB"], np.float32)
    mr = np.array(pal["mar"], np.float32)
    mh = np.array(pal["marHondo"], np.float32)
    ag = np.array(pal["agua"], np.float32)
    co = np.array(pal["costa"], np.float32)

    # tierra: pergamino
    n3 = n[:, :, None]
    tierra = pA[None, None, :] + (pB - pA)[None, None, :] * n3
    # mar: degradado por distancia
    t = np.clip(dist / profW, 0, 1)[:, :, None]
    mar = mr[None, None, :] + (mh - mr)[None, None, :] * t
    # costa entintada
    costa_mask = dist <= costaW
    mar[costa_mask] = co
    # waterlines concentricas
    wl = np.zeros_like(dist, bool)
    for b in bandasW:
        wl |= (np.abs(dist - b) < anchoW)
    wl &= ~costa_mask
    mar[wl] = (ag * 0.82)[None, :]
    # ruido leve sobre el mar
    nn = (n - 0.5) * 8
    mar = mar + nn[:, :, None]

    img = np.where(land[:, :, None], tierra, mar)
    img = np.clip(img, 0, 255).astype(np.uint8)
    base_ext = Image.fromarray(img, "RGB")

    # recorte de la ventana `win` dentro de la base extendida y escalado a salida
    px_x0 = (x0 - ex0) / cel
    px_y0 = (y0 - ey0) / cel
    px_x1 = (x0 + w - ex0) / cel
    px_y1 = (y0 + h - ey0) / cel
    base = base_ext.resize((outW, outH), Image.BILINEAR,
                           box=(px_x0, px_y0, px_x1, px_y1))
    return base, outW, outH


def _marfrac_grid(d, WX, WY):
    """Fraccion de mar con muestreo bilineal sobre grillas de coords de mundo."""
    ndx, ndy, nx, ny = d["ndx"], d["ndy"], d["nx"], d["ny"]
    gx = WX * ndx / nx - 0.5
    gy = WY * ndy / ny - 0.5
    x0 = np.floor(gx).astype(np.int64)
    y0 = np.floor(gy).astype(np.int64)
    fx = gx - x0
    fy = gy - y0
    mar = d["esmar"]

    def s(xx, yy):
        xx = np.clip(xx, 0, ndx - 1)
        yy = np.clip(yy, 0, ndy - 1)
        return mar[yy, xx].astype(np.float32)

    return (s(x0, y0) * (1 - fx) * (1 - fy) + s(x0 + 1, y0) * fx * (1 - fy) +
            s(x0, y0 + 1) * (1 - fx) * fy + s(x0 + 1, y0 + 1) * fx * fy)


def _chamfer(land, cel):
    """Distancia aproximada (en unidades de mundo) del mar a la costa, por
    chamfer 2 pasadas vectorizado por filas. La propagacion horizontal
    ortogonal (peso 1) se resuelve con el truco de minimo acumulado
    (dist[x]=min_k dist[k]+(x-k)); vertical y diagonales usan la fila vecina.
    Da un resultado visualmente equivalente al chamfer del front."""
    BH, BW = land.shape
    INF = 1e9
    dist = np.where(land, 0.0, INF).astype(np.float64)
    idx = np.arange(BW, dtype=np.float64)

    def horiz_lr(row):
        g = row - idx
        return np.minimum.accumulate(g) + idx

    def horiz_rl(row):
        g = row + idx
        return np.minimum.accumulate(g[::-1])[::-1] - idx

    def shift_r(a):
        out = np.empty_like(a)
        out[0] = INF
        out[1:] = a[:-1]
        return out

    def shift_l(a):
        out = np.empty_like(a)
        out[-1] = INF
        out[:-1] = a[1:]
        return out

    # pasada hacia adelante (arriba->abajo, izq->der)
    for y in range(BH):
        row = dist[y]
        if y > 0:
            prev = dist[y - 1]
            row = np.minimum(row, prev + 1)
            row = np.minimum(row, shift_r(prev) + 1.41421356)
            row = np.minimum(row, shift_l(prev) + 1.41421356)
        dist[y] = horiz_lr(row)
    # pasada hacia atras (abajo->arriba, der->izq)
    for y in range(BH - 1, -1, -1):
        row = dist[y]
        if y < BH - 1:
            nxt = dist[y + 1]
            row = np.minimum(row, nxt + 1)
            row = np.minimum(row, shift_r(nxt) + 1.41421356)
            row = np.minimum(row, shift_l(nxt) + 1.41421356)
        dist[y] = horiz_rl(row)
    return dist * cel


# ==========================================================================
#  tinte politico (imagen pequena, pais -> color)
# ==========================================================================
def _construir_tinte(d):
    if d["ids"] is None:
        return None
    capas = d["capas"]
    sr = capas.get("subregiones", {})
    id_pais = {}
    for t in sr.get("tierra", []):
        id_pais[t["id"]] = t.get("pais")
    pais_rgb = {}
    for p in (capas.get("paises", {}).get("lista", [])):
        pais_rgb[p["id"]] = p["rgb"]

    TW = TH = 384
    ids = d["ids"]
    rh, rw = ids.shape
    ys = (np.arange(TH) * rh / TH).astype(np.int64)
    xs = (np.arange(TW) * rw / TW).astype(np.int64)
    sub = ids[np.ix_(ys, xs)]
    out = np.zeros((TH, TW, 4), np.uint8)
    # mapear id->rgb del pais
    unicos = np.unique(sub)
    for uid in unicos:
        uid = int(uid)
        if uid == 0 or uid not in id_pais:
            continue
        rgb = pais_rgb.get(id_pais[uid])
        if not rgb:
            continue
        m = (sub == uid)
        out[m, 0] = rgb[0]
        out[m, 1] = rgb[1]
        out[m, 2] = rgb[2]
        out[m, 3] = 255
    return Image.fromarray(out, "RGBA")


# ==========================================================================
#  glifos de relieve y vegetacion (dependientes de la semilla) — cacheados
# ==========================================================================
def _construir_glifos(d, sello, stem, semilla, calidad):
    clave = (sello, stem, semilla, calidad)
    with _LOCK:
        hit = _CACHE_GLIFOS.get(clave)
    if hit is not None:
        return hit

    rnd = Mulberry32(hash_str(semilla + "|" + stem))
    nx, ny, K = d["nx"], d["ny"], calidad
    bioma, altura, hielo = d["bioma"], d["altura"], d["hielo"]
    esmar = d["esmar"]
    ndx, ndy = d["ndx"], d["ndy"]
    g = []

    def muestra(x, y):
        px = int(x * ndx / nx)
        py = int(y * ndy / ny)
        px = 0 if px < 0 else (ndx - 1 if px >= ndx else px)
        py = 0 if py < 0 else (ndy - 1 if py >= ndy else py)
        return px, py

    # --- relieve ---
    pasoR = max(6.0, max(20.0, nx / 64.0) / K)
    gy = pasoR * 0.5
    while gy < ny:
        gx = pasoR * 0.5
        while gx < nx:
            jx = gx + (rnd() - 0.5) * pasoR * 0.85
            jy = gy + (rnd() - 0.5) * pasoR * 0.85
            gx += pasoR
            if jx < 4 or jy < 4 or jx > nx - 4 or jy > ny - 4:
                continue
            px, py = muestra(jx, jy)
            if esmar[py, px]:
                continue
            a = float(altura[py, px])
            r0 = rnd()
            if a > 0.62:
                if r0 < 0.15:
                    continue
                s = pasoR * (0.42 + a * 0.55) * (0.8 + rnd() * 0.4)
                g.append((jy, "mont", jx, s, rnd(), "rel"))
            elif a > 0.40:
                if r0 < 0.45:
                    continue
                s = pasoR * (0.30 + a * 0.30)
                g.append((jy, "col", jx, s, rnd(), "rel"))
        gy += pasoR

    # --- vegetacion / cobertura ---
    pasoV = max(4.0, max(14.0, nx / 96.0) / K)
    gy = pasoV * 0.5
    while gy < ny:
        gx = pasoV * 0.5
        while gx < nx:
            jx = gx + (rnd() - 0.5) * pasoV * 0.8
            jy = gy + (rnd() - 0.5) * pasoV * 0.8
            gx += pasoV
            if jx < 4 or jy < 4 or jx > nx - 4 or jy > ny - 4:
                continue
            px, py = muestra(jx, jy)
            if esmar[py, px]:
                continue
            b = int(bioma[py, px])
            a = float(altura[py, px])
            hi = float(hielo[py, px])
            r0 = rnd()
            kind = None
            dens = 0.0
            if b == 0 or hi > 0.5:
                kind, dens = "hielo", 0.55
            elif b == 2:
                kind, dens = "conif", 0.55
            elif b == 10 or b == 7:
                kind, dens = "arbol", 0.62
            elif b == 8:
                kind, dens = "arbol", 0.40
            elif b == 9:
                kind, dens = "arbol", 0.22
            elif b == 4 or b == 5:
                kind, dens = "duna", 0.30
            if not kind or r0 > dens:
                continue
            if kind != "hielo" and a > 0.66:
                continue
            s = pasoV * (0.5 + rnd() * 0.5)
            g.append((jy, kind, jx, s, rnd(), "veg"))
        gy += pasoV

    g.sort(key=lambda p: p[0])     # pintar de fondo a frente (por y)
    with _LOCK:
        _CACHE_GLIFOS[clave] = g
    return g


# ==========================================================================
#  dibujo de glifos individuales (coords ya en pixel de salida)
# ==========================================================================
def _poly(dr, pts, fill=None, outline=None, w=1):
    if fill is not None:
        dr.polygon(pts, fill=fill)
    if outline is not None:
        dr.line(pts + [pts[0]], fill=outline, width=max(1, int(round(w))),
                joint="curve")


def _glifo_mont(dr, x, y, s, r, pal):
    jag = (r - 0.5) * s * 0.4
    apx, apy = x + jag, y - s * 1.35
    _poly(dr, [(x - s, y), (apx, apy), (x + s, y)], fill=pal["montF"])
    _poly(dr, [(apx, apy), (x + s, y), (x + s * 0.28, y)], fill=pal["montS"])
    dr.line([(x - s, y), (apx, apy), (x + s, y)], fill=pal["montI"],
            width=max(1, int(round(s * 0.09))), joint="curve")
    dr.line([(apx, apy), (x + jag * 0.4 - s * 0.14, y - s * 0.35)],
            fill=pal["montI"], width=max(1, int(round(s * 0.06))))


def _arc(dr, x, y, rx, ry, a0, a1, fill, w):
    dr.arc([x - rx, y - ry, x + rx, y + ry], a0, a1, fill=fill,
           width=max(1, int(round(w))))


def _glifo_col(dr, x, y, s, pal):
    _arc(dr, x, y, s, s, 184, 356, pal["colina"], s * 0.12)


def _glifo_arbol(dr, x, y, s, pal):
    s *= 0.9
    veg = pal["veg"]
    dr.line([(x, y), (x, y - s * 0.6)], fill=veg, width=max(1, int(round(s * 0.18))))
    r = s * 0.6
    cy = y - s * 1.1
    dr.ellipse([x - r, cy - r, x + r, cy + r], outline=veg,
               fill=_mezcla(veg, pal["papelA"], 0.30), width=1)


def _glifo_conif(dr, x, y, s, pal):
    conif = pal["conif"]
    _poly(dr, [(x, y - s * 1.5), (x - s * 0.55, y), (x + s * 0.55, y)],
          fill=_mezcla(conif, pal["papelA"], 0.32), outline=conif, w=s * 0.1)


def _glifo_duna(dr, x, y, s, pal):
    s *= 0.8
    des = pal["desierto"]
    _arc(dr, x, y, s * 0.7, s * 0.7, 194, 346, des, s * 0.14)
    _arc(dr, x + s * 0.5, y + s * 0.4, s * 0.4, s * 0.4, 194, 346, des, s * 0.14)


def _glifo_hielo(dr, x, y, s, pal):
    hi = _mezcla(pal["hielo"], pal["papelA"], 0.7)
    w = max(1, int(round(s * 0.09)))
    dr.line([(x - s * 0.7, y), (x + s * 0.7, y)], fill=hi, width=w)
    dr.line([(x - s * 0.4, y + s * 0.45), (x + s * 0.4, y + s * 0.45)], fill=hi, width=w)


def _dibujar_glifos(dr, glifos, pal, ver_rel, ver_veg, win, sc):
    x0, y0, w, h = win
    x1, y1 = x0 + w, y0 + h
    for (gy, kind, gx, s, r, cat) in glifos:
        if cat == "rel" and not ver_rel:
            continue
        if cat == "veg" and not ver_veg:
            continue
        mg = s * 4
        if gx + mg < x0 or gx - mg > x1 or gy + mg < y0 or gy - mg > y1:
            continue
        x = (gx - x0) * sc
        y = (gy - y0) * sc
        ss = s * sc
        if kind == "mont":
            _glifo_mont(dr, x, y, ss, r, pal)
        elif kind == "col":
            _glifo_col(dr, x, y, ss, pal)
        elif kind == "arbol":
            _glifo_arbol(dr, x, y, ss, pal)
        elif kind == "conif":
            _glifo_conif(dr, x, y, ss, pal)
        elif kind == "duna":
            _glifo_duna(dr, x, y, ss, pal)
        elif kind == "hielo":
            _glifo_hielo(dr, x, y, ss, pal)


# ==========================================================================
#  trazos suaves (rios, caminos, rutas)
# ==========================================================================
def _suave(pts):
    """Puntos de una polilinea suavizada por puntos medios (aprox. de las
    curvas cuadraticas del front), en el mismo espacio de coords que `pts`."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a = pts[i]
        mx = (pts[i][0] + pts[i + 1][0]) / 2
        my = (pts[i][1] + pts[i + 1][1]) / 2
        # subdividir el segmento cuadratico (control=a, fin=medio)
        p0 = out[-1]
        for k in range(1, 5):
            u = k / 5.0
            bx = (1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * a[0] + u * u * mx
            by = (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * a[1] + u * u * my
            out.append((bx, by))
    out.append(pts[-1])
    return out


def _map_pts(pts, x0, y0, sc):
    return [((p[0] - x0) * sc, (p[1] - y0) * sc) for p in pts]


def _dibujar_rios(dr, img, d, pal, win, sc, calidad, uni):
    x0, y0 = win[0], win[1]
    K = calidad
    kw = math.sqrt(K)
    rio = pal["rio"]
    for r in d["capas"].get("rios", []):
        pts = r.get("puntos", [])
        if len(pts) < 2:
            continue
        w = (0.7 + (r.get("caudal", 0.2)) * 2.6) / kw * sc
        sp = _map_pts(_suave(pts), x0, y0, sc)
        dr.line(sp, fill=rio + (230,), width=max(1, int(round(w))), joint="curve")
    # nombres de rios grandes, en cursiva siguiendo el cauce
    for r in d["capas"].get("rios", []):
        pts = r.get("puntos", [])
        if (r.get("caudal", 0) < 0.4 / K) or len(pts) < 6 or not r.get("nombre"):
            continue
        i = len(pts) // 2
        a = pts[i - 1]
        b = pts[i + 1] if i + 1 < len(pts) else pts[i]
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        if ang > math.pi / 2 or ang < -math.pi / 2:
            ang += math.pi
        fs = max(9 / K, uni / 150) * sc
        cx = (pts[i][0] - x0) * sc
        cy = (pts[i][1] - y0) * sc
        _texto_rotado(img, r["nombre"], cx, cy - fs * 0.2, fs, ang, "italic",
                      rio, pal["textoHalo"])


def _dibujar_caminos(dr, d, pal, win, sc, calidad, uni):
    x0, y0 = win[0], win[1]
    K = calidad
    u = uni
    wc = max(0.7 / K, u / 1400) * sc
    dash_c = (u / 500 * sc, u / 380 * sc)
    for c in d["capas"].get("caminos", []):
        pts = c.get("puntos", [])
        if len(pts) < 2:
            continue
        sp = _map_pts(_suave(pts), x0, y0, sc)
        _linea_punteada(dr, sp, pal["tinta"] + (179,), max(1, int(round(wc))), dash_c)
    wr = max(0.6 / K, u / 1700) * sc
    dash_r = (u / 700 * sc, u / 550 * sc)
    for r in d["capas"].get("rutas", []):
        pts = r.get("puntos", [])
        if len(pts) < 2:
            continue
        sp = _map_pts(_suave(pts), x0, y0, sc)
        _linea_punteada(dr, sp, pal["mareText"] + (179,), max(1, int(round(wr))), dash_r)


def _linea_punteada(dr, pts, fill, w, dash):
    on, off = dash
    period = on + off
    if period <= 0:
        dr.line(pts, fill=fill, width=w, joint="curve")
        return
    dist_acc = 0.0
    for i in range(1, len(pts)):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        seg = math.hypot(bx - ax, by - ay)
        if seg <= 0:
            continue
        ux, uy = (bx - ax) / seg, (by - ay) / seg
        t = 0.0
        while t < seg:
            fase = dist_acc % period
            if fase < on:
                paso = min(on - fase, seg - t)
                x1, y1 = ax + ux * t, ay + uy * t
                x2, y2 = ax + ux * (t + paso), ay + uy * (t + paso)
                dr.line([(x1, y1), (x2, y2)], fill=fill, width=w)
            else:
                paso = min(period - fase, seg - t)
            # nunca avanzar menos de 1e-6 px: si `fase` cae epsilon por debajo
            # de `on` o `period`, `paso` seria ~1e-16 y la suma flotante lo
            # absorberia (dist_acc no cambia) -> bucle infinito
            if paso < 1e-6:
                paso = 1e-6
            t += paso
            dist_acc += paso


# ==========================================================================
#  asentamientos
# ==========================================================================
def _casita(dr, x, y, s, pal):
    papel = pal["papelA"]
    tinta = pal["tinta"]
    w = max(1, int(round(s * 0.16)))
    dr.rectangle([x - s * 0.5, y - s * 0.5, x + s * 0.5, y + s * 0.2],
                 fill=papel, outline=tinta, width=w)
    _poly(dr, [(x - s * 0.62, y - s * 0.5), (x, y - s * 1.15), (x + s * 0.62, y - s * 0.5)],
          fill=papel, outline=tinta, w=s * 0.16)


def _castillo(dr, x, y, s, pal):
    papel = pal["papelA"]
    tinta = pal["tinta"]
    w = s * 1.5
    h = s * 1.1
    x0 = x - w / 2
    y0 = y - h
    pts = [(x0, y)]
    pts.append((x0, y0))
    almenas = 4
    aw = w / (almenas * 2 - 1)
    for i in range(almenas * 2 - 1):
        up = (i % 2 == 0)
        pts.append((x0 + i * aw, y0 if up else y0 + s * 0.28))
        pts.append((x0 + (i + 1) * aw, y0 if up else y0 + s * 0.28))
    pts.append((x0 + w, y))
    _poly(dr, pts, fill=papel, outline=tinta, w=s * 0.14)
    dr.line([(x, y0), (x, y0 - s * 0.8)], fill=tinta, width=max(1, int(round(s * 0.12))))
    _poly(dr, [(x, y0 - s * 0.8), (x + s * 0.7, y0 - s * 0.62), (x, y0 - s * 0.44)],
          fill=(176, 52, 44))


def _dibujar_asent(img, dr, d, pal, win, sc, calidad, uni):
    x0, y0 = win[0], win[1]
    x1, y1 = x0 + win[2], y0 + win[3]
    K = calidad
    base = max(3.2 / K, uni / 340) * sc
    cfg = sorted(d["capas"].get("asentamientos", []), key=lambda a: a.get("y", 0))
    for a in cfg:
        ax, ay = a.get("x", 0), a.get("y", 0)
        if ax < x0 - 20 or ax > x1 + 20 or ay < y0 - 20 or ay > y1 + 20:
            continue
        x = (ax - x0) * sc
        y = (ay - y0) * sc
        rg = int(a.get("rango", 0))
        if rg >= 3:
            _castillo(dr, x, y, base * 1.5, pal)
        elif rg == 2:
            _casita(dr, x, y, base * 1.25, pal)
        else:
            rr = base * 0.7 if rg == 1 else base * 0.5
            dr.ellipse([x - rr, y - rr, x + rr, y + rr], fill=pal["papelA"],
                       outline=pal["tinta"], width=max(1, int(round(base * 0.16))))
            if rg == 1:
                r2 = base * 0.22
                dr.ellipse([x - r2, y - r2, x + r2, y + r2], fill=pal["tinta"])
    # nombres
    for a in cfg:
        rg = int(a.get("rango", 0))
        if (rg < 1 and K < 3) or not a.get("nombre"):
            continue
        ax, ay = a.get("x", 0), a.get("y", 0)
        if ax < x0 - 40 or ax > x1 + 200 or ay < y0 - 40 or ay > y1 + 40:
            continue
        fs = (max(12 / K, uni / 118) if rg >= 3 else max(9.5 / K, uni / 165)) * sc
        clase = "bold" if rg >= 3 else "serif"
        off = (base * 1.8 if rg >= 3 else base * 1.3 if rg == 2 else base) + 2
        x = (ax - x0) * sc + off
        y = (ay - y0) * sc
        _texto(dr, a["nombre"], x, y, fs, clase, pal["texto"], pal["textoHalo"],
               anchor="lm")


# ==========================================================================
#  rotulos de paises y mares
# ==========================================================================
def _centroide_id(d, uid):
    ids = d["ids"]
    m = (ids == uid)
    n = int(m.sum())
    if not n:
        return None
    ys, xs = np.nonzero(m)
    cx = xs.mean() * d["nx"] / d["rw"]
    cy = ys.mean() * d["ny"] / d["rh"]
    return cx, cy, n


def _centroide_pais(d, pid, tierra_por_pais, cent_cache):
    if pid in cent_cache:
        return cent_cache[pid]
    ids_pais = tierra_por_pais.get(pid, [])
    if not ids_pais or d["ids"] is None:
        cent_cache[pid] = None
        return None
    ids = d["ids"]
    m = np.isin(ids, ids_pais)
    n = int(m.sum())
    if not n:
        cent_cache[pid] = None
        return None
    ys, xs = np.nonzero(m)
    res = (xs.mean() * d["nx"] / d["rw"], ys.mean() * d["ny"] / d["rh"], n)
    cent_cache[pid] = res
    return res


def _dibujar_rotulos(dr, d, pal, win, sc, calidad, nx):
    if d["ids"] is None:
        return
    x0, y0 = win[0], win[1]
    x1, y1 = x0 + win[2], y0 + win[3]
    K = calidad
    capas = d["capas"]
    tierra_por_pais = {}
    for t in capas.get("subregiones", {}).get("tierra", []):
        tierra_por_pais.setdefault(t.get("pais"), []).append(t["id"])
    cent_cache = {}

    paises = sorted(capas.get("paises", {}).get("lista", []),
                    key=lambda p: -p.get("area", 0))
    area_max = paises[0].get("area", 1) if paises else 1
    for p in paises:
        if p.get("area", 0) < area_max * 0.03 / (K * K):
            continue
        c = _centroide_pais(d, p["id"], tierra_por_pais, cent_cache)
        if not c:
            continue
        if c[0] < x0 or c[0] > x1 or c[1] < y0 or c[1] > y1:
            continue
        fs = max(15, min(36, nx / 46 * math.sqrt(p["area"] / area_max) + 12)) / K * sc
        x = (c[0] - x0) * sc
        y = (c[1] - y0) * sc
        _texto_espaciado(dr, p["nombre"].upper(), x, y, fs, "fantasy",
                         pal["texto"] + (235,), pal["textoHalo"], round(fs * 0.14))

    mares = sorted(capas.get("subregiones", {}).get("mar", []),
                   key=lambda m: -m.get("area", 0))
    mar_max = mares[0].get("area", 1) if mares else 1
    dibujados = 0
    for m in mares:
        if m.get("area", 0) < mar_max * 0.12 / K:
            continue
        if dibujados > 9 * K * K:
            break
        c = _centroide_id(d, m["id"])
        if not c:
            continue
        dibujados += 1
        if c[0] < x0 or c[0] > x1 or c[1] < y0 or c[1] > y1:
            continue
        fs = max(11, min(24, nx / 70 * math.sqrt(m["area"] / mar_max) + 8)) / K * sc
        x = (c[0] - x0) * sc
        y = (c[1] - y0) * sc
        _texto(dr, m["nombre"], x, y, fs, "italic", pal["mareText"] + (230,),
               pal["textoHalo"], anchor="mm")


# ==========================================================================
#  helpers de texto (halo por stroke; espaciado y rotacion manuales)
# ==========================================================================
def _texto(dr, txt, x, y, fs, clase, fill, halo, anchor="mm"):
    fnt = _fuente(clase, fs)
    sw = max(1, int(round(fs * 0.12))) if (len(halo) < 4 or halo[3] > 0) else 0
    dr.text((x, y), txt, font=fnt, fill=fill, anchor=anchor,
            stroke_width=sw, stroke_fill=halo[:3])


def _texto_espaciado(dr, txt, cx, cy, fs, clase, fill, halo, spacing):
    fnt = _fuente(clase, fs)
    anchos = [fnt.getlength(ch) for ch in txt]
    total = sum(anchos) + spacing * (len(txt) - 1 if txt else 0)
    x = cx - total / 2
    sw = max(1, int(round(fs * 0.14))) if (len(halo) < 4 or halo[3] > 0) else 0
    for ch, aw in zip(txt, anchos):
        dr.text((x, cy), ch, font=fnt, fill=fill, anchor="lm",
                stroke_width=sw, stroke_fill=halo[:3])
        x += aw + spacing


def _texto_rotado(img, txt, cx, cy, fs, ang, clase, fill, halo):
    fnt = _fuente(clase, fs)
    bbox = fnt.getbbox(txt, stroke_width=max(1, int(round(fs * 0.12))))
    tw = bbox[2] - bbox[0] + 8
    th = bbox[3] - bbox[1] + 8
    if tw < 2 or th < 2:
        return
    tmp = Image.new("RGBA", (int(tw), int(th)), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    sw = max(1, int(round(fs * 0.12)))
    td.text((tw / 2, th / 2), txt, font=fnt, fill=fill, anchor="mm",
            stroke_width=sw, stroke_fill=halo[:3])
    # canvas y-down: ang positivo = horario -> PIL rota antihorario, usar -deg
    rot = tmp.rotate(-math.degrees(ang), expand=True, resample=Image.BICUBIC)
    px = int(cx - rot.width / 2)
    py = int(cy - rot.height / 2)
    img.paste(rot, (px, py), rot)


# ==========================================================================
#  decoracion (marco, rosa de los vientos, cartela, escala grafica)
# ==========================================================================
def _round_rect(dr, x, y, w, h, r, fill=None, outline=None, width=1):
    dr.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill,
                         outline=outline, width=max(1, int(round(width))))


def _decorar(img, d, pal, W, H, win, calidad):
    dr = ImageDraw.Draw(img, "RGBA")
    _rosa_vientos(dr, d, pal, W, H, win)
    _marco(dr, pal, W, H)
    _cartela(dr, d, pal, W, H)
    _escala(dr, pal, W, H, win[2], d, calidad)


def _marco(dr, pal, W, H):
    m = W * 0.018
    marco = pal["marco"]
    dr.rectangle([m, m, W - m, H - m], outline=marco, width=max(1, int(round(W / 300))))
    dr.rectangle([m * 1.7, m * 1.7, W - 1.7 * m, H - 1.7 * m], outline=marco,
                 width=max(1, int(round(W / 700))))
    q = m * 2.4
    wq = max(1, int(round(W / 260)))
    for (sx, sy) in [(m, m), (W - m, m), (m, H - m), (W - m, H - m)]:
        dx = 1 if sx < W / 2 else -1
        dy = 1 if sy < H / 2 else -1
        # curva de esquina aproximada por bezier cuadratico
        p0 = (sx + dx * q, sy)
        p1 = (sx, sy)
        p2 = (sx, sy + dy * q)
        pts = []
        for k in range(9):
            u = k / 8.0
            bx = (1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * p1[0] + u * u * p2[0]
            by = (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * p1[1] + u * u * p2[1]
            pts.append((bx, by))
        dr.line(pts, fill=marco, width=wq, joint="curve")
        rr = m * 0.28
        ex, ey = sx + dx * q * 0.42, sy + dy * q * 0.42
        dr.ellipse([ex - rr, ey - rr, ex + rr, ey + rr], outline=marco, width=wq)


def _rosa_vientos(dr, d, pal, W, H, win):
    insX, insY = W * 0.13, H * 0.13
    esquinas = [(insX, insY), (W - insX, insY), (insX, H - insY), (W - insX, H - insY)]
    x0, y0, w, h = win

    def es_mar(px, py):
        wx = x0 + px / W * w
        wy = y0 + py / H * h
        cx, cy = _dpx(d, wx, wy)
        return bool(d["esmar"][cy, cx])

    pos = esquinas[3]
    for e in esquinas:
        if es_mar(*e):
            pos = e
            break
    cxp, cyp = pos
    R = W * 0.062
    tinta = pal["tinta"]
    wl = max(1, int(round(W / 900)))
    dr.ellipse([cxp - R, cyp - R, cxp + R, cyp + R], outline=tinta, width=wl)
    r2 = R * 0.72
    dr.ellipse([cxp - r2, cyp - r2, cxp + r2, cyp + r2], outline=tinta, width=wl)
    for k in range(8):
        ang = k * math.pi / 4
        largo = R if k % 2 == 0 else R * 0.62
        ww = R * 0.14 if k % 2 == 0 else R * 0.09
        ax, ay = math.cos(ang), math.sin(ang)
        pxp, pyp = math.cos(ang + math.pi / 2), math.sin(ang + math.pi / 2)
        pts = [(cxp + ax * largo, cyp + ay * largo),
               (cxp + pxp * ww, cyp + pyp * ww),
               (cxp - ax * ww, cyp - ay * ww),
               (cxp - pxp * ww, cyp - pyp * ww)]
        alpha = 217 if k % 2 == 0 else 128
        dr.polygon(pts, fill=tinta + (alpha,))
    fs = R * 0.34
    fnt = _fuente("fantasy", fs)
    for txt, dx, dy in [("N", 0, -R * 1.22), ("S", 0, R * 1.22),
                        ("E", R * 1.22, 0), ("O", -R * 1.22, 0)]:
        dr.text((cxp + dx, cyp + dy), txt, font=fnt, fill=tinta, anchor="mm")


def _cartela(dr, d, pal, W, H):
    paises = sorted(d["capas"].get("paises", {}).get("lista", []),
                    key=lambda p: -p.get("area", 0))
    titulo = "Tierras Ignotas"
    if paises and paises[0].get("nombre"):
        titulo = paises[0]["nombre"]
    else:
        cap = next((a for a in d["capas"].get("asentamientos", [])
                    if a.get("rango", 0) >= 3), None)
        if cap:
            titulo = "Tierras de " + cap["nombre"]
    cw, ch = W * 0.42, H * 0.072
    x = (W - cw) / 2
    y = H * 0.028
    papel = pal["papelA"]
    _round_rect(dr, x, y, cw, ch, ch * 0.22, fill=papel + (209,),
                outline=pal["marco"], width=W / 500)
    _round_rect(dr, x + ch * 0.14, y + ch * 0.14, cw - ch * 0.28, ch - ch * 0.28,
                ch * 0.16, outline=pal["marco"], width=W / 1100)
    fs = min(ch * 0.5, cw / (len(titulo) * 0.62)) if titulo else ch * 0.5
    _texto_espaciado(dr, titulo, W / 2, y + ch / 2, fs, "fantasy",
                     pal["texto"], (0, 0, 0, 0), round(fs * 0.08))


def _escala(dr, pal, W, H, winW, d, calidad):
    # leguas nominales de una barra 0.22W (el mundo mide 200*calidad leguas)
    raw = 200 * calidad * winW / d["nx"]
    if not (raw > 0):
        return
    pot = 10 ** math.floor(math.log10(raw))
    lg = pot
    for mm in (5, 2, 1):
        if mm * pot <= raw:
            lg = mm * pot
            break
    total = W * 0.22 * lg / raw
    seg = 4
    sw = total / seg
    x = W * 0.055
    y = H * 0.945
    tinta = pal["tinta"]
    hh = W * 0.008
    wl = max(1, int(round(W / 1200)))
    for i in range(seg):
        box = [x + i * sw, y, x + (i + 1) * sw, y + hh]
        if i % 2 == 0:
            dr.rectangle(box, fill=tinta)
        dr.rectangle(box, outline=tinta, width=wl)
    dr.rectangle([x, y, x + total, y + hh], outline=tinta, width=wl)
    fs = W * 0.011
    fnt = _fuente("serif", fs)

    def fmt(v):
        return ("%.1f" % v) if v % 1 else str(int(v))
    dr.text((x, y - 2), "0", font=fnt, fill=tinta, anchor="ms")
    dr.text((x + total / 2, y - 2), fmt(lg / 2), font=fnt, fill=tinta, anchor="ms")
    dr.text((x + total, y - 2), "%s leguas" % fmt(lg), font=fnt, fill=tinta, anchor="ms")


# ==========================================================================
#  vineteado (numpy)
# ==========================================================================
def _vineta(img, pal, win, nx, ny):
    W, H = img.size
    x0, y0, w, h = win
    xs = x0 + (np.arange(W) + 0.5) / W * w
    ys = y0 + (np.arange(H) + 0.5) / H * h
    WX, WY = np.meshgrid(xs, ys)
    r = np.sqrt((WX - nx / 2) ** 2 + (WY - ny / 2) ** 2)
    r0, r1 = nx * 0.32, nx * 0.72
    t = np.clip((r - r0) / (r1 - r0), 0, 1)
    vin = pal["vineta"]
    a = (t * (vin[3] / 255.0))[:, :, None]
    arr = np.asarray(img).astype(np.float32)
    col = np.array(vin[:3], np.float32)[None, None, :]
    arr = arr * (1 - a) + col * a
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


# ==========================================================================
#  render principal
# ==========================================================================
def _workres(calidad):
    return 4096 if calidad >= 3 else 3072 if calidad == 2 else 2048


def _render(d, sello, stem, calidad, semilla, paleta, capas, win, deco, workres):
    pal = PALETAS[paleta]
    nx, ny = d["nx"], d["ny"]
    uni = nx / calidad

    base, outW, outH = _construir_base(d, pal, win, calidad, workres)
    img = base

    sc = outW / win[2]

    # tinte politico
    if capas.get("tinte"):
        tinte = _construir_tinte(d)
        if tinte is not None:
            # el tinte cubre el mundo entero (0..nx); recortar/escalar a la ventana
            alpha = 0.30 if paleta == "noche" else 0.20
            tw = tinte.resize((outW, outH), Image.BILINEAR,
                              box=(win[0] / nx * tinte.width, win[1] / ny * tinte.height,
                                   (win[0] + win[2]) / nx * tinte.width,
                                   (win[1] + win[3]) / ny * tinte.height))
            arr = np.asarray(tw).astype(np.float32)
            a = (arr[:, :, 3:4] / 255.0) * alpha
            base_arr = np.asarray(img).astype(np.float32)
            base_arr = base_arr * (1 - a) + arr[:, :, :3] * a
            img = Image.fromarray(np.clip(base_arr, 0, 255).astype(np.uint8), "RGB")

    dr = ImageDraw.Draw(img, "RGBA")

    glifos = _construir_glifos(d, sello, stem, semilla, calidad)
    _dibujar_glifos(dr, glifos, pal, capas.get("relieve", True),
                    capas.get("veg", True), win, sc)

    if capas.get("rios", True):
        _dibujar_rios(dr, img, d, pal, win, sc, calidad, uni)
    if capas.get("caminos", True):
        _dibujar_caminos(dr, d, pal, win, sc, calidad, uni)
    if capas.get("asent", True):
        _dibujar_asent(img, dr, d, pal, win, sc, calidad, uni)
    if capas.get("rotulos", True):
        _dibujar_rotulos(dr, d, pal, win, sc, calidad, nx)

    img = _vineta(img, pal, win, nx, ny)

    if deco:
        _decorar(img, d, pal, outW, outH, win, calidad)

    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _render_deco(d, paleta, calidad, win, outW):
    """PNG RGBA transparente solo con la decoracion (marco, rosa, cartela,
    escala) para la ventana `win`. El visor lo superpone fijo a la vista,
    como hacia el overlay del front, sin llevarse la logica de dibujo."""
    pal = PALETAS[paleta]
    outH = max(1, int(round(outW * win[3] / win[2])))
    img = Image.new("RGBA", (outW, outH), (0, 0, 0, 0))
    _decorar(img, d, pal, outW, outH, win, calidad)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ==========================================================================
#  parseo/acotado de parametros y endpoints
# ==========================================================================
def _bool(q, k, defecto=False):
    v = q.get(k, [None])[0]
    if v is None:
        return defecto
    return v not in ("0", "false", "no", "")


def _float(q, k, defecto):
    try:
        return float(q.get(k, [defecto])[0])
    except (TypeError, ValueError):
        return defecto


def _parse_capas(q):
    v = q.get("capas", [None])[0]
    if v is None:
        # por defecto todas activas salvo tinte (como las casillas del front)
        return {c: (c != "tinte") for c in CAPAS_VALIDAS}
    activas = set(x for x in v.split(",") if x in CAPAS_VALIDAS)
    return {c: (c in activas) for c in CAPAS_VALIDAS}


def _params_comunes(q):
    try:
        calidad = int(q.get("calidad", ["2"])[0])
    except (TypeError, ValueError):
        calidad = 2
    calidad = min(4, max(1, calidad))
    paleta = q.get("paleta", ["claro"])[0]
    if paleta not in PALETAS_VALIDAS:
        paleta = "claro"
    semilla = (q.get("semilla", [""])[0] or "")[:64]
    capas = _parse_capas(q)
    deco = _bool(q, "deco", False)
    return calidad, paleta, semilla, capas, deco


def _cache_path(sello, stem, clave):
    carpeta = SALIDAS / sello / "detalles" / "fantasia_cache"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / (hashlib.md5(clave.encode()).hexdigest() + ".png")


def _atender(handler, url, es_sector, es_deco=False):
    q = parse_qs(url.query)
    sello = q.get("sello", [""])[0]
    stem = q.get("d", [""])[0]
    if not RE_SELLO.match(sello) or not RE_STEM.match(stem):
        handler._json({"error": "sello/d invalidos"}, 400)
        return True
    d = _cargar_datos(sello, stem)
    if d is None:
        handler._json({"error": "detalle sin capas.json/datos2.png"}, 404)
        return True

    calidad, paleta, semilla, capas, deco = _params_comunes(q)
    if not semilla:
        semilla = stem
    nx, ny = d["nx"], d["ny"]
    workres = _workres(calidad)
    # px opcional: ancho de salida en pixeles (exportes a mas/menos resolucion)
    px = int(_float(q, "px", 0))
    if px > 0:
        workres = min(8192, max(512, px))

    if es_sector:
        w = _float(q, "w", 0)
        h = _float(q, "h", 0)
        cx = _float(q, "cx", nx / 2)
        cy = _float(q, "cy", ny / 2)
        z = _float(q, "z", 0)
        if w <= 0 or h <= 0:
            if z > 1:
                w, h = nx / z, ny / z
            else:
                w, h = nx, ny
        w = min(max(w, nx / 512.0), nx)
        h = min(max(h, ny / 512.0), ny)
        x0 = min(max(0.0, cx - w / 2), nx - w)
        y0 = min(max(0.0, cy - h / 2), ny - h)
        win = (x0, y0, w, h)
    else:
        win = (0.0, 0.0, float(nx), float(ny))

    capas_str = ",".join(c for c in CAPAS_VALIDAS if capas[c])
    clave = "|".join([
        "deco" if es_deco else ("sector" if es_sector else "full"),
        stem, str(calidad), semilla, paleta,
        capas_str, "1" if deco else "0",
        "%.2f_%.2f_%.2f_%.2f" % win, str(workres),
    ])
    cache = _cache_path(sello, stem, clave)
    if cache.exists():
        handler._archivo(cache, "image/png", cache=True)
        return True

    if es_deco:
        png = _render_deco(d, paleta, calidad, win, min(workres, 2048))
    else:
        png = _render(d, sello, stem, calidad, semilla, paleta, capas, win,
                      deco, workres)
    try:
        cache.write_bytes(png)
    except OSError:
        pass
    handler._bytes(png, "image/png", cache=True)
    return True


def manejar_get(handler, url):
    if url.path == "/api/fantasia/render":
        return _atender(handler, url, es_sector=False)
    if url.path == "/api/fantasia/sector":
        return _atender(handler, url, es_sector=True)
    if url.path == "/api/fantasia/deco":
        return _atender(handler, url, es_sector=True, es_deco=True)
    return False


def manejar_post(handler, ruta, datos):
    return False
