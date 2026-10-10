"""Lugares destacados de un detalle, calculados por reglas (T03).

Ver ESPECIFICACION_RUTAS.md, «Lugares destacados». Hasta 6 puntos de rejilla
(los `rx, ry` de batalla_srv) elegidos por estas reglas, en orden de prioridad:

  cruce    cruce de rio con camino (puntua el caudal del rio)
  paso     paso de montana: collado entre dos cuencas (puerto de altura: mas
           bajo que las cumbres a sus lados, mas alto que los valles a los otros)
  costa    ciudad costera (puntua rango y poblacion)
  capital  capital (rango 3) o, si no hay, la ciudad mayor
  bosque   bosque denso (fraccion de bosque alrededor y humedad)
  desierto desierto profundo (fraccion de desierto alrededor y sequedad)

Primera pasada: un lugar por regla (la mejor celda libre de cada una). Si
quedan huecos, segunda pasada con los siguientes candidatos de cada regla, en
el mismo orden. Nunca se repite celda y los lugares guardan una separacion
minima entre si.

No se recorre cada celda: los rasters se muestrean en una malla gruesa
(vectorizado con numpy) y las polilineas se rasterizan sobre esa misma malla.
`batalla_srv.analizar` solo se llama sobre los lugares elegidos, para obtener
nombre (via detectar_tema + titulo_escena, igual que el analisis de lugar) y
bioma. Los datos se cargan con `batalla_srv._cargar_datos`.

Resultado cacheado en salidas/<sello>/detalles/<stem>_lugares.json como
{"version": VERSION, "lugares": [...]}; se recalcula si falta, no se puede
leer o su version es menor que VERSION.
"""
import json
import math
import os

import numpy as np

import batalla_srv

VERSION = 1
MAX_LUGARES = 6
MALLA = 128          # puntos de la malla gruesa en el eje mayor (paso >= 1)

BIOMA_MAR = 255
BOSQUES = {2: 1.0, 7: 1.0, 10: 1.0, 8: 0.6}     # taiga, templado, humedo, seco
DESIERTOS = {4: 1.0, 5: 0.8}                     # desierto, desierto frio

ORDEN_REGLAS = ("cruce", "paso", "costa", "capital", "bosque", "desierto")


# ==========================================================================
#  API publica
# ==========================================================================
def lugares(sello: str, d: str) -> list[dict]:
    """Lista de hasta 6 {x, y, nombre, bioma, regla} del detalle `d` de la
    corrida `sello`. [] si sello/d no son validos o el detalle no tiene datos."""
    if not (isinstance(sello, str) and isinstance(d, str)
            and batalla_srv.RE_SELLO.match(sello)
            and batalla_srv.RE_STEM.match(d)):
        return []
    ruta = _ruta_cache(sello, d)
    cache = _leer_cache(ruta)
    if cache is not None:
        return cache

    datos = batalla_srv._cargar_datos(sello, d)
    if datos is None:
        return []
    res = calcular(datos)
    _escribir_cache(ruta, res)
    return res


def calcular(datos):
    """Lugares de un dict de datos de batalla_srv._cargar_datos (sin cache)."""
    m = _Malla(datos)
    sep = max(datos["nx"], datos["ny"]) / 16.0
    candidatos = {
        "cruce": _regla_cruce(m),
        "paso": _regla_paso(m),
        "costa": _regla_costa(m, datos),
        "capital": _regla_capital(m),
        "bosque": _regla_densidad(m, BOSQUES, humedo=True),
        "desierto": _regla_densidad(m, DESIERTOS, humedo=False),
    }
    elegidos = []      # (x, y, regla)
    usadas = set()

    def libre(x, y):
        if (x, y) in usadas:
            return False
        return all(math.hypot(x - ex, y - ey) >= sep for ex, ey, _ in elegidos)

    def tomar(regla):
        lst = candidatos[regla]
        while lst:
            _, x, y = lst.pop(0)
            if libre(x, y):
                elegidos.append((x, y, regla))
                usadas.add((x, y))
                return True
        return False

    # pasada 1: una por regla en orden de prioridad; despues, rondas de
    # relleno (una mas por regla y ronda) hasta 6 o agotar candidatos
    while len(elegidos) < MAX_LUGARES:
        alguno = False
        for regla in ORDEN_REGLAS:
            if len(elegidos) >= MAX_LUGARES:
                break
            alguno = tomar(regla) or alguno
        if not alguno:
            break

    return [_ficha(datos, x, y, regla) for x, y, regla in elegidos]


# ==========================================================================
#  cache en disco
# ==========================================================================
def _ruta_cache(sello, stem):
    # batalla_srv.SALIDAS se lee en cada llamada (las pruebas lo parchean)
    return batalla_srv.SALIDAS / sello / "detalles" / f"{stem}_lugares.json"


def _leer_cache(ruta):
    try:
        obj = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("lugares"), list):
        return None
    if not isinstance(obj.get("version"), int) or obj["version"] < VERSION:
        return None
    return obj["lugares"]


def _escribir_cache(ruta, res):
    if not ruta.parent.is_dir():
        return
    tmp = ruta.with_name(ruta.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({"version": VERSION, "lugares": res},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ruta)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


# ==========================================================================
#  ficha final: nombre y bioma desde el analisis de batalla_srv
# ==========================================================================
def _ficha(datos, x, y, regla):
    info = batalla_srv.analizar(datos, x, y)
    nx = datos["nx"]
    tema = batalla_srv.detectar_tema(info, nx)
    nombre = batalla_srv.titulo_escena(datos, tema, None, info, nx)
    if info["esMar"]:
        bioma = "mar"
    elif info["bioma"]:
        bioma = info["bioma"].get("nombre", "desconocido")
    else:
        bioma = "desconocido"
    return {"x": int(x), "y": int(y), "nombre": nombre, "bioma": bioma,
            "regla": regla}


# ==========================================================================
#  malla gruesa
# ==========================================================================
class _Malla:
    """Muestreo de los rasters del detalle en una malla de paso `paso` celdas.
    Cada nodo (i, j) representa la celda de rejilla (xs[i], ys[j])."""

    def __init__(self, datos):
        nx, ny = datos["nx"], datos["ny"]
        self.nx, self.ny = nx, ny
        self.capas = datos["capas"]
        self.paso = max(1, max(nx, ny) // MALLA)
        p = self.paso
        self.xs = np.minimum(np.arange(p // 2, nx, p), nx - 1)
        self.ys = np.minimum(np.arange(p // 2, ny, p), ny - 1)
        d1, d2 = datos["d1"], datos["d2"]

        def muestra(r, canal):
            h, w = r.shape[0], r.shape[1]
            ix = np.clip((self.xs * w / nx).astype(int), 0, w - 1)
            iy = np.clip((self.ys * h / ny).astype(int), 0, h - 1)
            return r[np.ix_(iy, ix)][..., canal]

        self.alt = muestra(d1, 2).astype(np.float64) / 255.0
        self.precip = muestra(d1, 1).astype(np.float64) / 255.0
        self.bioma = muestra(d2, 0).astype(np.int32)
        self.tierra = self.bioma != BIOMA_MAR

    def nodo(self, x, y):
        """(j, i) del nodo de malla que contiene la celda (x, y), o None."""
        i = int(x) // self.paso
        j = int(y) // self.paso
        if 0 <= i < len(self.xs) and 0 <= j < len(self.ys):
            return j, i
        return None

    def rasterizar(self, polilineas, valor):
        """Malla con el maximo de `valor(it)` de las polilineas que la tocan
        (0 donde no pasa ninguna). Los segmentos se densifican a medio paso."""
        out = np.zeros(self.alt.shape, np.float64)
        h, w = out.shape
        for it in polilineas or []:
            a = np.asarray(it.get("puntos") or [], np.float64)
            if a.ndim != 2 or len(a) == 0 or a.shape[1] < 2:
                continue
            if len(a) > 1:
                seg = np.hypot(np.diff(a[:, 0]), np.diff(a[:, 1]))
                n = np.maximum(1, np.ceil(seg / (self.paso / 2.0))).astype(int)
                pts = [a[:1, :2]]
                for k in range(len(a) - 1):
                    t = (np.arange(1, n[k] + 1) / n[k])[:, None]
                    pts.append(a[k, :2] + t * (a[k + 1, :2] - a[k, :2]))
                a = np.concatenate(pts)
            i = (a[:, 0] // self.paso).astype(int)
            j = (a[:, 1] // self.paso).astype(int)
            ok = (i >= 0) & (i < w) & (j >= 0) & (j < h)
            v = float(valor(it))
            np.maximum.at(out, (j[ok], i[ok]), v)
        return out

    def celda(self, j, i):
        return int(self.xs[i]), int(self.ys[j])


def _desplazar(a, dj, di, relleno=np.nan):
    """a desplazada (dj, di) sin envolver: lo que entra por el borde es
    `relleno`. El detalle es un recorte, no se envuelve ni en X ni en Y."""
    out = np.full(a.shape, relleno, dtype=np.float64)
    h, w = a.shape
    if abs(dj) >= h or abs(di) >= w:
        return out
    src = a[max(0, -dj):h - max(0, dj), max(0, -di):w - max(0, di)]
    out[max(0, dj):h - max(0, -dj), max(0, di):w - max(0, -di)] = src
    return out


def _media_ventana(a, r):
    """Media de `a` en la ventana (2r+1)^2 de cada nodo, ignorando lo que cae
    fuera de la malla."""
    s = np.zeros(a.shape, np.float64)
    n = np.zeros(a.shape, np.float64)
    for dj in range(-r, r + 1):
        for di in range(-r, r + 1):
            b = _desplazar(a.astype(np.float64), dj, di)
            v = ~np.isnan(b)
            s += np.where(v, b, 0.0)
            n += v
    return s / np.maximum(n, 1)


def _mejores(m, score, limite=12):
    """Los `limite` nodos de mayor puntuacion (>0, finitos) como
    [(score, x, y)] de rejilla, de mayor a menor."""
    sc = np.where(np.isfinite(score), score, 0.0)
    plano = sc.ravel()
    idx = np.argsort(plano)[::-1][:limite]
    out = []
    for k in idx:
        if plano[k] <= 0:
            break
        j, i = divmod(int(k), sc.shape[1])
        x, y = m.celda(j, i)
        out.append((float(plano[k]), x, y))
    return out


# ==========================================================================
#  reglas: cada una devuelve [(score, x, y)] ordenada de mayor a menor
# ==========================================================================
def _regla_cruce(m):
    caminos = m.rasterizar(_capa(m, "caminos"), lambda it: 1.0)
    if not caminos.any():
        return []
    rios = m.rasterizar(_capa(m, "rios"),
                        lambda it: 0.1 + float(it.get("caudal") or 0.0))
    score = np.where((caminos > 0) & m.tierra, rios, 0.0)
    return _mejores(m, score)


def _regla_paso(m):
    """Collado: a lo largo de un eje el nodo es mas bajo que ambos vecinos
    (cumbres) y en el perpendicular mas alto que ambos (las dos cuencas). Se
    puntua la altitud y lo marcado del collado; un camino que lo cruza suma."""
    alt = np.where(m.tierra, m.alt, np.nan)      # el mar invalida el collado
    k = max(2, round(max(m.nx, m.ny) / 64 / m.paso))
    mejor = np.zeros(alt.shape)
    ejes = (((0, k), (k, 0)), ((k, k), (k, -k)))
    for (aj, ai), (bj, bi) in ejes:
        for (cj, ci), (vj, vi) in (((aj, ai), (bj, bi)), ((bj, bi), (aj, ai))):
            c1, c2 = _desplazar(alt, cj, ci), _desplazar(alt, -cj, -ci)
            v1, v2 = _desplazar(alt, vj, vi), _desplazar(alt, -vj, -vi)
            # np.minimum propaga NaN: borde o mar en cualquier vecino descarta
            subida = np.minimum(c1 - alt, c2 - alt)     # cumbres a ambos lados
            bajada = np.minimum(alt - v1, alt - v2)     # valles a ambos lados
            marca = np.minimum(subida, bajada)
            marca = np.where(np.isnan(marca), 0.0, marca)
            mejor = np.maximum(mejor, np.where(marca > 0.04, marca, 0.0))
    caminos = m.rasterizar(_capa(m, "caminos"), lambda it: 1.0)
    score = np.where((mejor > 0) & (np.nan_to_num(alt) >= 0.5),
                     alt + 2.0 * mejor + 0.3 * (caminos > 0), 0.0)
    return _mejores(m, score)


def _regla_costa(m, datos):
    out = []
    for a in _asentamientos(m):
        x, y = _celda_asent(m, a)
        costa = a.get("costa")
        if costa is None:
            costa = batalla_srv._ventana_mar(datos, x, y, 12)["hayMar"]
        if costa:
            out.append((_peso_asent(a), x, y))
    out.sort(key=lambda t: -t[0])
    return out


def _regla_capital(m):
    asents = _asentamientos(m)
    capitales = [a for a in asents if int(a.get("rango") or 0) >= 3]
    lst = capitales or asents
    out = [(_peso_asent(a),) + _celda_asent(m, a) for a in lst]
    out.sort(key=lambda t: -t[0])
    return out


def _regla_densidad(m, pesos, humedo):
    tipo = np.zeros(m.bioma.shape, np.float64)
    for b, w in pesos.items():
        tipo[m.bioma == b] = w
    if not tipo.any():
        return []
    dens = _media_ventana(tipo, 2)
    clima = (0.5 + m.precip) if humedo else (1.5 - m.precip)
    score = np.where((tipo > 0) & (dens >= 0.6), dens * clima, 0.0)
    return _mejores(m, score)


# ==========================================================================
#  auxiliares de capas
# ==========================================================================
def _capa(m, nombre):
    return m.capas.get(nombre) or []


def _asentamientos(m):
    return [a for a in _capa(m, "asentamientos")
            if isinstance(a, dict) and "x" in a and "y" in a
            and 0 <= a["x"] < m.nx and 0 <= a["y"] < m.ny]


def _celda_asent(m, a):
    return (min(max(int(a["x"]), 0), m.nx - 1),
            min(max(int(a["y"]), 0), m.ny - 1))


def _peso_asent(a):
    return int(a.get("rango") or 0) + math.log10(float(a.get("poblacion") or 0) + 1) / 10.0
