"""Generador de battlemaps de encuentro en el servidor (PIL + numpy).

Portea a Python la logica procedural que antes vivia en `batalla.html`:
analisis del punto elegido del mundo (rasters _datos/_datos2 + _capas.json),
deteccion del tema, titulo narrativo y el render completo del battlemap
(suelo por ruido fbm, corredor transitable, props por tema y subtipo,
interiores taberna/cripta/mazmorra, rejilla y numeracion). El navegador
queda como visor delgado: pide JSON/PNG y solo presenta.

El PRNG (mulberry32), el hash FNV-1a y el ruido de valor h2/noise2/fbm son
identicos bit a bit a los del front original: misma semilla + mismo
tema/subtipo/tamano -> mismo mapa (determinista y reproducible).

Expone, para el enchufe de `web.py`:
    manejar_get(handler, url) -> bool
    manejar_post(handler, ruta, datos) -> bool

Endpoints (GET):
    /api/batalla/info?sello&d
        -> resolucion del detalle + catalogo de temas y subtipos.
    /api/batalla/lugar?sello&d&rx&ry
        -> ficha del punto (bioma, altitud, temperatura, rios/caminos/
           asentamientos cercanos, costa) + tema sugerido.
    /api/batalla/escena?sello&d&rx&ry&tema&sub&semilla
        -> titulo narrativo y subtipo efectivo.
    /api/batalla/mapa?sello&d&rx&ry&tema&sub&cols&rows&semilla&px&rejilla&nums
        -> PNG del battlemap (cacheado en salidas/<sello>/detalles/
           batalla_cache/ por hash de parametros).

Geometria: los battlemaps son escenas locales, SIN wrap alguno (ni X ni Y);
el mundo del que derivan envuelve solo en X y eso ya viene resuelto en los
rasters del detalle. Solo biblioteca estandar + numpy + Pillow.
"""
import hashlib
import json
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

_LOCK = threading.Lock()
_CACHE_DATOS = {}      # (sello, stem) -> (mtime, dict)
_CACHE_FUENTES = {}    # px -> ImageFont

M32 = 0xFFFFFFFF
TAU = 6.2832

# ==========================================================================
#  catalogo de temas y subtipos (portado de batalla.html)
# ==========================================================================
TEMAS = [
    {"clave": "bosque",   "nombre": "Bosque templado",       "subs": ["tipico", "denso", "claro", "ruinas", "circulo", "cementerio", "campamento", "torre", "altar", "madriguera"]},
    {"clave": "taiga",    "nombre": "Taiga (coníferas)", "subs": ["tipico", "denso", "claro", "ruinas", "campamento", "madriguera"]},
    {"clave": "selva",    "nombre": "Selva densa",           "subs": ["tipico", "denso", "ruinas", "circulo", "altar"]},
    {"clave": "desierto", "nombre": "Desierto / roquedal",   "subs": ["tipico", "oasis", "canon", "ruinas", "campamento", "cruce"]},
    {"clave": "nieve",    "nombre": "Nieve / tundra",        "subs": ["tipico", "lago", "ruinas", "campamento", "cementerio", "torre"]},
    {"clave": "cienaga",  "nombre": "Ciénaga / pantano", "subs": ["tipico", "ruinas", "cementerio", "circulo", "altar"]},
    {"clave": "paso",     "nombre": "Paso rocoso / montaña", "subs": ["tipico", "canon", "mina", "ruinas", "campamento", "torre", "geiseres"]},
    {"clave": "pradera",  "nombre": "Pradera",               "subs": ["campamento", "tipico", "circulo", "granja", "cementerio", "ruinas", "torre", "cruce", "madriguera"]},
    {"clave": "volcanico", "nombre": "Tierras volcánicas / roca ardiente", "subs": ["tipico", "canon", "ruinas", "geiseres"]},
    {"clave": "vado",     "nombre": "Vado de río",      "subs": ["tipico", "puente", "piedras"]},
    {"clave": "playa",    "nombre": "Playa / costa",         "subs": ["tipico", "naufragio", "acantilado", "embarcadero"]},
    {"clave": "aldea",    "nombre": "Aldea",                 "subs": ["tipico", "mercado", "granja"]},
    {"clave": "puerto",   "nombre": "Puerto / muelle",       "subs": ["tipico", "embarcadero", "mercado"]},
    {"clave": "taberna",  "nombre": "Taberna (interior)",    "subs": []},
    {"clave": "cripta",   "nombre": "Cripta (interior)",     "subs": []},
    {"clave": "mazmorra", "nombre": "Mazmorra (interior)",   "subs": []},
    {"clave": "gruta",    "nombre": "Gruta / caverna (interior)", "subs": []},
]
SUBS = {
    "auto": "✨ automático", "tipico": "clásico",
    "denso": "espesura densa", "claro": "claro abierto",
    "ruinas": "ruinas antiguas", "circulo": "círculo de piedras",
    "cementerio": "cementerio", "campamento": "campamento",
    "oasis": "oasis", "canon": "cañón angosto", "lago": "lago helado",
    "mina": "mina abandonada", "granja": "granja",
    "puente": "puente", "piedras": "piedras de paso", "mercado": "mercado",
    "naufragio": "naufragio", "acantilado": "acantilado",
    "torre": "torre en ruinas", "altar": "altar profanado",
    "cruce": "cruce de caminos", "madriguera": "madriguera",
    "geiseres": "géiseres", "embarcadero": "embarcadero",
}
TEMAS_POR_CLAVE = {t["clave"]: t for t in TEMAS}


def _hx(s):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _a(c, alfa):
    """Color con alfa 0..1 -> tupla RGBA."""
    return (c[0], c[1], c[2], int(round(alfa * 255)))


def _mid(c1, c2, t=0.5):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3))


# paletas de suelo por tema: [base, claro, oscuro]
PAL = {
    "bosque":   [(61, 88, 52), (82, 112, 62), (40, 60, 34)],
    "taiga":    [(64, 82, 66), (120, 138, 128), (44, 58, 46)],
    "selva":    [(32, 58, 26), (58, 92, 40), (18, 38, 16)],
    "desierto": [(214, 182, 120), (232, 204, 150), (178, 146, 92)],
    "nieve":    [(221, 231, 240), (242, 247, 252), (186, 202, 218)],
    "cienaga":  [(74, 82, 54), (98, 104, 70), (48, 56, 38)],
    "paso":     [(104, 104, 110), (138, 138, 145), (74, 74, 80)],
    "pradera":  [(118, 146, 78), (150, 176, 100), (92, 116, 60)],
    "vado":     [(112, 140, 76), (146, 172, 96), (86, 110, 56)],
    "playa":    [(224, 206, 158), (238, 224, 184), (196, 176, 128)],
    "aldea":    [(120, 122, 82), (146, 146, 104), (92, 96, 62)],
    "volcanico": [(58, 50, 50), (96, 70, 60), (30, 25, 27)],
    "puerto":   [(150, 156, 132), (176, 180, 158), (116, 122, 98)],
}


# ==========================================================================
#  PRNG determinista y ruido de valor (portados 1:1 de batalla.html)
# ==========================================================================
def _imul(x, y):
    return (int(x) * int(y)) & M32


def hash_str(s):
    """FNV-1a 32 bit (identico a hashStr del front)."""
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & M32
    return h & M32


class Mulberry32:
    """Identico a mulberry32(a) del front: misma semilla, misma secuencia."""
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a & M32

    def __call__(self):
        self.a = (self.a + 0x6D2B79F5) & M32
        a = self.a
        t = _imul(a ^ (a >> 15), 1 | a)
        t = ((t + _imul(t ^ (t >> 7), 61 | t)) & M32) ^ t
        t &= M32
        return ((t ^ (t >> 14)) & M32) / 4294967296.0


def semilla_efectiva(seed, tema):
    return (int(seed) & M32) ^ hash_str(tema)


def h2(ix, iy, seed):
    h = (int(seed) ^ _imul(ix, 374761393) ^ _imul(iy, 668265263)) & M32
    h = _imul(h ^ (h >> 13), 1274126177)
    return ((h ^ (h >> 16)) & M32) / 4294967296.0


def noise2(x, y, seed):
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    u = fx * fx * (3 - 2 * fx)
    v = fy * fy * (3 - 2 * fy)
    a = h2(ix, iy, seed)
    b = h2(ix + 1, iy, seed)
    c = h2(ix, iy + 1, seed)
    d = h2(ix + 1, iy + 1, seed)
    return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v


def fbm(x, y, seed, oct_):
    s, amp, f, tot = 0.0, 0.5, 1.0, 0.0
    for i in range(oct_):
        s += amp * noise2(x * f, y * f, seed + i * 1013)
        tot += amp
        amp *= 0.5
        f *= 2
    return s / tot


def cel_rng(seed, x, y):
    return Mulberry32(((int(seed) & M32) ^ _imul(x + 1, 73856093)
                       ^ _imul(y + 1, 19349663)) & M32)


# --- versiones vectorizadas (mismos bits) para el suelo ---
_U = np.uint64
_MV = _U(M32)


def _h2_vec(ix, iy, seed):
    ix = ix.astype(np.uint64)
    iy = iy.astype(np.uint64)
    h = (_U(int(seed) & M32) ^ ((ix * _U(374761393)) & _MV)
         ^ ((iy * _U(668265263)) & _MV)) & _MV
    h = ((h ^ (h >> _U(13))) * _U(1274126177)) & _MV
    return ((h ^ (h >> _U(16))) & _MV).astype(np.float64) / 4294967296.0


def _noise2_vec(x, y, seed):
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = x - x0
    fy = y - y0
    u = fx * fx * (3 - 2 * fx)
    v = fy * fy * (3 - 2 * fy)
    x0 = x0.astype(np.int64)
    y0 = y0.astype(np.int64)
    a = _h2_vec(x0, y0, seed)
    b = _h2_vec(x0 + 1, y0, seed)
    c = _h2_vec(x0, y0 + 1, seed)
    d = _h2_vec(x0 + 1, y0 + 1, seed)
    return a * (1 - u) * (1 - v) + b * u * (1 - v) + c * (1 - u) * v + d * u * v


def _fbm_vec(x, y, seed, oct_):
    s = np.zeros_like(x)
    amp, f, tot = 0.5, 1.0, 0.0
    for i in range(oct_):
        s += amp * _noise2_vec(x * f, y * f, seed + i * 1013)
        tot += amp
        amp *= 0.5
        f *= 2
    return s / tot


def _mb32_first_vec(a):
    """Primer valor de mulberry32(a) para un array de semillas (para el
    jitter por casilla del suelo)."""
    a = (a.astype(np.uint64) + _U(0x6D2B79F5)) & _MV
    t = ((a ^ (a >> _U(15))) * (_U(1) | a)) & _MV
    t2 = ((t ^ (t >> _U(7))) * (_U(61) | t)) & _MV
    t = (((t + t2) & _MV) ^ t) & _MV
    return ((t ^ (t >> _U(14))) & _MV).astype(np.float64) / 4294967296.0


# ==========================================================================
#  carga de datos del detalle (cacheada en memoria por mtime)
# ==========================================================================
def _cargar_datos(sello, stem):
    carpeta = SALIDAS / sello / "detalles"
    fcapas = carpeta / f"{stem}_capas.json"
    fd1 = carpeta / f"{stem}_datos.png"
    fd2 = carpeta / f"{stem}_datos2.png"
    if not (fcapas.exists() and fd1.exists() and fd2.exists()):
        return None
    mt = max(fcapas.stat().st_mtime, fd1.stat().st_mtime, fd2.stat().st_mtime)
    clave = (sello, stem)
    with _LOCK:
        hit = _CACHE_DATOS.get(clave)
        if hit and hit[0] == mt:
            return hit[1]

    capas = json.loads(fcapas.read_text(encoding="utf-8"))
    nx, ny = capas.get("resolucion", [1536, 1536])
    d1 = np.asarray(Image.open(fd1).convert("RGB"))   # temp, precip, alt
    d2 = np.asarray(Image.open(fd2).convert("RGB"))   # bioma, koppen, hielo
    d = {
        "capas": capas, "nx": int(nx), "ny": int(ny),
        "d1": d1, "d2": d2,
        "escalas": capas.get("escalas") or {"tair": [0, 1]},
        "biomas": capas.get("biomas") or [],
    }
    with _LOCK:
        _CACHE_DATOS[clave] = (mt, d)
    return d


def _muestrear(raster, rx, ry, nx, ny):
    h, w = raster.shape[0], raster.shape[1]
    x = min(max(int(rx * w / nx), 0), w - 1)
    y = min(max(int(ry * h / ny), 0), h - 1)
    return raster[y, x]


def _ventana_mar(d, rx, ry, radio_px=12):
    """Fraccion de mar (bioma==255) en una ventana de datos2 (paso 2 px,
    identico al front)."""
    r2 = d["d2"]
    h, w = r2.shape[0], r2.shape[1]
    cx = rx * w / d["nx"]
    cy = ry * h / d["ny"]
    mar = tot = 0
    dy = -radio_px
    while dy <= radio_px:
        dx = -radio_px
        while dx <= radio_px:
            x = int(round(cx + dx))
            y = int(round(cy + dy))
            dx += 2
            if x < 0 or y < 0 or x >= w or y >= h:
                continue
            tot += 1
            if r2[y, x, 0] == 255:
                mar += 1
        dy += 2
    return {"hayMar": mar > 0, "frac": (mar / tot) if tot else 0.0}


def _dist_polilinea(px, py, pts):
    a = np.asarray(pts, np.float64)
    if a.ndim != 2 or len(a) == 0:
        return math.inf
    if len(a) == 1:
        return float(math.hypot(px - a[0, 0], py - a[0, 1]))
    ax, ay = a[:-1, 0], a[:-1, 1]
    bx, by = a[1:, 0], a[1:, 1]
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = np.where(l2 > 0, ((px - ax) * dx + (py - ay) * dy) / np.maximum(l2, 1e-12), 0.0)
    t = np.clip(t, 0.0, 1.0)
    return float(np.min(np.hypot(px - (ax + t * dx), py - (ay + t * dy))))


def _mas_cercano(px, py, lista, con_puntos):
    best, bd = None, math.inf
    for it in (lista or []):
        if con_puntos:
            pts = it.get("puntos") or []
            d = _dist_polilinea(px, py, pts) if pts else math.inf
        else:
            d = math.hypot(px - it.get("x", 0), py - it.get("y", 0))
        if d < bd:
            bd, best = d, it
    return {"it": best, "d": bd}


# ==========================================================================
#  analisis del punto: ficha, tema sugerido, titulo (portados del front)
# ==========================================================================
def analizar(d, rx, ry):
    nx, ny = d["nx"], d["ny"]
    p1 = _muestrear(d["d1"], rx, ry, nx, ny)
    p2 = _muestrear(d["d2"], rx, ry, nx, ny)
    tair = d["escalas"].get("tair") or [0, 1]
    temp = tair[0] + (int(p1[0]) / 255.0) * (tair[1] - tair[0])
    precip = int(p1[1]) / 255.0
    alt = int(p1[2]) / 255.0
    bioma_id = int(p2[0])
    hielo = int(p2[2]) / 255.0
    es_mar = bioma_id == 255
    bioma = next((b for b in d["biomas"] if b.get("id") == bioma_id), None)
    c = d["capas"]
    return {
        "rx": rx, "ry": ry, "temp": temp, "precip": precip, "alt": alt,
        "biomaId": bioma_id, "bioma": bioma, "hielo": hielo, "esMar": es_mar,
        "rio": _mas_cercano(rx, ry, c.get("rios"), True),
        "camino": _mas_cercano(rx, ry, c.get("caminos"), True),
        "asent": _mas_cercano(rx, ry, c.get("asentamientos"), False),
        "costa": _ventana_mar(d, rx, ry, 12),
        "tair": tair,
    }


def detectar_tema(info, nx):
    esc = nx / 1024.0            # umbrales pensados en base 1024
    tair = info["tair"]
    if info["asent"]["it"] and info["asent"]["d"] < 15 * esc:
        # asentamiento en el litoral -> puerto; tierra adentro -> aldea
        return "puerto" if info["costa"]["hayMar"] else "aldea"
    if info["rio"]["it"] and info["rio"]["d"] < 42 * esc:
        return "vado"
    if info["costa"]["hayMar"]:
        return "playa"
    # roca ardiente: gran altitud + calor tórrido -> tierras volcánicas
    if info["alt"] > 0.72 and info["temp"] > tair[0] + 0.82 * (tair[1] - tair[0]):
        return "volcanico"
    if info["alt"] > 0.75:
        return "paso"
    if (info["precip"] > 0.86 and info["alt"] < 0.16
            and info["temp"] > tair[0] + 0.55 * (tair[1] - tair[0])):
        return "cienaga"
    b = info["biomaId"]
    if b in (0, 1):
        return "nieve"           # hielo, tundra
    if b == 2:
        return "taiga"
    if b == 10:
        return "selva"           # bosque humedo
    if b in (7, 8):
        return "bosque"          # templado, seco
    if b in (4, 5):
        return "desierto"
    return "pradera"             # estepa, pradera, sabana y resto


def _desc_temp(t, tair):
    f = (t - tair[0]) / ((tair[1] - tair[0]) or 1)
    if f < 0.2:
        return "gélido"
    if f < 0.4:
        return "frío"
    if f < 0.6:
        return "templado"
    if f < 0.8:
        return "cálido"
    return "tórrido"


def _desc_alt(a):
    if a < 0.12:
        return "tierras bajas"
    if a < 0.35:
        return "llanura"
    if a < 0.6:
        return "colinas"
    if a < 0.78:
        return "montaña"
    return "alta montaña"


def _nombre_pais(d, pid):
    ls = (d["capas"].get("paises") or {}).get("lista") or []
    p = next((x for x in ls if x.get("id") == pid), None)
    return p.get("nombre") if p else None


def titulo_escena(d, tema, sub, info, nx):
    pais = _nombre_pais(d, info["asent"]["it"].get("pais")) if info["asent"]["it"] else None
    lugar = pais or "las tierras salvajes"
    asent_n = info["asent"]["it"].get("nombre") if info["asent"]["it"] else "la aldea"
    rio_n = info["rio"]["it"].get("nombre") if info["rio"]["it"] else "el río"
    por_sub = {
        "ruinas": "Ruinas antiguas de " + lugar,
        "circulo": "Círculo de piedras de " + lugar,
        "cementerio": "Cementerio olvidado de " + lugar,
        "campamento": "Campamento en " + lugar,
        "oasis": "Oasis de " + lugar,
        "canon": "Cañón de " + lugar,
        "lago": "Lago helado de " + lugar,
        "mina": "Mina abandonada de " + lugar,
        "granja": ("Granja de " + asent_n) if tema == "aldea" else ("Granja en " + lugar),
        "naufragio": "Naufragio en la costa de " + lugar,
        "acantilado": "Acantilados de " + lugar,
        "mercado": ("Mercado de " + asent_n) if tema in ("aldea", "puerto") else ("Mercado de " + lugar),
        "torre": "Torre en ruinas de " + lugar,
        "altar": "Altar profanado de " + lugar,
        "cruce": "Cruce de caminos de " + lugar,
        "madriguera": "Madriguera en " + lugar,
        "geiseres": "Géiseres de " + lugar,
        "embarcadero": ("Embarcadero de " + asent_n) if tema in ("puerto", "aldea") else ("Embarcadero de " + lugar),
    }
    if sub in por_sub:
        return por_sub[sub]
    if tema == "vado":
        puente = sub == "puente" or (
            sub != "piedras" and info["camino"]["it"]
            and info["camino"]["d"] < 45 * (nx / 1024.0))
        return ("Puente sobre el " if puente else "Vado del ") + rio_n
    por_tema = {
        "aldea": "Aldea de " + asent_n,
        "taberna": "Taberna de " + asent_n,
        "cripta": "Cripta de " + asent_n,
        "mazmorra": "Mazmorra bajo " + (asent_n if info["asent"]["it"] else lugar),
        "playa": "Costa de " + lugar,
        "puerto": ("Puerto de " + asent_n) if info["asent"]["it"] else ("Puerto de " + lugar),
        "gruta": "Gruta bajo " + (asent_n if info["asent"]["it"] else lugar),
        "volcanico": "Tierras ardientes de " + lugar,
        "bosque": "Bosque de " + lugar,
        "taiga": "Taiga de " + lugar,
        "selva": "Selva de " + lugar,
        "desierto": "Desierto de " + lugar,
        "nieve": "Yermo helado de " + lugar,
        "cienaga": "Ciénaga de " + lugar,
        "paso": "Paso rocoso de " + lugar,
        "pradera": "Praderas de " + lugar,
    }
    return por_tema.get(tema, "Encuentro en " + lugar)


def sub_efectivo(tema, sub, seed):
    if sub and sub != "auto":
        return sub
    lst = TEMAS_POR_CLAVE.get(tema, {}).get("subs") or []
    if not lst:
        return "tipico"
    return lst[(semilla_efectiva(seed, tema) >> 4) % len(lst)]


# ==========================================================================
#  lienzo: primitivas en unidades de casilla sobre PIL (mezcla RGBA)
# ==========================================================================
class Lienzo:
    def __init__(self, img, S):
        self.im = img
        self.S = float(S)
        self.dr = ImageDraw.Draw(img, "RGBA")

    def p(self, x, y):
        return (x * self.S, y * self.S)

    def w(self, w):
        return max(1, int(round(w * self.S)))

    def linea(self, pts, color, w=0.05):
        self.dr.line([self.p(x, y) for x, y in pts], fill=color, width=self.w(w))

    def poli(self, pts, fill=None, outline=None, w=0.05):
        px = [self.p(x, y) for x, y in pts]
        if fill is not None:
            self.dr.polygon(px, fill=fill)
        if outline is not None:
            self.dr.line(px + [px[0]], fill=outline, width=self.w(w))

    def elipse(self, cx, cy, rx, ry, fill=None, outline=None, w=0.05):
        rx, ry = abs(rx), abs(ry)
        if rx * self.S < 0.5 or ry * self.S < 0.5:
            rx = max(rx, 0.5 / self.S)
            ry = max(ry, 0.5 / self.S)
        box = [self.p(cx - rx, cy - ry), self.p(cx + rx, cy + ry)]
        self.dr.ellipse(box, fill=fill, outline=outline,
                        width=self.w(w) if outline else 1)

    def rect(self, x, y, w, h, fill=None, outline=None, ow=0.05):
        if w <= 0 or h <= 0:
            return
        self.dr.rectangle([self.p(x, y), self.p(x + w, y + h)], fill=fill,
                          outline=outline, width=self.w(ow) if outline else 1)

    def radial(self, cx, cy, r, stops, ry_f=1.0):
        """Gradiente radial aproximado (tile numpy con alfa) pegado encima."""
        S = self.S
        R = int(math.ceil(r * S))
        if R < 2:
            return
        x0, y0 = int(round(cx * S)) - R, int(round(cy * S)) - int(round(R * ry_f))
        h = 2 * int(round(R * ry_f))
        wdt = 2 * R
        if h < 2:
            return
        yy, xx = np.mgrid[0:h, 0:wdt].astype(np.float64)
        t = np.clip(np.hypot(xx - wdt / 2, (yy - h / 2) / max(ry_f, 1e-6)) / R, 0, 1)
        pos = [s[0] for s in stops]
        tile = np.zeros((h, wdt, 4), np.uint8)
        for k in range(4):
            vals = [s[1][k] if len(s[1]) > k else 255 for s in stops]
            tile[:, :, k] = np.interp(t, pos, vals).astype(np.uint8)
        tim = Image.fromarray(tile, "RGBA")
        self.im.paste(tim, (x0, y0), tim)

    def poli_radial(self, pts, cx, cy, r, stops):
        """Poligono relleno con gradiente radial (mascara del poligono)."""
        S = self.S
        px = [self.p(x, y) for x, y in pts]
        xs = [q[0] for q in px]
        ys = [q[1] for q in px]
        x0, x1 = int(min(xs)), int(math.ceil(max(xs)))
        y0, y1 = int(min(ys)), int(math.ceil(max(ys)))
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(self.im.width, x1)
        y1 = min(self.im.height, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mask).polygon([(q[0] - x0, q[1] - y0) for q in px], fill=255)
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float64)
        t = np.clip(np.hypot(xx - cx * S, yy - cy * S) / max(r * S, 1e-6), 0, 1)
        pos = [s[0] for s in stops]
        tile = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
        for k in range(3):
            vals = [s[1][k] for s in stops]
            tile[:, :, k] = np.interp(t, pos, vals).astype(np.uint8)
        self.im.paste(Image.fromarray(tile, "RGB"), (x0, y0), mask)


def _qpts(p0, p1, p2, n=14):
    """Curva cuadratica muestreada (reemplazo de quadraticCurveTo)."""
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


# ==========================================================================
#  corredor transitable garantizado (random walk acotado, port 1:1)
# ==========================================================================
def corredor(cols, rows, seed):
    s = set()
    rng = Mulberry32(seed + 7)
    horizontal = rng() < 0.5
    largo = cols if horizontal else rows
    ancho = rows if horizontal else cols
    pos = round(ancho / 2 + (rng() - 0.5) * ancho * 0.3)
    pos = max(1, min(ancho - 2, pos))
    for i in range(largo):
        r = rng()
        if r < 0.34 and pos > 1:
            pos -= 1
        elif r > 0.66 and pos < ancho - 2:
            pos += 1
        for dd in (-1, 0, 1):
            p = pos + dd
            if p < 0 or p >= ancho:
                continue
            s.add((i, p) if horizontal else (p, i))
    return {"set": s, "horizontal": horizontal}


def es_sendero(corr, x, y):
    return (x, y) in corr["set"]


# ==========================================================================
#  primitivas de dibujo (todas en unidades de casilla)
# ==========================================================================
def sombra(l, cx, cy, rx, ry):
    l.elipse(cx, cy, rx, ry, fill=(0, 0, 0, 56))


def poly_facet(cx, cy, r, n, rng):
    pts = []
    for i in range(n):
        a = (i / n) * TAU + rng() * 0.4
        rr = r * (0.72 + rng() * 0.5)
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    return pts


def roca(l, cx, cy, r, rng):
    sombra(l, cx + r * 0.15, cy + r * 0.4, r * 1.0, r * 0.45)
    pts = poly_facet(cx, cy, r, 6 + int(rng() * 2), rng)
    l.poli(pts, fill=_hx("#71767c"))
    l.linea([(cx - r * 0.3, cy - r * 0.2), (cx + r * 0.1, cy + r * 0.15),
             (cx + r * 0.45, cy - r * 0.25)], (30, 32, 36, 128), r * 0.06)
    l.elipse(cx - r * 0.25, cy - r * 0.3, r * 0.32, r * 0.18,
             fill=(255, 255, 255, 36))


def arbol(l, cx, cy, r, rng, conif, verdes):
    sombra(l, cx + r * 0.25, cy + r * 0.55, r * 1.05, r * 0.42)
    l.rect(cx - r * 0.1, cy - r * 0.1, r * 0.2, r * 0.75, fill=_hx("#4d3521"))
    cl, md, dk = verdes
    if conif:
        for k in range(3):
            yy = cy - r * 0.1 - k * r * 0.5
            ww = r * (1.0 - k * 0.22)
            l.poli([(cx, yy - r * 0.85), (cx - ww * 0.55, yy),
                    (cx + ww * 0.55, yy)], fill=_mid(md, dk, 0.35))
    else:
        n = 5 + int(rng() * 3)
        R = r * 0.95
        for _ in range(n):
            a = rng() * TAU
            rr = rng() * R * 0.55
            bx = cx + math.cos(a) * rr
            by = cy - r * 0.35 + math.sin(a) * rr * 0.8
            rad = R * (0.42 + rng() * 0.3)
            t = rng()
            col = _mid(md, dk, rng()) if t < 0.5 else _mid(md, cl, rng())
            l.elipse(bx, by, rad, rad, fill=col)
        l.elipse(cx - R * 0.2, cy - r * 0.6, R * 0.35, R * 0.35, fill=_a(cl, 0.5))


def arbusto(l, cx, cy, r, rng, verdes):
    sombra(l, cx, cy + r * 0.3, r * 0.7, r * 0.28)
    n = 4 + int(rng() * 2)
    for _ in range(n):
        a = rng() * TAU
        rr = rng() * r * 0.4
        col = _mid(verdes[1], verdes[2], rng())
        rad = r * (0.3 + rng() * 0.2)
        l.elipse(cx + math.cos(a) * rr, cy + math.sin(a) * rr * 0.7, rad, rad, fill=col)


def tronco(l, cx, cy, r, rng):
    sombra(l, cx, cy + r * 0.25, r * 1.0, r * 0.25)
    ang = (rng() - 0.5) * 1.2
    ca, sa = math.cos(ang), math.sin(ang)
    a = (cx - ca * r * 0.9, cy - sa * r * 0.9)
    b = (cx + ca * r * 0.9, cy + sa * r * 0.9)
    l.linea([a, b], _hx("#8a6238"), r * 0.36)
    l.elipse(a[0], a[1], r * 0.18, r * 0.18, fill=_hx("#3a2718"))
    l.linea([(a[0], a[1] - r * 0.05), (b[0], b[1] - r * 0.05)],
            (255, 255, 255, 31), r * 0.05)


def flor(l, cx, cy, r, rng):
    cols = ["#e7d24a", "#e46a8b", "#c98be0", "#f0f0f0"]
    c = _hx(cols[int(rng() * len(cols))])
    for k in range(5):
        a = k / 5 * TAU
        l.elipse(cx + math.cos(a) * r * 0.12, cy + math.sin(a) * r * 0.12,
                 r * 0.09, r * 0.09, fill=c)
    l.elipse(cx, cy, r * 0.07, r * 0.07, fill=_hx("#e7b23a"))


def fogata(l, cx, cy, r):
    for k in range(7):
        a = k / 7 * TAU
        l.elipse(cx + math.cos(a) * r * 0.45, cy + math.sin(a) * r * 0.45,
                 r * 0.13, r * 0.13, fill=_hx("#5b5b60"))
    l.linea([(cx - r * 0.3, cy + r * 0.2), (cx + r * 0.3, cy - r * 0.2)],
            _hx("#5a3d22"), r * 0.12)
    l.linea([(cx - r * 0.3, cy - r * 0.2), (cx + r * 0.3, cy + r * 0.2)],
            _hx("#5a3d22"), r * 0.12)
    l.radial(cx, cy - r * 0.1, r * 0.5,
             [(0.0, (255, 242, 176, 255)), (0.4, (246, 161, 42, 220)),
              (1.0, (210, 60, 20, 0))])
    llama = (_qpts((cx, cy - r * 0.55), (cx + r * 0.18, cy - r * 0.1), (cx, cy + r * 0.1))
             + _qpts((cx, cy + r * 0.1), (cx - r * 0.18, cy - r * 0.1), (cx, cy - r * 0.55)))
    l.poli(llama, fill=_hx("#ffdd66"))


def tienda(l, cx, cy, r, rng):
    sombra(l, cx, cy + r * 0.5, r * 0.9, r * 0.3)
    cols = [("#a24b3a", "#7d3628"), ("#3a6a8c", "#274a63"), ("#8a7a3a", "#5f5326")]
    c = cols[int(rng() * len(cols))]
    l.poli([(cx, cy - r * 0.7), (cx - r * 0.75, cy + r * 0.55),
            (cx + r * 0.75, cy + r * 0.55)], fill=_mid(_hx(c[0]), _hx(c[1])))
    l.poli([(cx, cy - r * 0.5), (cx - r * 0.22, cy + r * 0.55),
            (cx + r * 0.22, cy + r * 0.55)], fill=(0, 0, 0, 102))
    l.linea([(cx, cy - r * 0.7), (cx, cy - r * 0.9)], _hx("#4a3a20"), r * 0.05)


def barril(l, cx, cy, rng):
    sombra(l, cx, cy + 0.1, 0.45, 0.25)
    l.elipse(cx, cy, 0.4, 0.5, fill=_hx("#9c7642"), outline=_hx("#3a2718"), w=0.05)
    l.linea([(cx - 0.4, cy - 0.15), (cx + 0.4, cy - 0.15)], _hx("#3a2718"), 0.05)
    l.linea([(cx - 0.4, cy + 0.15), (cx + 0.4, cy + 0.15)], _hx("#3a2718"), 0.05)


# ==========================================================================
#  suelo: base fbm por numpy + jitter por casilla + sendero
# ==========================================================================
def _suelo_img(cols, rows, S, seed, tema):
    pal = PAL.get(tema) or PAL["pradera"]
    sub = 4
    sw, sh = cols * sub, rows * sub
    xs = (np.arange(sw) / sub) * 0.6
    ys = (np.arange(sh) / sub) * 0.6
    X, Y = np.meshgrid(xs, ys)
    n = _fbm_vec(X, Y, seed + 11, 4)
    n = np.clip((n - 0.25) / 0.5, 0.0, 1.0)
    p0 = np.array(pal[0], np.float64)
    p1 = np.array(pal[1], np.float64)
    p2 = np.array(pal[2], np.float64)
    t = n[..., None]
    bajo = p2 + (p0 - p2) * (t * 2)
    alto = p0 + (p1 - p0) * ((t - 0.5) * 2)
    arr = np.where(t < 0.5, bajo, alto)

    # jitter por casilla (tono roto) — primer valor de celRng(seed+3, x, y)
    gx, gy = np.meshgrid(np.arange(cols, dtype=np.uint64),
                         np.arange(rows, dtype=np.uint64))
    semillas = ((_U(int(seed + 3) & M32)
                 ^ (((gx + _U(1)) * _U(73856093)) & _MV)
                 ^ (((gy + _U(1)) * _U(19349663)) & _MV)) & _MV)
    j = (_mb32_first_vec(semillas) - 0.5) * 0.14        # (rows, cols)
    j = np.repeat(np.repeat(j, sub, axis=0), sub, axis=1)[..., None]
    arr = np.where(j > 0, arr + (255 - arr) * j, arr * (1 + j))
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB").resize((cols * S, rows * S), Image.NEAREST)
    return img


def _sendero(l, corr, seed):
    for (x, y) in sorted(corr["set"]):
        r = cel_rng(seed + 9, x, y)()
        l.elipse(x + 0.5, y + 0.5, 0.62, 0.55,
                 fill=(120, 96, 60, int(round((0.14 + r * 0.12) * 255))))


# ==========================================================================
#  props por tema (ports de propsNaturales y rasgos de subtipo)
# ==========================================================================
def props_naturales(l, cols, rows, seed, tema, corr, sub):
    conif = False
    if tema == "bosque":
        dens, verdes = 0.42, [(110, 160, 78), (64, 118, 58), (34, 74, 40)]
    elif tema == "taiga":
        dens, verdes, conif = 0.4, [(120, 150, 130), (46, 96, 70), (26, 60, 46)], True
    elif tema == "selva":
        dens, verdes = 0.6, [(86, 150, 60), (42, 100, 40), (20, 56, 24)]
    elif tema == "desierto":
        dens, verdes = 0.14, [(150, 160, 90), (110, 120, 66), (80, 88, 48)]
    elif tema == "nieve":
        dens, verdes, conif = 0.18, [(210, 220, 210), (150, 170, 160), (90, 110, 110)], True
    elif tema == "cienaga":
        dens, verdes = 0.3, [(130, 150, 80), (80, 100, 52), (46, 62, 34)]
    elif tema == "paso":
        dens, verdes = 0.5, [(120, 130, 90), (90, 100, 66), (60, 66, 46)]
    elif tema == "volcanico":
        dens, verdes = 0.12, [(96, 92, 70), (72, 66, 50), (48, 42, 34)]
    else:   # pradera
        dens, verdes = 0.16, [(150, 176, 100), (92, 130, 62), (60, 92, 46)]

    if sub == "denso":
        dens = min(0.85, dens * 1.9 + 0.08)
    if sub == "claro":
        dens *= 0.45
    con_claro = sub in ("claro", "circulo", "campamento", "cementerio",
                        "oasis", "lago", "granja", "torre", "altar",
                        "madriguera", "geiseres")
    midx, midy = cols / 2, rows / 2
    r_claro = min(cols, rows) * (0.42 if sub in ("cementerio", "granja") else 0.3)

    for y in range(rows):
        for x in range(cols):
            rng = cel_rng(seed + 21, x, y)
            roll = rng()
            cx = x + 0.5 + (rng() - 0.5) * 0.3
            cy = y + 0.5 + (rng() - 0.5) * 0.3
            sendero = es_sendero(corr, x, y) or (
                con_claro and math.hypot(cx - midx, cy - midy) < r_claro)

            if tema == "nieve":
                if rng() < 0.5:
                    rx = 0.4 + rng() * 0.3
                    ry = 0.3 + rng() * 0.2
                    rng()   # rotacion (no soportada; consumir igual)
                    l.elipse(cx, cy, rx, ry, fill=(255, 255, 255, 128))
            if tema == "desierto":
                if rng() < 0.6:
                    l.linea(_qpts((x, cy), (cx, cy - 0.3), (x + 1, cy)),
                            (150, 120, 70, 89), 0.05)
                if rng() < 0.08 and not sendero:
                    l.linea([(cx - 0.3, cy), (cx + 0.1, cy + 0.2),
                             (cx + 0.35, cy - 0.15)], (90, 70, 40, 128), 0.04)
            if tema == "cienaga":
                if rng() < 0.22 and not sendero:
                    rot1, rot2 = rng(), None
                    l.elipse(cx, cy, 0.5, 0.38, fill=(50, 75, 65, 200))
                    rot2 = rng()
                    l.elipse(cx, cy, 0.5, 0.38, outline=(180, 200, 180, 64), w=0.03)
                    continue
            if tema == "volcanico":
                if rng() < 0.28 and not sendero:
                    grieta_lava(l, cx, cy, rng)
                if rng() < 0.05 and not sendero:
                    fumarola(l, cx, cy)

            if sendero and roll < 0.85:
                continue

            if roll < dens:
                r = 0.42 + rng() * 0.22
                if tema == "desierto":
                    if rng() < 0.6:
                        roca(l, cx, cy, r * 0.8, rng)
                    else:
                        arbusto(l, cx, cy, r * 0.7, rng, verdes)
                elif tema == "paso":
                    if rng() < 0.75:
                        roca(l, cx, cy, r * (0.8 + rng() * 0.7), rng)
                    else:
                        for _ in range(4):
                            px = cx + (rng() - 0.5) * 0.6
                            py = cy + (rng() - 0.5) * 0.6
                            rr = 0.08 + rng() * 0.08
                            l.elipse(px, py, rr, rr, fill=(60, 60, 66, 153))
                elif tema == "cienaga":
                    if rng() < 0.5:
                        for _ in range(5):
                            a = (cx + (rng() - 0.5) * 0.4, cy + 0.3)
                            b = (cx + (rng() - 0.5) * 0.5, cy - 0.4 - rng() * 0.2)
                            l.linea([a, b], _hx("#6b5a34"), 0.06)
                    else:
                        arbusto(l, cx, cy, r, rng, verdes)
                elif tema == "nieve":
                    if rng() < 0.4:
                        roca(l, cx, cy, r * 0.8, rng)
                    else:
                        arbol(l, cx, cy, r * 1.1, rng, True, verdes)
                        l.elipse(cx, cy - r * 0.6, r * 0.4, r * 0.4,
                                 fill=(255, 255, 255, 179))
                elif tema == "volcanico":
                    if rng() < 0.82:
                        roca_basalto(l, cx, cy, r * (0.7 + rng() * 0.6), rng)
                    else:
                        arbusto(l, cx, cy, r * 0.6, rng, verdes)
                else:
                    t = rng()
                    if t < 0.62:
                        arbol(l, cx, cy, r * (1.25 if tema == "selva" else 1.1),
                              rng, conif, verdes)
                    elif t < 0.78:
                        arbusto(l, cx, cy, r * 0.8, rng, verdes)
                    elif t < 0.9:
                        roca(l, cx, cy, r * 0.7, rng)
                    else:
                        tronco(l, cx, cy, r, rng)
            elif (not sendero and rng() < 0.12
                    and tema in ("pradera", "bosque", "selva")):
                flor(l, cx, cy, 1, rng)

    if sub == "campamento":
        campamento(l, cols, rows, seed)
    elif sub == "ruinas":
        ruinas(l, cols, rows, seed)
    elif sub == "circulo":
        circulo_piedras(l, cols, rows, seed)
    elif sub == "cementerio":
        cementerio(l, cols, rows, seed)
    elif sub == "oasis":
        oasis(l, cols, rows, seed)
    elif sub == "canon":
        canon(l, cols, rows, seed, corr)
    elif sub == "lago":
        lago_helado(l, cols, rows, seed)
    elif sub == "mina":
        mina(l, cols, rows, seed)
    elif sub == "granja":
        granja(l, cols, rows, seed)
    elif sub == "torre":
        torre_ruinas(l, cols, rows, seed)
    elif sub == "altar":
        altar_profanado(l, cols, rows, seed)
    elif sub == "cruce":
        cruce_caminos(l, cols, rows, seed, corr)
    elif sub == "madriguera":
        madriguera(l, cols, rows, seed)
    elif sub == "geiseres":
        geiseres(l, cols, rows, seed)


def campamento(l, cols, rows, seed):
    midx, midy = cols / 2, rows / 2
    fogata(l, midx, midy, 1.1)
    rng = Mulberry32(seed + 55)
    for _ in range(2 + int(rng() * 3)):
        a = rng() * TAU
        rr = 2.2 + rng() * 2
        tienda(l, midx + math.cos(a) * rr, midy + math.sin(a) * rr, 1.1, rng)
    for _ in range(2 + int(rng() * 2)):
        barril(l, midx + (rng() - 0.5) * 5, midy + (rng() - 0.5) * 5, rng)


def muro_ruina(l, x, y, ln, horizontal, rng):
    for i in range(int(ln)):
        if rng() < 0.28:
            continue
        px = x + (i if horizontal else 0)
        py = y + (0 if horizontal else i)
        sombra(l, px + 0.5, py + 0.55, 0.55, 0.25)
        alto = 0.5 + rng() * 0.2
        if horizontal:
            l.rect(px, py, 1.02, alto, fill=_hx("#71747b"),
                   outline=(30, 32, 36, 140), ow=0.05)
        else:
            l.rect(px, py, alto, 1.02, fill=_hx("#71747b"),
                   outline=(30, 32, 36, 140), ow=0.05)


def ruinas(l, cols, rows, seed):
    rng = Mulberry32(seed + 404)
    midx, midy = cols / 2, rows / 2
    w = min(cols - 4, 5 + int(rng() * 4))
    h = min(rows - 4, 4 + int(rng() * 3))
    x0, y0 = round(midx - w / 2), round(midy - h / 2)
    muro_ruina(l, x0, y0, w, True, rng)
    muro_ruina(l, x0, y0 + h, w, True, rng)
    muro_ruina(l, x0, y0, h, False, rng)
    muro_ruina(l, x0 + w, y0, h, False, rng)
    for _ in range(3 + int(rng() * 3)):
        cx = x0 + rng() * w
        cy = y0 + rng() * h
        if rng() < 0.5:
            columna(l, cx, cy)
        else:
            ang = rng() * 3.14
            ca, sa = math.cos(ang), math.sin(ang)
            sombra(l, cx, cy + 0.15, 0.9, 0.3)
            a = (cx - ca * 0.8, cy - sa * 0.8)
            b = (cx + ca * 0.8, cy + sa * 0.8)
            l.linea([a, b], _hx("#686b71"), 0.56)
            l.linea([a, b], (30, 32, 36, 128), 0.05)
    for _ in range(10):
        a = rng() * TAU
        rr = rng() * max(w, h) * 0.8
        roca(l, midx + math.cos(a) * rr, midy + math.sin(a) * rr,
             0.18 + rng() * 0.2, rng)


def columna(l, cx, cy):
    sombra(l, cx, cy + 0.2, 0.7, 0.35)
    l.elipse(cx, cy, 0.5, 0.5, fill=_hx("#70747c"))
    l.elipse(cx, cy, 0.62, 0.62, outline=(20, 20, 24, 128), w=0.04)


def circulo_piedras(l, cols, rows, seed):
    rng = Mulberry32(seed + 505)
    midx, midy = cols / 2, rows / 2
    R = min(cols, rows) * 0.26
    n = 6 + int(rng() * 3)
    for k in range(n):
        a = k / n * TAU + rng() * 0.15
        cx = midx + math.cos(a) * R
        cy = midy + math.sin(a) * R
        sombra(l, cx + 0.1, cy + 0.5, 0.5, 0.25)
        ang = (rng() - 0.5) * 0.25
        ca, sa = math.cos(ang), math.sin(ang)

        def rot(px, py):
            return (cx + px * ca - py * sa, cy + px * sa + py * ca)
        pts = [rot(-0.32, 0.55), rot(-0.28, -0.6), rot(0, -0.78),
               rot(0.3, -0.55), rot(0.34, 0.55)]
        l.poli(pts, fill=_hx("#6d7278"), outline=(30, 32, 36, 128), w=0.05)
    sombra(l, midx, midy + 0.3, 1.0, 0.4)
    l.rect(midx - 1, midy - 0.5, 2, 1, fill=_hx("#6c6f76"),
           outline=(30, 32, 36, 140), ow=0.06)
    for k in range(4):
        rx = midx - 0.7 + k * 0.45
        l.linea([(rx, midy - 0.25), (rx + 0.12, midy + 0.25)], (240, 240, 220, 89), 0.04)
        l.linea([(rx + 0.12, midy - 0.25), (rx, midy + 0.05)], (240, 240, 220, 89), 0.04)


def lapida(l, cx, cy, rng):
    sombra(l, cx + 0.06, cy + 0.32, 0.32, 0.14)
    fill = _hx("#74777d")
    ang = (rng() - 0.5) * 0.3
    ca, sa = math.cos(ang), math.sin(ang)

    def rot(px, py):
        return (cx + px * ca - py * sa, cy + px * sa + py * ca)
    if rng() < 0.6:
        arco = [rot(-0.22 + 0.22 * (1 - math.cos(t * math.pi)),
                    -0.12 - 0.22 * math.sin(t * math.pi))
                for t in [i / 8 for i in range(9)]]
        l.poli([rot(-0.22, 0.3)] + arco + [rot(0.22, 0.3)], fill=fill)
    else:
        l.poli([rot(-0.07, -0.35), rot(0.07, -0.35), rot(0.07, 0.3),
                rot(-0.07, 0.3)], fill=fill)
        l.poli([rot(-0.22, -0.2), rot(0.22, -0.2), rot(0.22, -0.07),
                rot(-0.22, -0.07)], fill=fill)


def cementerio(l, cols, rows, seed):
    rng = Mulberry32(seed + 606)
    midx, midy = cols / 2, rows / 2
    w = min(cols - 4, 8 + int(rng() * 4))
    h = min(rows - 4, 6 + int(rng() * 3))
    x0, y0 = midx - w / 2, midy - h / 2
    l.rect(x0, y0, w, h, fill=(70, 58, 40, 89))
    l.rect(x0, y0, w, h, outline=_hx("#4a3a26"), ow=0.08)
    i = 0.0
    while i <= w:
        l.rect(x0 + i - 0.06, y0 - 0.18, 0.12, 0.36, fill=_hx("#5a4830"))
        l.rect(x0 + i - 0.06, y0 + h - 0.18, 0.12, 0.36, fill=_hx("#5a4830"))
        i += 1.2
    i = 0.0
    while i <= h:
        l.rect(x0 - 0.18, y0 + i - 0.06, 0.36, 0.12, fill=_hx("#5a4830"))
        l.rect(x0 + w - 0.18, y0 + i - 0.06, 0.36, 0.12, fill=_hx("#5a4830"))
        i += 1.2
    gy = y0 + 1.2
    while gy < y0 + h - 0.5:
        gx = x0 + 1
        while gx < x0 + w - 0.6:
            if rng() < 0.72:
                lapida(l, gx + (rng() - 0.5) * 0.4, gy + (rng() - 0.5) * 0.3, rng)
            elif rng() < 0.25:
                l.rect(gx - 0.3, gy - 0.15, 0.7, 0.45, fill=(35, 28, 20, 191))
            gx += 1.4
        gy += 1.7
    mx, my = x0 + w - 2.3, y0 + 0.4
    sombra(l, mx + 1, my + 1.5, 1.3, 0.4)
    l.rect(mx, my, 2, 1.6, fill=_hx("#686b72"), outline=(30, 32, 36, 153), ow=0.06)
    l.rect(mx + 0.75, my + 0.7, 0.5, 0.9, fill=_hx("#1c2026"))
    tx, ty = x0 + 0.8, y0 + h - 0.8
    l.linea([(tx, ty), (tx + 0.3, ty - 1.2)], _hx("#3d3226"), 0.12)
    l.linea([(tx + 0.15, ty - 0.6), (tx - 0.4, ty - 1.4)], _hx("#3d3226"), 0.12)
    l.linea([(tx + 0.3, ty - 1.2), (tx + 0.7, ty - 1.8)], _hx("#3d3226"), 0.12)


def palmera(l, cx, cy, r, rng):
    sombra(l, cx + r * 0.3, cy + r * 0.4, r * 0.9, r * 0.35)
    lean = (rng() - 0.5) * 0.8
    l.linea(_qpts((cx, cy + r * 0.4), (cx + lean * r * 0.5, cy - r * 0.2),
                  (cx + lean * r, cy - r * 0.7)), _hx("#7a5a34"), r * 0.14)
    tx, ty = cx + lean * r, cy - r * 0.7
    for k in range(6):
        a = k / 6 * TAU
        l.linea(_qpts((tx, ty),
                      (tx + math.cos(a) * r * 0.5, ty + math.sin(a) * r * 0.35 - r * 0.25),
                      (tx + math.cos(a) * r * 0.95, ty + math.sin(a) * r * 0.55)),
                _hx("#3f7a3a"), r * 0.1)
    l.elipse(tx, ty, r * 0.12, r * 0.12, fill=_hx("#8a6a3a"))


def oasis(l, cols, rows, seed):
    rng = Mulberry32(seed + 707)
    midx, midy = cols / 2, rows / 2
    R = min(cols, rows) * 0.2
    l.radial(midx, midy, R * 2.1,
             [(0.0, (96, 130, 60, 191)), (1.0, (96, 130, 60, 0))])
    pts = []
    for k in range(25):
        a = k / 24 * TAU
        rr = R * (0.85 + fbm(math.cos(a) + 3, math.sin(a) + 3, seed + 8, 2) * 0.4)
        pts.append((midx + math.cos(a) * rr, midy + math.sin(a) * rr * 0.8))
    l.poli_radial(pts, midx, midy, R, [(0.0, _hx("#4fa3b8")), (1.0, _hx("#2b6076"))])
    l.poli(pts, outline=(255, 255, 255, 102), w=0.1)
    n = 4 + int(rng() * 3)
    for _ in range(n):
        a = rng() * TAU
        rr = R * (1.25 + rng() * 0.6)
        palmera(l, midx + math.cos(a) * rr, midy + math.sin(a) * rr * 0.85,
                0.9 + rng() * 0.4, rng)
    verdes = [(130, 160, 80), (86, 120, 56), (54, 84, 40)]
    for _ in range(6):
        a = rng() * TAU
        rr = R * (1.1 + rng() * 0.9)
        arbusto(l, midx + math.cos(a) * rr, midy + math.sin(a) * rr * 0.85,
                0.5, rng, verdes)


def canon(l, cols, rows, seed, corr):
    rng = Mulberry32(seed + 808)
    horizontal = corr["horizontal"]
    ancho = rows if horizontal else cols
    banda = max(2.5, ancho * 0.26)
    largo = cols if horizontal else rows

    def pared(lado):
        borde = banda if lado < 0 else ancho - banda
        pts = [borde + (fbm(i * 0.3, lado * 7 + 9, seed + 13, 3) - 0.5) * 2.2
               for i in range(largo + 1)]
        if horizontal:
            poly = [(0, 0 if lado < 0 else ancho), (0, pts[0])]
            poly += [(i, pts[i]) for i in range(largo + 1)]
            poly.append((largo, 0 if lado < 0 else ancho))
        else:
            poly = [(0 if lado < 0 else ancho, 0), (pts[0], 0)]
            poly += [(pts[i], i) for i in range(largo + 1)]
            poly.append((0 if lado < 0 else ancho, largo))
        l.poli(poly, fill=_hx("#4a4744"))
        cresta = [((i, pts[i]) if horizontal else (pts[i], i))
                  for i in range(largo + 1)]
        l.linea(cresta, (230, 220, 200, 77), 0.12)
        for _ in range(int(largo * 0.5)):
            t = rng() * largo
            off = rng() * 1.2
            c = borde + (off if lado < 0 else -off)
            roca(l, t if horizontal else c, c if horizontal else t,
                 0.25 + rng() * 0.3, rng)
    pared(-1)
    pared(1)


def lago_helado(l, cols, rows, seed):
    rng = Mulberry32(seed + 909)
    midx, midy = cols / 2, rows / 2
    R = min(cols, rows) * 0.32
    pts = []
    for k in range(29):
        a = k / 28 * TAU
        rr = R * (0.85 + fbm(math.cos(a) + 5, math.sin(a) + 5, seed + 17, 2) * 0.35)
        pts.append((midx + math.cos(a) * rr, midy + math.sin(a) * rr * 0.85))
    l.poli_radial(pts, midx, midy, R,
                  [(0.0, _hx("#cfe8f2")), (0.7, _hx("#9cc6dc")), (1.0, _hx("#7aa8c4"))])
    l.poli(pts, outline=(255, 255, 255, 179), w=0.14)
    for _ in range(7):
        a = rng() * TAU
        px, py = midx, midy
        cam = [(px, py)]
        for _ in range(6):
            a += (rng() - 0.5) * 0.8
            px += math.cos(a) * R * 0.2
            py += math.sin(a) * R * 0.2
            cam.append((px, py))
        l.linea(cam, (70, 110, 140, 140), 0.05)
    if rng() < 0.6:
        l.elipse(midx + R * 0.3, midy - R * 0.2, 0.35, 0.35, fill=_hx("#27454f"))


def mina(l, cols, rows, seed):
    rng = Mulberry32(seed + 111)
    prof = 3.2
    borde = [prof + (fbm(i * 0.35, 3, seed + 19, 3) - 0.5) * 1.6
             for i in range(cols + 1)]
    poly = [(0, 0), (cols, 0)] + [(i, borde[i]) for i in range(cols, -1, -1)]
    l.poli(poly, fill=_hx("#57534f"))
    l.linea([(i, borde[i]) for i in range(cols + 1)], (230, 220, 200, 64), 0.1)
    bx = cols / 2
    boca = ([(bx - 1.2, prof + 0.6), (bx - 1.2, 1.2)]
            + [(bx - 1.2 * math.cos(t * math.pi), 1.2 - 1.2 * math.sin(t * math.pi))
               for t in [i / 10 for i in range(11)]]
            + [(bx + 1.2, prof + 0.6)])
    l.poli(boca, fill=_hx("#0d0f13"))
    l.linea([(bx - 1.35, prof + 0.6), (bx - 1.35, 1.0)], _hx("#6b4a28"), 0.22)
    l.linea([(bx + 1.35, prof + 0.6), (bx + 1.35, 1.0)], _hx("#6b4a28"), 0.22)
    l.linea([(bx - 1.5, 1.05), (bx + 1.5, 1.05)], _hx("#6b4a28"), 0.22)
    l.linea([(bx - 0.35, prof + 0.4), (bx - 0.35, rows * 0.7)], _hx("#7c7a76"), 0.07)
    l.linea([(bx + 0.35, prof + 0.4), (bx + 0.35, rows * 0.7)], _hx("#7c7a76"), 0.07)
    y = prof + 0.6
    while y < rows * 0.7:
        l.linea([(bx - 0.5, y), (bx + 0.5, y)], _hx("#5a4630"), 0.09)
        y += 0.7
    vy = prof + 1.5 + rng() * 2
    sombra(l, bx, vy + 0.4, 0.7, 0.25)
    l.rect(bx - 0.55, vy - 0.4, 1.1, 0.8, fill=_hx("#4a3a2a"),
           outline=_hx("#2c221a"), ow=0.06)
    for _ in range(4):
        l.elipse(bx - 0.3 + rng() * 0.6, vy - 0.1 + rng() * 0.2, 0.14, 0.14,
                 fill=_hx("#6e6a66"))
    for _ in range(3):
        barril(l, bx - 3 + rng() * 1.4, prof + 0.8 + rng() * 1.4, rng)


def granja(l, cols, rows, seed):
    rng = Mulberry32(seed + 222)
    w = min(cols - 7, 8 + int(rng() * 4))
    h = min(rows - 6, 5 + int(rng() * 3))
    x0 = round(2 + rng() * 2)
    y0 = round(rows / 2 - h / 2)
    l.rect(x0, y0, w, h, fill=_hx("#705334"))
    i = 0.5
    while i < h:
        l.linea([(x0 + 0.2, y0 + i), (x0 + w - 0.2, y0 + i)], (50, 36, 20, 140), 0.09)
        i += 0.75
    i = 0.5
    while i < h:
        j = 0.4
        while j < w:
            if rng() < 0.7:
                l.elipse(x0 + j, y0 + i - 0.12, 0.08, 0.08, fill=(120, 160, 70, 204))
            j += 0.5
        i += 0.75
    l.rect(x0 - 0.3, y0 - 0.3, w + 0.6, h + 0.6, outline=_hx("#4a3a26"), ow=0.08)
    i = 0.0
    while i <= w + 0.6:
        l.rect(x0 - 0.3 + i - 0.06, y0 - 0.42, 0.12, 0.3, fill=_hx("#5a4830"))
        l.rect(x0 - 0.3 + i - 0.06, y0 + h + 0.12, 0.12, 0.3, fill=_hx("#5a4830"))
        i += 1.2
    casa(l, min(cols - 4.5, x0 + w + 1), max(1.5, y0 - 0.5), 3, 3, rng)
    for _ in range(3):
        hx = min(cols - 1, x0 + w + 1 + rng() * 2)
        hy = min(rows - 1, y0 + h - 1 + rng() * 1.5)
        sombra(l, hx, hy + 0.25, 0.5, 0.2)
        l.elipse(hx, hy, 0.4, 0.4, fill=_hx("#c9a94f"), outline=_hx("#9a7c34"), w=0.05)
        l.elipse(hx, hy, 0.22, 0.22, outline=_hx("#9a7c34"), w=0.05)


def puesto(l, cx, cy, rng):
    sombra(l, cx, cy + 0.5, 0.9, 0.3)
    l.rect(cx - 0.8, cy - 0.1, 1.6, 0.7, fill=_hx("#8a6238"))
    toldos = [("#b8433a", "#e8e4da"), ("#3a6a8c", "#e8e4da"), ("#7a8c3a", "#e8e4da")]
    c = toldos[int(rng() * len(toldos))]
    for i in range(6):
        l.rect(cx - 0.9 + i * 0.3, cy - 0.75, 0.3, 0.5, fill=_hx(c[i % 2]))
    l.rect(cx - 0.9, cy - 0.75, 1.8, 0.5, outline=_hx("#4a3220"), ow=0.07)
    l.elipse(cx - 0.4, cy + 0.2, 0.14, 0.14, fill=_hx("#d8b04a"))
    l.elipse(cx + 0.1, cy + 0.25, 0.12, 0.12, fill=_hx("#b8433a"))
    l.elipse(cx + 0.45, cy + 0.15, 0.13, 0.13, fill=_hx("#7a8c3a"))


# ---- tierras volcanicas ----
def roca_basalto(l, cx, cy, r, rng):
    """Bloque de basalto oscuro con aristas y, a veces, veta incandescente."""
    sombra(l, cx + r * 0.15, cy + r * 0.4, r * 1.0, r * 0.45)
    pts = poly_facet(cx, cy, r, 6 + int(rng() * 2), rng)
    l.poli(pts, fill=_hx("#3a3236"))
    l.linea([(cx - r * 0.3, cy - r * 0.2), (cx + r * 0.1, cy + r * 0.15),
             (cx + r * 0.45, cy - r * 0.25)], (14, 14, 18, 140), r * 0.06)
    if rng() < 0.35:
        l.linea([(cx - r * 0.25, cy + r * 0.1), (cx + r * 0.05, cy - r * 0.05),
                 (cx + r * 0.3, cy + r * 0.2)], (255, 120, 40, 150), r * 0.05)
    l.elipse(cx - r * 0.25, cy - r * 0.3, r * 0.3, r * 0.16, fill=(255, 150, 90, 30))


def grieta_lava(l, cx, cy, rng):
    """Fisura brillante de roca fundida en el suelo."""
    ang = rng() * TAU
    ca, sa = math.cos(ang), math.sin(ang)
    ln = 0.4 + rng() * 0.5
    a = (cx - ca * ln, cy - sa * ln)
    b = (cx + ca * ln, cy + sa * ln)
    m = (cx + (rng() - 0.5) * 0.3, cy + (rng() - 0.5) * 0.3)
    l.radial(cx, cy, ln * 1.4,
             [(0.0, (255, 180, 90, 150)), (1.0, (255, 120, 40, 0))])
    l.linea(_qpts(a, m, b), (30, 16, 14, 200), 0.14)
    l.linea(_qpts(a, m, b), (255, 170, 70, 220), 0.06)
    l.linea(_qpts(a, m, b), (255, 240, 190, 200), 0.02)


def fumarola(l, cx, cy):
    """Chimenea humeante con boca ardiente."""
    sombra(l, cx, cy + 0.25, 0.5, 0.2)
    l.elipse(cx, cy, 0.4, 0.32, fill=_hx("#2e2a2c"))
    l.elipse(cx, cy, 0.18, 0.14, fill=(255, 150, 60, 220))
    l.radial(cx, cy - 0.5, 0.6,
             [(0.0, (180, 180, 185, 120)), (1.0, (180, 180, 185, 0))])


def geiseres(l, cols, rows, seed):
    """Campo de géiseres: pozas humeantes y un chorro central."""
    rng = Mulberry32(seed + 313)
    midx, midy = cols / 2, rows / 2
    n = 3 + int(rng() * 3)
    for _ in range(n):
        a = rng() * TAU
        rr = min(cols, rows) * (0.1 + rng() * 0.32)
        px = midx + math.cos(a) * rr
        py = midy + math.sin(a) * rr * 0.85
        R = 0.6 + rng() * 0.7
        l.radial(px, py, R * 1.6,
                 [(0.0, (210, 235, 240, 150)), (1.0, (210, 235, 240, 0))])
        l.elipse(px, py, R, R * 0.7, fill=_hx("#7fb4bd"),
                 outline=(230, 245, 248, 160), w=0.06)
        l.elipse(px, py, R * 0.55, R * 0.4, fill=_hx("#c7a24a"))
        for _ in range(int(4 + rng() * 3)):
            roca(l, px + (rng() - 0.5) * R * 2.4, py + (rng() - 0.5) * R * 2.0,
                 0.14 + rng() * 0.16, rng)
    # chorro central
    l.radial(midx, midy - 0.4, 1.4,
             [(0.0, (235, 248, 250, 180)), (1.0, (235, 248, 250, 0))])
    l.linea([(midx, midy + 0.4), (midx - 0.1, midy - 1.6)], (240, 250, 252, 150), 0.24)
    l.linea([(midx, midy + 0.4), (midx + 0.12, midy - 1.9)], (255, 255, 255, 120), 0.12)


# ---- torre, altar, cruce, madriguera (subtipos comunes) ----
def torre_ruinas(l, cols, rows, seed):
    """Torre circular derruida con escombros y un tramo de muro."""
    rng = Mulberry32(seed + 414)
    cx = cols * (0.4 + rng() * 0.2)
    cy = rows * (0.4 + rng() * 0.2)
    R = min(cols, rows) * (0.13 + rng() * 0.05)
    sombra(l, cx + R * 0.2, cy + R * 0.5, R * 1.15, R * 0.5)
    # anillo de base (muro grueso con almenas rotas)
    n = 16
    ext, inte = [], []
    for k in range(n + 1):
        a = k / n * TAU
        rot = R * (1.0 + (fbm(math.cos(a) + 2, math.sin(a) + 2, seed + 41, 2) - 0.5) * 0.5)
        # almenas rotas: algunos tramos ausentes
        ext.append((cx + math.cos(a) * rot, cy + math.sin(a) * rot))
        inte.append((cx + math.cos(a) * rot * 0.62, cy + math.sin(a) * rot * 0.62))
    l.poli(ext, fill=_hx("#6f727a"))
    l.poli(inte, fill=_hx("#2a2c31"))
    for k in range(0, n, 2):
        a = k / n * TAU
        rot = R * 1.02
        bx = cx + math.cos(a) * rot
        by = cy + math.sin(a) * rot
        if rng() < 0.6:
            l.rect(bx - 0.22, by - 0.22, 0.44, 0.44, fill=_hx("#7a7d85"),
                   outline=(30, 32, 36, 140), ow=0.05)
    l.poli(ext, outline=(24, 26, 30, 150), w=0.08)
    l.poli(inte, outline=(20, 20, 24, 160), w=0.05)
    # tramo de muro colapsado saliendo de la torre
    ang = rng() * TAU
    ca, sa = math.cos(ang), math.sin(ang)
    x0 = cx + ca * R
    y0 = cy + sa * R
    muro_ruina(l, round(x0), round(y0), 3 + int(rng() * 3),
               abs(ca) >= abs(sa), rng)
    for _ in range(6 + int(rng() * 4)):
        a = rng() * TAU
        rr = R * (1.1 + rng() * 1.0)
        roca(l, cx + math.cos(a) * rr, cy + math.sin(a) * rr,
             0.18 + rng() * 0.24, rng)


def altar_profanado(l, cols, rows, seed):
    """Losa central con velas apagadas, runas y sangre reseca."""
    rng = Mulberry32(seed + 515)
    midx, midy = cols / 2, rows / 2
    # halo profano
    l.radial(midx, midy, min(cols, rows) * 0.3,
             [(0.0, (90, 30, 40, 90)), (1.0, (90, 30, 40, 0))])
    # anillo de piedras derribadas
    R = min(cols, rows) * 0.24
    n = 5 + int(rng() * 3)
    for k in range(n):
        a = k / n * TAU + rng() * 0.2
        px = midx + math.cos(a) * R
        py = midy + math.sin(a) * R * 0.85
        sombra(l, px, py + 0.3, 0.4, 0.18)
        if rng() < 0.5:
            l.rect(px - 0.28, py - 0.16, 0.56, 0.32, fill=_hx("#5c5056"),
                   outline=(24, 20, 24, 140), ow=0.05)
        else:
            l.rect(px - 0.16, py - 0.5, 0.32, 1.0, fill=_hx("#65686f"),
                   outline=(24, 24, 28, 140), ow=0.05)
    # losa
    w, h = 2.2, 1.4
    sombra(l, midx, midy + 0.4, w * 0.7, 0.5)
    l.rect(midx - w / 2, midy - h / 2, w, h, fill=_hx("#5a5258"),
           outline=(20, 18, 22, 170), ow=0.08)
    l.rect(midx - w / 2 + 0.15, midy - h / 2 + 0.12, w - 0.3, h - 0.24,
           outline=(20, 18, 22, 120), ow=0.04)
    # manchas y goteo
    for _ in range(5):
        l.elipse(midx + (rng() - 0.5) * (w - 0.5), midy + (rng() - 0.5) * (h - 0.4),
                 0.1 + rng() * 0.12, 0.08 + rng() * 0.08, fill=(96, 14, 18, 190))
    l.linea([(midx + 0.2, midy + h / 2), (midx + 0.3, midy + h / 2 + 0.7)],
            (96, 14, 18, 190), 0.06)
    # velas negras en las esquinas
    for sx in (-1, 1):
        for sy in (-1, 1):
            vx = midx + sx * (w / 2 + 0.3)
            vy = midy + sy * (h / 2 + 0.2)
            l.rect(vx - 0.06, vy - 0.1, 0.12, 0.4, fill=_hx("#1c1a1e"))
            l.radial(vx, vy - 0.2, 0.4,
                     [(0.0, (150, 60, 200, 160)), (1.0, (150, 60, 200, 0))])
            l.elipse(vx, vy - 0.24, 0.06, 0.08, fill=_hx("#b47adf"))


def cruce_caminos(l, cols, rows, seed, corr):
    """Cruz de dos sendas de tierra con mojón/poste indicador."""
    rng = Mulberry32(seed + 616)
    midx, midy = cols / 2, rows / 2
    tierra = (120, 96, 60, 150)
    l.rect(0, midy - 1.1, cols, 2.2, fill=tierra)
    l.rect(midx - 1.1, 0, 2.2, rows, fill=tierra)
    # roderas
    for off in (-0.5, 0.5):
        l.linea([(0, midy + off), (cols, midy + off)], (90, 68, 40, 120), 0.05)
        l.linea([(midx + off, 0), (midx + off, rows)], (90, 68, 40, 120), 0.05)
    # poste indicador
    px, py = midx + 1.4, midy - 1.2
    sombra(l, px, py + 0.2, 0.4, 0.18)
    l.rect(px - 0.08, py - 1.4, 0.16, 1.6, fill=_hx("#6b4a28"))
    for k in range(2 + int(rng() * 2)):
        yy = py - 1.2 + k * 0.4
        dirx = 1 if rng() < 0.5 else -1
        l.poli([(px, yy), (px + dirx * 0.9, yy - 0.16),
                (px + dirx * 0.9, yy + 0.16)], fill=_hx("#8a6238"),
               outline=_hx("#4a3220"), w=0.04)
    # piedras al borde del cruce
    for _ in range(6):
        a = rng() * TAU
        rr = 1.6 + rng() * 1.4
        roca(l, midx + math.cos(a) * rr, midy + math.sin(a) * rr,
             0.16 + rng() * 0.18, rng)


def madriguera(l, cols, rows, seed):
    """Montículo con bocas de túnel, tierra removida y huesecillos."""
    rng = Mulberry32(seed + 717)
    midx, midy = cols / 2, rows / 2
    R = min(cols, rows) * 0.22
    # montículo de tierra
    l.radial(midx, midy, R * 1.3,
             [(0.0, (86, 64, 40, 220)), (0.7, (74, 54, 34, 200)),
              (1.0, (74, 54, 34, 0))])
    n = 3 + int(rng() * 3)
    for _ in range(n):
        a = rng() * TAU
        rr = R * (0.2 + rng() * 0.7)
        bx = midx + math.cos(a) * rr
        by = midy + math.sin(a) * rr * 0.8
        rad = 0.35 + rng() * 0.3
        sombra(l, bx, by + rad * 0.4, rad * 1.1, rad * 0.5)
        l.elipse(bx, by, rad, rad * 0.8, fill=_hx("#5a4530"))
        l.elipse(bx, by + rad * 0.1, rad * 0.6, rad * 0.5, fill=_hx("#120d0a"))
        # tierra removida
        for _ in range(3):
            l.elipse(bx + (rng() - 0.5) * rad * 2.4, by + rad * 0.6 + rng() * 0.4,
                     0.1, 0.07, fill=(70, 52, 32, 180))
    # huesecillos
    for _ in range(4 + int(rng() * 3)):
        hx = midx + (rng() - 0.5) * R * 2.4
        hy = midy + (rng() - 0.5) * R * 2.0
        l.linea([(hx, hy), (hx + 0.25, hy + 0.1)], (220, 214, 198, 200), 0.04)


# ---- puerto / muelle ----
def props_puerto(l, cols, rows, seed, corr, sub):
    rng = Mulberry32(seed + 818)
    mar_abajo = rng() < 0.5
    linea = rows * (0.42 + rng() * 0.16)
    pts = [(i, linea + (fbm(i * 0.35, 9, seed + 46, 3) - 0.5) * 1.8)
           for i in range(cols + 1)]
    if mar_abajo:
        poly = [(0, rows), (0, pts[0][1])] + pts + [(cols, rows)]
    else:
        poly = [(0, 0), (0, rows - pts[0][1])] + [(p[0], rows - p[1]) for p in pts] \
               + [(cols, 0)]
    l.poli(poly, fill=_hx("#26697f"))
    # brillos y espuma
    for k in range(cols):
        yy = (linea if mar_abajo else rows - linea) + (rng() - 0.5) * 2
        l.linea([(k, yy), (k + 0.8, yy + (rng() - 0.5) * 0.3)],
                (255, 255, 255, 56), 0.06)
    espuma = [(i, (p if mar_abajo else rows - p))
              for i, p in ((q[0], q[1]) for q in pts)]
    l.linea(espuma, (255, 255, 255, 140), 0.16)

    def y_costa(x):
        j = min(int(round(x)), cols)
        base = pts[j][1]
        return base if mar_abajo else rows - base

    # muelle de madera hacia el mar
    mx = cols * (0.35 + rng() * 0.3)
    yc = y_costa(mx)
    largo_m = 2.5 + rng() * 3
    dir_m = 1 if mar_abajo else -1
    l.rect(mx - 0.8, min(yc, yc + dir_m * largo_m), 1.6, abs(largo_m),
           fill=_hx("#9c7642"), outline=_hx("#4a3220"), ow=0.08)
    i = 0.0
    while i <= largo_m:
        yy = yc + dir_m * i
        l.linea([(mx - 0.8, yy), (mx + 0.8, yy)], _hx("#5a3d22"), 0.05)
        i += 0.7
    for pil in (mx - 0.7, mx + 0.7):
        l.elipse(pil, yc + dir_m * largo_m, 0.12, 0.12, fill=_hx("#3a2718"))
    # barca amarrada
    bx = mx + 1.4
    by = yc + dir_m * (largo_m * 0.6)
    sombra(l, bx, by + 0.2, 0.9, 0.3)
    barca = (_qpts((bx - 0.9, by), (bx, by + 0.5), (bx + 0.9, by))
             + _qpts((bx + 0.9, by), (bx, by - 0.15), (bx - 0.9, by)))
    l.poli(barca, fill=_hx("#6b4a28"), outline=_hx("#3a2718"), w=0.06)
    l.linea([(bx, by), (bx + 0.05, by - 1.1)], _hx("#5a3d22"), 0.05)

    if sub == "embarcadero":
        # segundo muelle y más barcas
        m2 = cols * (0.15 + rng() * 0.15)
        yc2 = y_costa(m2)
        lg2 = 2 + rng() * 2.5
        l.rect(m2 - 0.6, min(yc2, yc2 + dir_m * lg2), 1.2, abs(lg2),
               fill=_hx("#9c7642"), outline=_hx("#4a3220"), ow=0.08)
        for _ in range(2):
            barril(l, m2 + (rng() - 0.5) * 1.2, yc2 - dir_m * (0.4 + rng()), rng)

    # tierra: casas del puerto, cajas y barriles
    ocupadas = []

    def libre(x, y, w, h):
        for o in ocupadas:
            if (x < o[0] + o[2] + 1 and x + w + 1 > o[0]
                    and y < o[1] + o[3] + 1 and y + h + 1 > o[1]):
                return False
        return True

    n_casas = 2 + int(rng() * 3)
    k = 0
    while k < n_casas * 4 and len(ocupadas) < n_casas:
        k += 1
        w = 3 + int(rng() * 2)
        h = 3 + int(rng() * 2)
        x = 1 + int(rng() * (cols - w - 2))
        y = 1 + int(rng() * (rows - h - 2))
        # en tierra firme (lejos del agua)
        eje = y_costa(x + w / 2)
        en_agua = (y + h > eje - 0.5) if mar_abajo else (y < eje + 0.5)
        if en_agua or not libre(x, y, w, h):
            continue
        ocupadas.append((x, y, w, h))
        casa(l, x, y, w, h, rng)
    if sub == "mercado":
        for kk in range(3 + int(rng() * 2)):
            cxp = 2 + rng() * (cols - 4)
            cyp = (1 + rng() * (linea - 2)) if not mar_abajo \
                else (rows - linea + 1 + rng() * (linea - 2))
            puesto(l, cxp, cyp, rng)
    for _ in range(3 + int(rng() * 3)):
        cxb = 1 + rng() * (cols - 2)
        cyb = (1 + rng() * (linea - 1)) if not mar_abajo \
            else (rows - linea + 1 + rng() * (linea - 1))
        if rng() < 0.5:
            barril(l, cxb, cyb, rng)
        else:
            l.rect(cxb - 0.35, cyb - 0.35, 0.7, 0.7, fill=_hx("#7a5730"),
                   outline=_hx("#3a2718"), ow=0.05)


# ---- vado de rio ----
def props_vado(l, cols, rows, seed, corr, sub, puente_auto):
    rng = Mulberry32(seed + 33)
    horizontal_rio = rng() < 0.5
    ancho_rio = max(3, min(cols, rows) * 0.32)
    centro = (rows if horizontal_rio else cols) / 2 + (rng() - 0.5) * 2
    puente = (True if sub == "puente"
              else False if sub == "piedras" else bool(puente_auto))

    largo = cols if horizontal_rio else rows

    def orilla(offset):
        return [(i, centro + offset * (ancho_rio / 2
                 + (fbm(i * 0.3, offset, seed + 4, 3) - 0.5) * 1.4))
                for i in range(largo + 1)]
    oa, ob = orilla(-1), orilla(1)
    if horizontal_rio:
        poly = [(q[0], q[1]) for q in oa] + [(q[0], q[1]) for q in reversed(ob)]
    else:
        poly = [(q[1], q[0]) for q in oa] + [(q[1], q[0]) for q in reversed(ob)]
    l.poli(poly, fill=_hx("#3f92a8"), outline=(180, 200, 190, 102), w=0.12)
    for _ in range(largo * 2):
        t = rng() * largo
        c = centro + (rng() - 0.5) * ancho_rio * 0.7
        if horizontal_rio:
            l.linea([(t, c), (t + 0.5, c)], (255, 255, 255, 56), 0.05)
        else:
            l.linea([(c, t), (c, t + 0.5)], (255, 255, 255, 56), 0.05)

    cruce = largo / 2
    if puente:
        bw = 1.6
        madera = _hx("#9c7642")
        if horizontal_rio:
            l.rect(cruce - bw / 2, centro - ancho_rio, bw, ancho_rio * 2, fill=madera)
            i = 0
            while i <= ancho_rio * 2:
                l.linea([(cruce - bw / 2, centro - ancho_rio + i),
                         (cruce + bw / 2, centro - ancho_rio + i)], _hx("#5a3d22"), 0.06)
                i += 1
            l.rect(cruce - bw / 2, centro - ancho_rio, bw, ancho_rio * 2,
                   outline=_hx("#4a3220"), ow=0.1)
        else:
            l.rect(centro - ancho_rio, cruce - bw / 2, ancho_rio * 2, bw, fill=madera)
            i = 0
            while i <= ancho_rio * 2:
                l.linea([(centro - ancho_rio + i, cruce - bw / 2),
                         (centro - ancho_rio + i, cruce + bw / 2)], _hx("#5a3d22"), 0.06)
                i += 1
            l.rect(centro - ancho_rio, cruce - bw / 2, ancho_rio * 2, bw,
                   outline=_hx("#4a3220"), ow=0.1)
    else:
        rngp = Mulberry32(seed + 66)
        s = -ancho_rio
        while s <= ancho_rio:
            jx = (rngp() - 0.5) * 0.5
            px = cruce + jx if horizontal_rio else centro + s
            py = centro + s if horizontal_rio else cruce + jx
            roca(l, px, py, 0.36, rngp)
            s += 0.9

    verdes = [(150, 176, 100), (92, 130, 62), (60, 92, 46)]
    for y in range(rows):
        for x in range(cols):
            eje = y if horizontal_rio else x
            if abs(eje - centro) < ancho_rio / 2 + 0.6:
                continue
            if es_sendero(corr, x, y):
                continue
            rng2 = cel_rng(seed + 77, x, y)
            if rng2() < 0.16:
                cx, cy = x + 0.5, y + 0.5
                if rng2() < 0.5:
                    arbusto(l, cx, cy, 0.5, rng2, verdes)
                else:
                    for _ in range(4):
                        a = (cx + (rng2() - 0.5) * 0.3, cy + 0.3)
                        b = (cx + (rng2() - 0.5) * 0.4, cy - 0.4)
                        l.linea([a, b], _hx("#5f7a3a"), 0.05)


# ---- playa / acantilado ----
def suelo_playa(l, cols, rows, seed, sub):
    rng = Mulberry32(seed + 12)
    mar_abajo = rng() < 0.5
    linea = rows * (0.45 + rng() * 0.15)
    pts = [(i, linea + (fbm(i * 0.35, 5, seed + 6, 3) - 0.5) * 2.2)
           for i in range(cols + 1)]
    if mar_abajo:
        poly = [(0, rows), (0, pts[0][1])] + pts + [(cols, rows)]
    else:
        poly = [(0, 0), (0, rows - pts[0][1])] + [(p[0], rows - p[1]) for p in pts] \
               + [(cols, 0)]
    l.poli(poly, fill=_hx("#26697f"))
    for k in range(cols):
        yy = (linea if mar_abajo else rows - linea) + (rng() - 0.5) * 2 \
             + (0.6 if mar_abajo else -0.6)
        l.linea([(k, yy), (k + 0.8, yy + (rng() - 0.5) * 0.3)],
                (255, 255, 255, 77), 0.08)
    espuma = [(i, (p if mar_abajo else rows - p))
              for i, p in ((q[0], q[1]) for q in pts)]
    l.linea(espuma, (255, 255, 255, 140), 0.18)
    for _ in range(int(cols * 0.6)):
        x = rng() * cols
        ryn = rng() * linea if mar_abajo else rows - rng() * linea
        if rng() < 0.4:
            roca(l, x, ryn, 0.35 + rng() * 0.4, rng)

    if sub == "naufragio":
        cx = cols * (0.3 + rng() * 0.4)
        cy = linea + 0.6 if mar_abajo else rows - linea - 0.6
        ang = (rng() - 0.5) * 0.6
        ca, sa = math.cos(ang), math.sin(ang)

        def rot(px, py):
            return (cx + px * ca - py * sa, cy + px * sa + py * ca)
        sombra(l, cx, cy + 0.4, 3.2, 0.8)
        casco = (_qpts((-3, 0), (-1, -1.6), (2.6, -1.0))
                 + _qpts((2.6, -1.0), (3.4, -0.4), (2.9, 0.5))
                 + _qpts((2.9, 0.5), (0, 1.4), (-3, 0)))
        l.poli([rot(px, py) for px, py in casco], fill=_hx("#553b24"),
               outline=_hx("#2c1e12"), w=0.1)
        for k in range(5):
            t = -2.2 + k * 0.7
            l.linea([rot(px, py) for px, py in _qpts((t, -0.7), (t + 0.2, 0), (t, 0.8))],
                    _hx("#8a6238"), 0.12)
        l.linea([rot(0.5, -0.6), rot(4, -2)], _hx("#5a3d22"), 0.18)
        rngc = Mulberry32(seed + 31)
        for _ in range(4):
            barril(l, cx - 2 + rngc() * 5,
                   cy + (-1 if mar_abajo else 1) * (0.6 + rngc() * 2), rngc)
    elif sub == "embarcadero":
        mx = cols * (0.35 + rng() * 0.3)
        yc = linea if mar_abajo else rows - linea
        largo_m = 2.5 + rng() * 3
        dir_m = 1 if mar_abajo else -1
        l.rect(mx - 0.8, min(yc, yc + dir_m * largo_m), 1.6, abs(largo_m),
               fill=_hx("#9c7642"), outline=_hx("#4a3220"), ow=0.08)
        i = 0.0
        while i <= largo_m:
            yy = yc + dir_m * i
            l.linea([(mx - 0.8, yy), (mx + 0.8, yy)], _hx("#5a3d22"), 0.05)
            i += 0.7
        for pil in (mx - 0.7, mx + 0.7):
            l.elipse(pil, yc + dir_m * largo_m, 0.12, 0.12, fill=_hx("#3a2718"))
        bx = mx + 1.5
        by = yc + dir_m * (largo_m * 0.55)
        sombra(l, bx, by + 0.2, 0.9, 0.3)
        barca = (_qpts((bx - 0.9, by), (bx, by + 0.5), (bx + 0.9, by))
                 + _qpts((bx + 0.9, by), (bx, by - 0.15), (bx - 0.9, by)))
        l.poli(barca, fill=_hx("#6b4a28"), outline=_hx("#3a2718"), w=0.06)
        l.linea([(bx, by), (bx + 0.05, by - 1.1)], _hx("#5a3d22"), 0.05)
        rngb = Mulberry32(seed + 71)
        for _ in range(3):
            barril(l, mx - 1.4 + rngb() * 0.8, yc - dir_m * (0.5 + rngb()), rngb)
    elif sub == "acantilado":
        prof = 2.8
        arriba = mar_abajo
        borde = [prof + (fbm(i * 0.35, 8, seed + 23, 3) - 0.5) * 1.6
                 for i in range(cols + 1)]
        poly = [(0, 0 if arriba else rows), (cols, 0 if arriba else rows)]
        poly += [(i, borde[i] if arriba else rows - borde[i])
                 for i in range(cols, -1, -1)]
        l.poli(poly, fill=_hx("#57534f"))
        l.linea([(i, borde[i] if arriba else rows - borde[i])
                 for i in range(cols + 1)], (230, 220, 200, 64), 0.1)
        for _ in range(int(cols * 0.5)):
            x = rng() * cols
            dpr = prof + rng() * 1.4
            roca(l, x, dpr if arriba else rows - dpr, 0.25 + rng() * 0.3, rng)


# ---- aldea ----
def props_aldea(l, cols, rows, seed, corr, sub):
    rng = Mulberry32(seed + 44)
    n_casas = 1 + int(rng() * 2) if sub == "granja" else 3 + int(rng() * 3)
    if sub == "granja":
        granja(l, cols, rows, seed)
    ocupadas = []

    def libre(x, y, w, h):
        for o in ocupadas:
            if (x < o[0] + o[2] + 1 and x + w + 1 > o[0]
                    and y < o[1] + o[3] + 1 and y + h + 1 > o[1]):
                return False
        return True

    k = 0
    while k < n_casas * 4 and len(ocupadas) < n_casas:
        k += 1
        w = 3 + int(rng() * 2)
        h = 3 + int(rng() * 2)
        x = 1 + int(rng() * (cols - w - 2))
        y = 1 + int(rng() * (rows - h - 2))
        toca = any(es_sendero(corr, xx, yy)
                   for yy in range(y, y + h) for xx in range(x, x + w))
        if toca or not libre(x, y, w, h):
            continue
        ocupadas.append((x, y, w, h))
        casa(l, x, y, w, h, rng)
    px, py = cols / 2, rows / 2
    if sub != "mercado" and libre(int(px) - 1, int(py) - 1, 2, 2):
        pozo(l, px, py, rng)
    if sub == "mercado":
        rng2 = Mulberry32(seed + 99)
        n = 4 + int(rng2() * 3)
        for k in range(n):
            a = k / n * TAU + rng2() * 0.4
            rr = 2.4 + rng2() * 1.6
            puesto(l, px + math.cos(a) * rr, py + math.sin(a) * rr * 0.8, rng2)
        for _ in range(3):
            barril(l, px + (rng2() - 0.5) * 7, py + (rng2() - 0.5) * 5, rng2)
    verdes = [(110, 160, 78), (64, 118, 58), (34, 74, 40)]
    for y in range(rows):
        for x in range(cols):
            dentro = any(o[0] <= x < o[0] + o[2] and o[1] <= y < o[1] + o[3]
                         for o in ocupadas)
            if dentro or es_sendero(corr, x, y):
                continue
            r2 = cel_rng(seed + 88, x, y)
            if r2() < 0.1:
                arbol(l, x + 0.5, y + 0.5, 0.9, r2, False, verdes)
            elif r2() < 0.16:
                arbusto(l, x + 0.5, y + 0.5, 0.5, r2, verdes)


def casa(l, x, y, w, h, rng):
    sombra(l, x + w / 2 + 0.2, y + h + 0.05, w * 0.55, 0.35)
    base = ("#c9a878", "#a98757") if rng() < 0.5 else ("#b98d5c", "#93683f")
    l.rect(x, y, w, h, fill=_mid(_hx(base[0]), _hx(base[1])),
           outline=_hx("#5a3d22"), ow=0.12)
    for i in range(1, int(w)):
        l.linea([(x + i, y), (x + i, y + h)], (90, 61, 34, 153), 0.06)
    l.poli([(x - 0.25, y + 0.2), (x + w / 2, y - h * 0.4), (x + w + 0.25, y + 0.2)],
           fill=_hx("#7d4a34"), outline=_hx("#5a3020"), w=0.06)
    for i in range(1, int(w * 2)):
        l.linea([(x - 0.25 + i * 0.5, y + 0.2), (x + w / 2, y - h * 0.4)],
                (0, 0, 0, 51), 0.04)
    l.rect(x + w / 2 - 0.35, y + h - 0.9, 0.7, 0.9, fill=_hx("#4a3220"))
    l.rect(x + 0.35, y + 0.5, 0.5, 0.5, fill=_hx("#3a4a52"))
    l.rect(x + w - 0.85, y + 0.5, 0.5, 0.5, fill=_hx("#3a4a52"))


def pozo(l, cx, cy, rng):
    sombra(l, cx, cy + 0.15, 0.7, 0.3)
    l.elipse(cx, cy, 0.6, 0.6, fill=_hx("#7a7a80"))
    l.elipse(cx, cy, 0.4, 0.4, fill=_hx("#1a2228"))
    l.linea([(cx - 0.6, cy), (cx - 0.55, cy - 0.9)], _hx("#5a3d22"), 0.1)
    l.linea([(cx + 0.6, cy), (cx + 0.55, cy - 0.9)], _hx("#5a3d22"), 0.1)
    l.linea([(cx - 0.7, cy - 0.9), (cx + 0.7, cy - 0.9)], _hx("#7d4a34"), 0.14)


# ---- interiores ----
def dibujar_taberna(l, cols, rows, seed):
    rng = Mulberry32(seed + 101)
    l.rect(0, 0, cols, rows, fill=_hx("#3a3228"))
    m = 1
    x0, y0, w, h = m, m, cols - 2 * m, rows - 2 * m
    l.rect(x0, y0, w, h, fill=_hx("#7a5630"))
    for i in range(int(y0) + 1, int(y0 + h)):
        l.linea([(x0, i), (x0 + w, i)], (60, 40, 22, 140), 0.06)
    i = 0
    while i < h:
        off = (i % 2) * 1.5
        j = x0 + off
        while j < x0 + w:
            l.linea([(j, y0 + i), (j, y0 + i + 1)], (60, 40, 22, 140), 0.06)
            j += 3
        i += 1
    l.rect(x0 - 0.25, y0 - 0.25, w + 0.5, 0.5, fill=_hx("#4a3220"))
    l.rect(x0 - 0.25, y0 + h - 0.25, w + 0.5, 0.5, fill=_hx("#4a3220"))
    l.rect(x0 - 0.25, y0 - 0.25, 0.5, h + 0.5, fill=_hx("#4a3220"))
    l.rect(x0 + w - 0.25, y0 - 0.25, 0.5, h + 0.5, fill=_hx("#4a3220"))
    l.rect(x0 + w / 2 - 0.8, y0 + h - 0.3, 1.6, 0.6, fill=_hx("#2a2018"))
    l.rect(x0 + w * 0.25, y0 - 0.2, 1, 0.4, fill=_hx("#6a8a92"))
    l.rect(x0 + w * 0.6, y0 - 0.2, 1, 0.4, fill=_hx("#6a8a92"))
    l.rect(x0 + 0.3, y0 + 0.3, 2, 1.2, fill=_hx("#5b5b60"))
    l.radial(x0 + 1.3, y0 + 0.9, 0.8,
             [(0.0, (255, 210, 122, 255)), (0.5, (240, 144, 42, 200)),
              (1.0, (200, 60, 20, 0))])
    l.rect(x0 + w - 4, y0 + 0.4, 3.4, 1, fill=_hx("#5a3d22"))
    l.rect(x0 + w - 4, y0 + 0.4, 3.4, 0.3, fill=_hx("#7d5730"))
    for k in range(3):
        barril(l, x0 + w - 1 - k * 0.9, y0 + 2 + (k % 2) * 0.5, rng)
    zonas = []
    ty = y0 + 3
    while ty < y0 + h - 2:
        tx = x0 + 2
        while tx < x0 + w - 2:
            zonas.append((tx, ty))
            tx += 3.5
        ty += 3
    for (tx, ty) in zonas:
        if rng() < 0.75:
            mesa_redonda(l, tx + (rng() - 0.5) * 0.6, ty + (rng() - 0.5) * 0.6, rng)


def mesa_redonda(l, cx, cy, rng):
    for k in range(4):
        a = k / 4 * TAU + 0.3
        l.rect(cx + math.cos(a) * 0.9 - 0.22, cy + math.sin(a) * 0.9 - 0.22,
               0.44, 0.44, fill=_hx("#6b4a28"))
    sombra(l, cx, cy + 0.1, 0.8, 0.4)
    l.elipse(cx, cy, 0.75, 0.75, fill=_hx("#886033"), outline=_hx("#4a3220"), w=0.06)
    if rng() < 0.5:
        l.elipse(cx + 0.2, cy - 0.1, 0.14, 0.14, fill=_hx("#c9b26a"))


def dibujar_cripta(l, cols, rows, seed):
    rng = Mulberry32(seed + 202)
    l.rect(0, 0, cols, rows, fill=_hx("#3c3f45"))
    for y in range(rows):
        for x in range(cols):
            r = cel_rng(seed + 5, x, y)()
            v = int(58 + r * 26)
            l.rect(x + 0.06, y + 0.06, 0.88, 0.88, fill=(v, v, v + 6))
            if r < 0.12:
                l.linea([(x + 0.2, y + 0.2), (x + 0.6, y + 0.5), (x + 0.8, y + 0.3)],
                        (20, 20, 24, 153), 0.03)
    l.rect(0, 0, cols, 0.8, fill=_hx("#4a4d53"))
    l.rect(0, rows - 0.8, cols, 0.8, fill=_hx("#4a4d53"))
    l.rect(0, 0, 0.8, rows, fill=_hx("#4a4d53"))
    l.rect(cols - 0.8, 0, 0.8, rows, fill=_hx("#4a4d53"))
    i = 0.0
    while i < cols:
        l.rect(i, 0, 1.5, 0.8, outline=(20, 20, 24, 153), ow=0.05)
        l.rect(i, rows - 0.8, 1.5, 0.8, outline=(20, 20, 24, 153), ow=0.05)
        i += 1.5
    i = 0.0
    while i < rows:
        l.rect(0, i, 0.8, 1.5, outline=(20, 20, 24, 153), ow=0.05)
        l.rect(cols - 0.8, i, 0.8, 1.5, outline=(20, 20, 24, 153), ow=0.05)
        i += 1.5
    for cx in (cols * 0.28, cols * 0.72):
        for cy in (rows * 0.3, rows * 0.7):
            columna(l, cx, cy)
    for _ in range(2 + int(rng() * 2)):
        sx = 2 + rng() * (cols - 5)
        sy = 2 + rng() * (rows - 4)
        sarcofago(l, sx, sy, rng)
    for _ in range(int(cols * 0.8)):
        x = rng() * cols
        y = rng() * rows
        if rng() < 0.5:
            roca(l, x, y, 0.25 + rng() * 0.25, rng)
    for k in range(4):
        t = (k + 0.5) / 4
        antorcha(l, t * cols, 0.6)
        antorcha(l, t * cols, rows - 0.6)


def sarcofago(l, x, y, rng):
    w, h = 1.4, 2.6
    rot90 = not (rng() < 0.5)
    if rot90:
        w, h = h, w
    sombra(l, x + 0.2, y + 0.2, 1.4 * 0.7, 2.6 * 0.5)
    l.rect(x - w / 2, y - h / 2, w, h, fill=_hx("#61656d"),
           outline=_hx("#2a2c30"), ow=0.08)
    if rng() < 0.4:
        if rot90:
            l.rect(x - w / 2 + 0.3, y - h / 2 + 0.2, w * 0.4, h - 0.4,
                   fill=_hx("#2a2c30"))
        else:
            l.rect(x - w / 2 + 0.2, y - h / 2 + 0.3, w - 0.4, h * 0.4,
                   fill=_hx("#2a2c30"))
    if rot90:
        l.elipse(x - w / 2 + 0.6, y, 0.28, 0.28,
                 outline=(30, 30, 34, 153), w=0.04)
        l.linea([(x - w / 2 + 0.9, y), (x + w / 2 - 0.4, y)], (30, 30, 34, 153), 0.04)
    else:
        l.elipse(x, y - h / 2 + 0.6, 0.28, 0.28, outline=(30, 30, 34, 153), w=0.04)
        l.linea([(x, y - h / 2 + 0.9), (x, y + h / 2 - 0.4)], (30, 30, 34, 153), 0.04)


def antorcha(l, cx, cy):
    l.rect(cx - 0.06, cy - 0.1, 0.12, 0.5, fill=_hx("#3a2718"))
    l.radial(cx, cy - 0.2, 0.9,
             [(0.0, (255, 230, 160, 255)), (0.4, (240, 144, 42, 190)),
              (1.0, (200, 60, 20, 0))])
    l.elipse(cx, cy - 0.25, 0.16, 0.16, fill=_hx("#ffd66a"))


def dibujar_mazmorra(l, cols, rows, seed):
    rng = Mulberry32(seed + 303)
    l.rect(0, 0, cols, rows, fill=_hx("#15171d"))
    for y in range(rows):
        for x in range(cols):
            r = cel_rng(seed + 7, x, y)()
            l.rect(x, y, 1, 1, fill=(255, 255, 255, int(r * 0.03 * 255)))
    piso = set()
    salas = []
    meta = 4 + int(rng() * 3)
    k = 0
    while k < 60 and len(salas) < meta:
        k += 1
        w = 3 + int(rng() * 4)
        h = 3 + int(rng() * 3)
        x = 1 + int(rng() * (cols - w - 2))
        y = 1 + int(rng() * (rows - h - 2))
        if any(x < s["x"] + s["w"] + 2 and x + w + 2 > s["x"]
               and y < s["y"] + s["h"] + 2 and y + h + 2 > s["y"] for s in salas):
            continue
        s = {"x": x, "y": y, "w": w, "h": h, "cx": x + (w >> 1), "cy": y + (h >> 1)}
        salas.append(s)
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                piso.add((xx, yy))

    def tallar(a, b):
        x, y = a["cx"], a["cy"]

        def ancho_x(px):
            piso.add((px, y))
            if y + 1 < rows - 1:
                piso.add((px, y + 1))

        def ancho_y(py):
            piso.add((x, py))
            if x + 1 < cols - 1:
                piso.add((x + 1, py))
        if rng() < 0.5:
            while x != b["cx"]:
                x += 1 if b["cx"] > x else -1
                ancho_x(x)
            while y != b["cy"]:
                y += 1 if b["cy"] > y else -1
                ancho_y(y)
        else:
            while y != b["cy"]:
                y += 1 if b["cy"] > y else -1
                ancho_y(y)
            while x != b["cx"]:
                x += 1 if b["cx"] > x else -1
                ancho_x(x)
    for i in range(1, len(salas)):
        tallar(salas[i - 1], salas[i])

    for (x, y) in sorted(piso):
        r = cel_rng(seed + 5, x, y)()
        v = int(52 + r * 24)
        l.rect(x + 0.04, y + 0.04, 0.92, 0.92, fill=(v, v, v + 6))
        if r < 0.1:
            l.linea([(x + 0.2, y + 0.25), (x + 0.55, y + 0.5), (x + 0.8, y + 0.3)],
                    (16, 16, 20, 153), 0.03)
    for y in range(rows):
        for x in range(cols):
            if (x, y) in piso:
                continue
            borde = any((x + dx, y + dy) in piso
                        for dy in (-1, 0, 1) for dx in (-1, 0, 1))
            if not borde:
                continue
            r = cel_rng(seed + 15, x, y)()
            v = int(46 + r * 14)
            l.rect(x, y, 1, 1, fill=(v, v, v + 8))
            l.rect(x + 0.05, y + 0.05, 0.9, 0.9, outline=(12, 12, 16, 179), ow=0.06)
    if salas:
        s0 = salas[0]
        ex, ey = s0["x"] + 0.4, s0["y"] + 0.4
        for k in range(4):
            v = 96 - k * 16
            l.rect(ex, ey + k * 0.35, 1.6, 0.35, fill=(v, v, v + 6))
        l.rect(ex, ey, 1.6, 1.4, outline=(220, 220, 230, 128), ow=0.05)
    for i in range(1, len(salas)):
        s = salas[i]
        r2 = Mulberry32(seed + 400 + i)
        t = r2()
        if t < 0.3:
            sarcofago(l, s["cx"] + 0.5, s["cy"] + 0.5, r2)
        elif t < 0.55:
            for _ in range(2 + int(r2() * 2)):
                barril(l, s["x"] + 0.8 + r2() * (s["w"] - 1.6),
                       s["y"] + 0.8 + r2() * (s["h"] - 1.6), r2)
        elif t < 0.8:
            cx, cy = s["cx"] + 0.5, s["cy"] + 0.5
            sombra(l, cx, cy + 0.25, 0.5, 0.2)
            l.rect(cx - 0.45, cy - 0.3, 0.9, 0.6, fill=_hx("#7a5730"))
            l.rect(cx - 0.45, cy - 0.3, 0.9, 0.22, fill=_hx("#8f6a3a"))
            l.rect(cx - 0.45, cy - 0.3, 0.9, 0.6, outline=_hx("#3a2718"), ow=0.06)
            l.rect(cx - 0.07, cy - 0.12, 0.14, 0.2, fill=_hx("#d8b04a"))
        else:
            for _ in range(4):
                roca(l, s["x"] + 0.6 + r2() * (s["w"] - 1.2),
                     s["y"] + 0.6 + r2() * (s["h"] - 1.2), 0.15 + r2() * 0.18, r2)
        if r2() < 0.7:
            antorcha(l, s["x"] + 0.4, s["y"] + 0.4)


# ---- gruta / caverna (interior) ----
def estalagmita(l, cx, cy, r, hacia_abajo):
    """Aguja de piedra; si hacia_abajo cuelga del techo (estalactita)."""
    sombra(l, cx, cy + r * 0.4, r * 0.7, r * 0.28)
    d = 1 if not hacia_abajo else -1
    base = cy + d * r * 0.6
    punta = cy - d * r * 0.9
    l.poli([(cx - r * 0.42, base), (cx + r * 0.42, base), (cx, punta)],
           fill=_hx("#5b5560"), outline=(24, 22, 26, 150), w=0.05)
    l.linea([(cx - r * 0.1, base), (cx - r * 0.02, punta)], (230, 225, 235, 60), 0.04)


def dibujar_gruta(l, cols, rows, seed):
    rng = Mulberry32(seed + 404)
    l.rect(0, 0, cols, rows, fill=_hx("#181519"))
    midx, midy = cols / 2, rows / 2
    # cavidad transitable: polígono orgánico
    n = 26
    pts = []
    for k in range(n + 1):
        a = k / n * TAU
        rr = (0.5 + fbm(math.cos(a) + 4, math.sin(a) + 4, seed + 42, 3) * 0.55)
        pts.append((midx + math.cos(a) * rr * cols * 0.5,
                    midy + math.sin(a) * rr * rows * 0.5))
    # suelo de roca con variacion por celda (dentro del poligono via mascara)
    S = l.S
    mask = Image.new("L", (l.im.width, l.im.height), 0)
    ImageDraw.Draw(mask).polygon([(x * S, y * S) for x, y in pts], fill=255)
    suelo = Image.new("RGB", (l.im.width, l.im.height), (0, 0, 0))
    ds = ImageDraw.Draw(suelo)
    for y in range(rows):
        for x in range(cols):
            r = cel_rng(seed + 5, x, y)()
            v = int(46 + r * 26)
            ds.rectangle([(x * S, y * S), ((x + 1) * S, (y + 1) * S)],
                         fill=(v, v - 2, v + 4))
    l.im.paste(suelo, (0, 0), mask)
    l.poli(pts, outline=(12, 10, 14, 210), w=0.22)
    l.poli(pts, outline=(70, 66, 74, 120), w=0.06)
    # poza subterranea
    if rng() < 0.85:
        px = midx + (rng() - 0.5) * cols * 0.3
        py = midy + (rng() - 0.5) * rows * 0.3
        R = min(cols, rows) * (0.12 + rng() * 0.08)
        poza = []
        for k in range(21):
            a = k / 20 * TAU
            rr = R * (0.85 + fbm(math.cos(a) + 6, math.sin(a) + 6, seed + 43, 2) * 0.35)
            poza.append((px + math.cos(a) * rr, py + math.sin(a) * rr * 0.85))
        l.poli_radial(poza, px, py, R,
                      [(0.0, _hx("#2b5560")), (0.7, _hx("#1c3d47")), (1.0, _hx("#122a31"))])
        l.poli(poza, outline=(120, 170, 180, 90), w=0.06)
        l.elipse(px - R * 0.3, py - R * 0.2, R * 0.4, R * 0.22, fill=(180, 220, 225, 40))
    # estalagmitas en el suelo y estalactitas colgando
    for _ in range(6 + int(rng() * 5)):
        sx = 1.5 + rng() * (cols - 3)
        sy = 1.5 + rng() * (rows - 3)
        estalagmita(l, sx, sy, 0.5 + rng() * 0.5, False)
    for _ in range(5 + int(rng() * 4)):
        sx = 1.5 + rng() * (cols - 3)
        sy = 1.5 + rng() * (rows - 3)
        estalagmita(l, sx, sy, 0.4 + rng() * 0.4, True)
    # rocas sueltas y cristales luminiscentes
    for _ in range(int(cols * 0.7)):
        roca(l, rng() * cols, rng() * rows, 0.18 + rng() * 0.22, rng)
    for _ in range(4 + int(rng() * 4)):
        cx = 1 + rng() * (cols - 2)
        cy = 1 + rng() * (rows - 2)
        l.radial(cx, cy, 0.5,
                 [(0.0, (110, 200, 220, 150)), (1.0, (110, 200, 220, 0))])
        l.elipse(cx, cy, 0.1, 0.16, fill=_hx("#8fe0ee"))
    # entrada iluminada
    ang = rng() * TAU
    ex = midx + math.cos(ang) * cols * 0.42
    ey = midy + math.sin(ang) * rows * 0.42
    l.radial(ex, ey, 1.8,
             [(0.0, (210, 220, 200, 120)), (1.0, (210, 220, 200, 0))])


# ==========================================================================
#  vineta, rejilla y numeracion
# ==========================================================================
def _vineta(img, cols, rows, S, r0f, r1f, alfa):
    arr = np.asarray(img, np.float32)
    h, w = arr.shape[0], arr.shape[1]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r0 = min(cols, rows) * r0f * S
    r1 = max(cols, rows) * r1f * S
    d = np.hypot(xx - w / 2, yy - h / 2)
    a = np.clip((d - r0) / max(r1 - r0, 1e-6), 0, 1) * alfa
    arr = arr * (1 - a[..., None])
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _fuente(px):
    px = max(6, int(round(px)))
    hit = _CACHE_FUENTES.get(px)
    if hit:
        return hit
    wf = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    fnt = None
    for nombre in ("arialbd.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            fnt = ImageFont.truetype(str(wf / nombre), px)
            break
        except OSError:
            continue
    if fnt is None:
        fnt = ImageFont.load_default()
    _CACHE_FUENTES[px] = fnt
    return fnt


def dibujar_rejilla(img, S, cols, rows, nums):
    dr = ImageDraw.Draw(img, "RGBA")
    for x in range(cols + 1):
        dr.line([(x * S, 0), (x * S, rows * S)], fill=(0, 0, 0, 71), width=1)
        dr.line([(x * S + 1, 0), (x * S + 1, rows * S)], fill=(255, 255, 255, 20), width=1)
    for y in range(rows + 1):
        dr.line([(0, y * S), (cols * S, y * S)], fill=(0, 0, 0, 71), width=1)
    if not nums:
        return
    fs = max(8, int(S * 0.28))
    fnt = _fuente(fs)

    def etiqueta(t, x, y):
        dr.text((x, y), t, font=fnt, fill=(240, 240, 245, 230), anchor="mm",
                stroke_width=max(1, fs // 6), stroke_fill=(0, 0, 0, 179))
    for x in range(cols):
        lbl = LETRAS[x] if x < 26 else LETRAS[x // 26 - 1] + LETRAS[x % 26]
        etiqueta(lbl, x * S + S / 2, fs * 0.7)
    for y in range(rows):
        etiqueta(str(y + 1), fs * 0.7, y * S + S / 2)


# ==========================================================================
#  render principal
# ==========================================================================
INTERIORES = ("taberna", "cripta", "mazmorra", "gruta")

MOMENTOS = ("dia", "atardecer", "noche")
ESTACIONES = ("primavera", "verano", "otono", "invierno")
# temas templados que en invierno reciben escarcha / nieve parcial
_TEMPLADOS = frozenset({"bosque", "taiga", "pradera", "vado", "cienaga",
                        "paso", "aldea", "puerto"})


def _mascara_noise(cols, rows, S, seed):
    """Campo de ruido (rows*S, cols*S) en 0..1, coherente con el suelo."""
    xs = np.arange(cols) * 0.7
    ys = np.arange(rows) * 0.7
    X, Y = np.meshgrid(xs, ys)
    n = _fbm_vec(X, Y, seed + 61, 3)
    n = np.clip((n - 0.25) / 0.5, 0.0, 1.0)
    return np.repeat(np.repeat(n, S, axis=0), S, axis=1)


def _colorgrade(img, cols, rows, S, seed, tema, momento, estacion):
    """Post-procesa la paleta segun momento del dia y estacion (barato:
    opera sobre el render base, sin re-dibujar props)."""
    if momento == "dia" and estacion == "verano":
        return img
    arr = np.asarray(img, np.float32)
    R = arr[..., 0]
    G = arr[..., 1]
    B = arr[..., 2]

    # --- estacion: vegetacion / nieve ---
    if estacion == "otono":
        verde = np.clip((G - np.maximum(R, B)) / 40.0, 0, 1)   # 0..1 verdor
        R = R + verde * 78
        G = G - verde * 8
        B = B - verde * 46
    elif estacion == "primavera":
        verde = np.clip((G - np.maximum(R, B)) / 50.0, 0, 1)
        G = G + verde * 16
        R = R + verde * 4
    elif estacion == "invierno" and tema in _TEMPLADOS:
        snow = np.clip(0.28 + _mascara_noise(cols, rows, S, seed) * 0.5, 0, 0.82)
        R = R + (238 - R) * snow
        G = G + (244 - G) * snow
        B = B + (250 - B) * snow

    # --- momento del dia ---
    if momento == "noche":
        # mascara de fuego (rojos brillantes: antorchas, lava, fogatas)
        warm = (np.clip((R - B - 30) / 90.0, 0, 1)
                * np.clip((R - 120) / 90.0, 0, 1))[..., None]
        base = np.stack([R * 0.40 - 4, G * 0.44 + 6, B * 0.52 + 18], axis=-1)
        glow = np.stack([R * 1.06, G * 1.0, B * 0.9], axis=-1)
        arr = base * (1 - warm) + glow * warm
    elif momento == "atardecer":
        arr = np.stack([R * 1.14 + 12, G * 1.0 + 3, B * 0.78], axis=-1) * 0.95
    else:
        arr = np.stack([R, G, B], axis=-1)

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def render_mapa(cols, rows, S, seed, tema, sub, grid, nums, puente_auto,
                momento="dia", estacion="verano"):
    """Devuelve (PNG bytes, subtipo efectivo)."""
    seed_e = semilla_efectiva(seed, tema)
    sub_e = sub_efectivo(tema, sub, seed)
    corr = corredor(cols, rows, seed_e)

    if tema in INTERIORES:
        img = Image.new("RGB", (cols * S, rows * S), (10, 13, 19))
    else:
        img = _suelo_img(cols, rows, S, seed_e, tema)
    l = Lienzo(img, S)

    if tema == "taberna":
        dibujar_taberna(l, cols, rows, seed_e)
    elif tema == "cripta":
        dibujar_cripta(l, cols, rows, seed_e)
    elif tema == "mazmorra":
        dibujar_mazmorra(l, cols, rows, seed_e)
    elif tema == "gruta":
        dibujar_gruta(l, cols, rows, seed_e)
    else:
        _sendero(l, corr, seed_e)
        if tema == "vado":
            props_vado(l, cols, rows, seed_e, corr, sub_e, puente_auto)
        elif tema == "playa":
            suelo_playa(l, cols, rows, seed_e, sub_e)
        elif tema == "aldea":
            props_aldea(l, cols, rows, seed_e, corr, sub_e)
        elif tema == "puerto":
            props_puerto(l, cols, rows, seed_e, corr, sub_e)
        else:
            props_naturales(l, cols, rows, seed_e, tema, corr, sub_e)

    if tema in ("cripta", "gruta"):
        img = _vineta(img, cols, rows, S, 0.2, 0.7, 0.45)
    elif tema == "mazmorra":
        img = _vineta(img, cols, rows, S, 0.15, 0.75, 0.55)
    else:
        img = _vineta(img, cols, rows, S, 0.35, 0.75, 0.22)

    img = _colorgrade(img, cols, rows, S, seed_e, tema, momento, estacion)

    if grid:
        dibujar_rejilla(img, S, cols, rows, nums)

    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), sub_e


# ==========================================================================
#  endpoints
# ==========================================================================
def _q1(q, k, defecto=""):
    return q.get(k, [defecto])[0]


def _qfloat(q, k, defecto):
    try:
        return float(_q1(q, k, str(defecto)))
    except (TypeError, ValueError):
        return defecto


def _qint(q, k, defecto):
    try:
        return int(float(_q1(q, k, str(defecto))))
    except (TypeError, ValueError):
        return defecto


def _q_momento(q):
    m = _q1(q, "momento", "dia")
    return m if m in MOMENTOS else "dia"


def _q_estacion(q):
    e = _q1(q, "estacion", "verano")
    return e if e in ESTACIONES else "verano"


def _sufijo_ambiente(momento, estacion):
    """Coletilla narrativa para el titulo (solo cuando aporta)."""
    mm = {"atardecer": ", al atardecer", "noche": ", al anochecer"}
    ee = {"primavera": " en primavera", "otono": " en otoño",
          "invierno": " en invierno"}
    return mm.get(momento, "") + ee.get(estacion, "")


def _slug(s):
    s = (s or "battlemap").lower()
    s = re.sub(r"[^0-9a-záéíóúñ\s-]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s or "battlemap"


def _validar(q):
    """(sello, stem, datos) o (None, None, None) si son invalidos."""
    sello = _q1(q, "sello")
    stem = _q1(q, "d")
    if not RE_SELLO.match(sello) or not RE_STEM.match(stem):
        return None, None, None
    return sello, stem, _cargar_datos(sello, stem)


def _params_mapa(q, nx, ny):
    cols = min(40, max(10, _qint(q, "cols", 20)))
    rows = min(40, max(10, _qint(q, "rows", 20)))
    seed = _qint(q, "semilla", 1)
    if seed < 0:
        seed = 1
    seed &= M32
    tema = _q1(q, "tema", "pradera")
    if tema not in TEMAS_POR_CLAVE:
        tema = "pradera"
    sub = _q1(q, "sub", "auto")
    if sub != "auto" and sub not in (TEMAS_POR_CLAVE[tema]["subs"] or []):
        sub = "auto"
    px = min(160, max(8, _qint(q, "px", 48)))
    grid = _q1(q, "rejilla", "1") != "0"
    nums = _q1(q, "nums", "1") != "0"
    rx = _qfloat(q, "rx", -1.0)
    ry = _qfloat(q, "ry", -1.0)
    if not (0 <= rx < nx and 0 <= ry < ny):
        rx = ry = None
    return cols, rows, seed, tema, sub, px, grid, nums, rx, ry


def _lugar_json(d, rx, ry):
    info = analizar(d, rx, ry)
    nx = d["nx"]
    esc = nx / 1024.0
    tema = detectar_tema(info, nx)
    out = {
        "rx": rx, "ry": ry,
        "es_mar": info["esMar"],
        "alt_pct": round(info["alt"] * 100),
        "alt_desc": _desc_alt(info["alt"]),
        "temp": round(info["temp"], 2),
        "temp_desc": _desc_temp(info["temp"], info["tair"]),
        "precip_pct": round(info["precip"] * 100),
        "hielo_pct": round(info["hielo"] * 100) if info["hielo"] > 0.02 else 0,
        "tema": tema,
        "tema_nombre": TEMAS_POR_CLAVE[tema]["nombre"],
        "interiores": tema == "aldea",
    }
    if not info["esMar"] and info["bioma"]:
        out["bioma"] = {"nombre": info["bioma"].get("nombre", "desconocido"),
                        "rgb": info["bioma"].get("rgb", [120, 120, 120])}
    if info["rio"]["it"]:
        out["rio"] = {"nombre": info["rio"]["it"].get("nombre", "?"),
                      "dist": round(info["rio"]["d"] / esc),
                      "cerca": info["rio"]["d"] < 42 * esc}
    if info["costa"]["hayMar"]:
        out["costa"] = {"frac_pct": round(info["costa"]["frac"] * 100)}
    if info["camino"]["it"]:
        out["camino"] = {"dist": round(info["camino"]["d"] / esc),
                         "cerca": info["camino"]["d"] < 30 * esc}
    if info["asent"]["it"]:
        it = info["asent"]["it"]
        out["asent"] = {"nombre": it.get("nombre", "?"),
                        "pais": _nombre_pais(d, it.get("pais")),
                        "dist": round(info["asent"]["d"] / esc),
                        "aqui": info["asent"]["d"] < 15 * esc}
    return out


def _cache_path(sello, stem, clave):
    carpeta = SALIDAS / sello / "detalles" / "batalla_cache"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / (hashlib.md5(clave.encode()).hexdigest() + ".png")


def manejar_get(handler, url):
    if not url.path.startswith("/api/batalla/"):
        return False
    q = parse_qs(url.query)
    sello, stem, d = _validar(q)
    if d is None:
        handler._json({"error": "sello/d invalidos o detalle sin datos"}, 400)
        return True
    nx, ny = d["nx"], d["ny"]

    if url.path == "/api/batalla/info":
        handler._json({
            "resolucion": [nx, ny],
            "sub_auto": SUBS["auto"],
            "temas": [{"clave": t["clave"], "nombre": t["nombre"],
                       "subs": [{"clave": s, "nombre": SUBS[s]} for s in t["subs"]]}
                      for t in TEMAS],
        })
        return True

    if url.path == "/api/batalla/lugar":
        rx = _qfloat(q, "rx", nx / 2)
        ry = _qfloat(q, "ry", ny / 2)
        rx = min(max(rx, 0.0), nx - 1e-6)
        ry = min(max(ry, 0.0), ny - 1e-6)
        handler._json(_lugar_json(d, rx, ry))
        return True

    if url.path == "/api/batalla/escena":
        cols, rows, seed, tema, sub, px, grid, nums, rx, ry = _params_mapa(q, nx, ny)
        momento, estacion = _q_momento(q), _q_estacion(q)
        sub_e = sub_efectivo(tema, sub, seed)
        out = {"tema": tema, "tema_nombre": TEMAS_POR_CLAVE[tema]["nombre"],
               "sub": sub_e, "sub_nombre": SUBS.get(sub_e, sub_e),
               "auto": sub == "auto", "momento": momento, "estacion": estacion,
               "tiene_subs": bool(TEMAS_POR_CLAVE[tema]["subs"])}
        if rx is not None:
            info = analizar(d, rx, ry)
            base = titulo_escena(d, tema, sub_e, info, nx)
        else:
            base = TEMAS_POR_CLAVE[tema]["nombre"]
        out["titulo"] = base + _sufijo_ambiente(momento, estacion)
        handler._json(out)
        return True

    if url.path == "/api/batalla/mapa":
        cols, rows, seed, tema, sub, px, grid, nums, rx, ry = _params_mapa(q, nx, ny)
        momento, estacion = _q_momento(q), _q_estacion(q)
        # el punto solo influye en el vado automatico (puente si hay camino)
        puente_auto = False
        if tema == "vado" and rx is not None:
            info = analizar(d, rx, ry)
            puente_auto = bool(info["camino"]["it"]
                               and info["camino"]["d"] < 45 * (nx / 1024.0))
        clave = "|".join([stem, str(cols), str(rows), str(seed), tema, sub,
                          str(px), "1" if grid else "0", "1" if nums else "0",
                          "P" if puente_auto else "p", momento, estacion])
        cache = _cache_path(sello, stem, clave)
        if cache.exists():
            handler._archivo(cache, "image/png", cache=True)
            return True
        png, _sub_e = render_mapa(cols, rows, px, seed, tema, sub, grid, nums,
                                  puente_auto, momento, estacion)
        try:
            cache.write_bytes(png)
        except OSError:
            pass
        handler._bytes(png, "image/png", cache=True)
        return True

    if url.path == "/api/batalla/vtt":
        # manifiesto de escena para VTT (Foundry) o datos de rejilla (Roll20).
        # La logica del manifiesto vive aqui; el front solo dispara descargas.
        cols, rows, seed, tema, sub, px, grid, nums, rx, ry = _params_mapa(q, nx, ny)
        momento, estacion = _q_momento(q), _q_estacion(q)
        formato = _q1(q, "formato", "foundry")
        sub_e = sub_efectivo(tema, sub, seed)
        if rx is not None:
            info = analizar(d, rx, ry)
            base = titulo_escena(d, tema, sub_e, info, nx)
        else:
            base = TEMAS_POR_CLAVE[tema]["nombre"]
        titulo = base + _sufijo_ambiente(momento, estacion)
        cel = 70 if formato == "roll20" else 100
        fname = f"{_slug(base)}_{cols}x{rows}_s{seed}_{cel}px.png"
        if formato == "roll20":
            handler._json({
                "formato": "roll20", "archivo_png": fname,
                "cols": cols, "rows": rows, "px": cel,
                "nota": f"{cols}×{rows} casillas · {cel} px/casilla",
            })
            return True
        # Foundry VTT: escena minima (v10+: grid anidado, type 1 = cuadrada)
        handler._json({
            "name": titulo,
            "navigation": True,
            "width": cols * cel, "height": rows * cel,
            "padding": 0,
            "grid": {"size": cel, "type": 1},
            "background": {"src": fname},
            "img": fname,
            "_archivo_png": fname,
        })
        return True

    handler._json({"error": "no existe"}, 404)
    return True


def manejar_post(handler, ruta, datos):
    return False
