"""Constantes y rutas del servidor: copiadas tal cual del viejo web.py.

BASE apunta a la raiz del proyecto (el directorio padre de servidor/), de modo
que SALIDAS, FRONTEND, tecto.py y las paginas HTML sueltas siguen resolviendose
a los mismos sitios que antes.
"""
import re
from pathlib import Path

# raiz del proyecto: servidor/ vive dentro de ella, asi que subimos un nivel
BASE = Path(__file__).resolve().parent.parent
SALIDAS = BASE / "salidas"
# front comercial nuevo (ADR-004): paginas en frontend/ y estaticos en
# frontend/assets/ servidos bajo /app/. El panel cientifico (web.html) se muda
# a /lab; "/" pasa a ser la landing.
FRONTEND = BASE / "frontend"
ASSETS = FRONTEND / "assets"

# tipos de contenido de los estaticos servidos por /app/ (allowlist)
CTYPE_APP = {
    "css": "text/css; charset=utf-8",
    "js": "application/javascript; charset=utf-8",
    "svg": "image/svg+xml",
    "png": "image/png",
    "webp": "image/webp",
    "woff2": "font/woff2",
}
# ruta relativa segura para /app/<rel>: solo minusculas/digitos/_/-/./ y sin ".."
RE_APP_REL = re.compile(r"^[a-z0-9_/.-]+$")

# nombre de carpeta de una corrida: sello de tiempo, con sufijo -N si dos
# corridas arrancan en el mismo segundo
RE_SELLO = r"[0-9]{8}-[0-9]{6}(?:-[0-9]+)?"
RE_ARCHIVO = r"mapa(?:_placas|_manto|_clima|_final)?\.(?:gif|png)"

# parametro: (minimo, maximo, tipo, valor por defecto) — todo lo que llega
# del navegador se acota a estos rangos antes de tocar la linea de comandos
PARAMS = {
    "tiempo":      (50, 6000, int, 800),
    "cada":        (1, 50, int, 8),
    "ms":          (20, 300, int, 60),
    "semilla":     (0, 2**31 - 1, int, 7),
    "resolucion":  (64, 512, int, 256),
    "detalle":     (0.0, 1.5, float, 0.6),
    # diales del algoritmo (flags largos de tecto.py con el mismo nombre)
    "velocidad":   (2.0, 40.0, float, 18.0),
    "mar":         (0.35, 0.70, float, 0.52),
    "continentes": (0.10, 1.20, float, 0.55),
    "plumas":      (10, 300, int, 70),
    "erosion":     (0.0, 0.03, float, 0.008),
    "empuje":      (0.0, 0.6, float, 0.15),
    "momento":     (0.005, 0.2, float, 0.02),
    "rigidez":     (0.0, 1.0, float, 0.85),
    "deriva":      (1.0, 10.0, float, 8.0),
    "anos_paso":   (0.1, 10.0, float, 1.0),
}
ALGORITMO = ("velocidad", "mar", "continentes", "plumas",
             "erosion", "empuje", "momento", "rigidez", "deriva", "anos_paso")

# diales del detallado de UN cuadro (tecto.py --detallar): mismos rangos que
# el CLI; el factor ademas se acota para que resolucion*factor <= 4096 px. Los
# diales de clima (temperatura/precipitaciones) viven aqui: se eligen al detallar un
# cuadro y sobreescriben los del mundo, sin tocar la generacion
DETALLE = {
    "factor":      (2, 16, int, 8),
    "semilla":     (0, 2**31 - 1, int, 0),
    "casquetes":   (0.0, 0.45, float, 0.18),
    "relieve":     (0.2, 3.0, float, 1.2),
    "sinuosidad":  (0.0, 3.0, float, 1.0),
    "temperatura": (-1.0, 1.0, float, 0.0),
    "precipitaciones": (0.2, 2.0, float, 1.0),
    # diales de civilizacion (0 = automatico): ver civ.py
    "semilla_civ":   (0, 2**31 - 1, int, 0),
    "asentamientos": (0, 200, int, 0),
    "paises":        (0, 48, int, 0),
    # tamano de los paises: 0 auto, 1 grandes (imperios), 2 chicos (reinos)
    "tam_paises":    (0, 2, int, 0),
}
