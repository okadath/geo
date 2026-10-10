"""Mundos: identidad, visibilidad y mundo del dia (ESPECIFICACION_RUTAS.md).

Un *mundo* es una corrida de `salidas/<sello>/` vista desde el producto: su
identificador publico es el sello; el detalle `d` lo resuelve el servidor (el
mas reciente con `_capas.json`, preferentemente con `_civ.png`). El meta de la
corrida es `params.json`; aqui se le anaden, sin romper lo que ya lee
corridas.py, los campos:

  nombre   str         nombre del mundo (se persiste la primera vez)
  publico  bool        listado en Explorar (ausente -> compat publicos.json)
  dueno    email|None  quien puede cambiar la visibilidad

Funciones publicas: cargar_meta, guardar_meta, resolver_detalle, nombre_mundo,
es_publico, lugares, mundo, lista_publica, buscar, mundo_del_dia,
cambiar_visibilidad, mundos_propios.
"""
import hashlib
import json
import os
import random
import re
import threading
import unicodedata
from datetime import datetime, timezone

from .config import RE_SELLO, SALIDAS
from .corridas import _detalles
from .rutas_lab import _sellos_publicos

try:   # T03: lugares destacados por reglas (opcional hasta que exista)
    from .lugares import lugares as _lugares
except ImportError:
    _lugares = None

RE_STEM = re.compile(r"^d[0-9]{6}_f[0-9]+_[0-9a-f]{6}$")
N_MAX = 100

# serializa las escrituras de params.json (nombre, visibilidad)
_lock_meta = threading.Lock()


# ------------------------------- meta ---------------------------------------

def _valido(sello):
    return isinstance(sello, str) and re.fullmatch(RE_SELLO, sello) is not None


def cargar_meta(sello):
    """params.json de la corrida como dict, o None si no existe / es ilegible."""
    if not _valido(sello):
        return None
    try:
        meta = json.loads((SALIDAS / sello / "params.json").read_bytes())
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def guardar_meta(sello, cambios):
    """Mezcla `cambios` en params.json (relee bajo lock para no pisar otros
    campos) y lo reescribe de forma atomica. ASCII puro: corridas.py lo lee
    con la codificacion por defecto del sistema."""
    ruta = SALIDAS / sello / "params.json"
    with _lock_meta:
        meta = cargar_meta(sello) or {}
        meta.update(cambios)
        tmp = ruta.with_name("params.json.tmp")
        tmp.write_text(json.dumps(meta, indent=2, ensure_ascii=True),
                       encoding="ascii")
        os.replace(tmp, ruta)
    return meta


# ------------------------------- identidad ----------------------------------

def resolver_detalle(sello, d=None):
    """Stem del detalle usable (con `_capas.json`) del mundo: `d` si es valido,
    si no el mas reciente con `_civ.png`, si no el mas reciente con capas.
    None si no hay ninguno."""
    if not _valido(sello):
        return None
    usables = [m for m in _detalles(sello) if "capas" in m]   # mas reciente 1o
    stems = [m["png"].rsplit("/", 1)[-1][:-4] for m in usables]
    if d and RE_STEM.match(d) and d in stems:
        return d
    for m, stem in zip(usables, stems):
        if "civ" in m:
            return stem
    return stems[0] if stems else None


def _semilla(meta):
    try:
        return int((meta or {}).get("params", {}).get("semilla"))
    except (TypeError, ValueError):
        return None


_SIL_A = ["", "b", "d", "g", "k", "l", "m", "n", "r", "s", "t", "v", "z",
          "br", "dr", "th", "kh", "val"]
_SIL_B = ["a", "e", "i", "o", "u", "ae", "ei", "ia", "or", "an"]
_SIL_C = ["", "", "n", "r", "s", "l", "th", "ra", "ndor", "mos"]


def _nombre_desde_semilla(semilla):
    """Nombre determinista: el generador de toponimos de civ si se puede
    importar; si no, silabas propias con un RNG sembrado."""
    try:
        import numpy as np
        import civ
        return civ._nombre(np.random.default_rng(semilla))
    except Exception:   # civ ausente o con otra firma: alternativa propia
        rng = random.Random(semilla)
        s = "".join(rng.choice(_SIL_A) + rng.choice(_SIL_B)
                    for _ in range(rng.randint(2, 3))) + rng.choice(_SIL_C)
        return s[:1].upper() + s[1:]


def nombre_mundo(sello, meta=None):
    """Nombre del mundo: `meta.nombre` si existe; si no, derivado de la semilla
    (o del sello si no hay semilla) y persistido en el meta."""
    meta = meta if meta is not None else (cargar_meta(sello) or {})
    nombre = meta.get("nombre")
    if isinstance(nombre, str) and nombre.strip():
        return nombre
    semilla = _semilla(meta)
    if semilla is None:
        semilla = int(hashlib.sha256(sello.encode()).hexdigest()[:8], 16)
    nombre = _nombre_desde_semilla(semilla)
    if (SALIDAS / sello / "params.json").exists():
        guardar_meta(sello, {"nombre": nombre})
    meta["nombre"] = nombre
    return nombre


def es_publico(sello, meta=None):
    """`meta.publico` si esta definido; si no, compat con publicos.json
    (listado -> publico; archivo ausente -> todo publico)."""
    meta = meta if meta is not None else (cargar_meta(sello) or {})
    if isinstance(meta.get("publico"), bool):
        return meta["publico"]
    pub = _sellos_publicos()
    return pub is None or sello in pub


def lugares(sello, d):
    """Lugares destacados (T03). Lista vacia si el modulo aun no existe o
    falla."""
    if _lugares is None:
        return []
    try:
        res = _lugares(sello, d)
    except Exception:
        return []
    return res if isinstance(res, list) else []


def _imagen(sello, d):
    """URL del render de fantasia 1x (calidad=1) ya existente."""
    return f"/api/fantasia/render?sello={sello}&d={d}&calidad=1"


def _datos_meta(sello, d, meta):
    """Metadatos legibles: parametros de generacion + recuento de paises y
    asentamientos de las capas si estan."""
    p = meta.get("params") or {}
    datos = {k: p[k] for k in ("semilla", "resolucion", "continentes", "mar",
                               "plumas", "tiempo") if k in p}
    datos["creado"] = meta.get("creado")
    try:
        capas = json.loads((SALIDAS / sello / "detalles" / f"{d}_capas.json")
                           .read_bytes())
        lista = (capas.get("paises") or {}).get("lista")
        if isinstance(lista, list):
            datos["paises"] = len(lista)
        if isinstance(capas.get("asentamientos"), list):
            datos["asentamientos"] = len(capas["asentamientos"])
    except (OSError, ValueError, AttributeError):
        pass
    return datos


def mundo(sello, d=None, email=None):
    """Ficha JSON de un mundo, o None si no existe o no tiene detalle usable.
    `email` = usuario de la sesion: el dueno solo se revela a si mismo."""
    meta = cargar_meta(sello)
    if meta is None:
        return None
    stem = resolver_detalle(sello, d)
    if stem is None:
        return None
    dueno = meta.get("dueno")
    es_dueno = bool(email and dueno and email == dueno)
    return {
        "sello": sello,
        "nombre": nombre_mundo(sello, meta),
        "d": stem,
        "meta": _datos_meta(sello, stem, meta),
        "publico": es_publico(sello, meta),
        "dueno": dueno if es_dueno else None,
        "es_dueno": es_dueno,
        "imagen": _imagen(sello, stem),
        "lugares": lugares(sello, stem),
    }


# ------------------------------- listados ----------------------------------

def _resumen(sello, meta, stem):
    return {"sello": sello, "nombre": nombre_mundo(sello, meta), "d": stem,
            "semilla": _semilla(meta), "creado": meta.get("creado"),
            "imagen": _imagen(sello, stem)}


def _publicos():
    """[(sello, meta, stem)] de los mundos publicos con detalle usable,
    ordenados por sello ascendente."""
    if not SALIDAS.exists():
        return []
    res = []
    for carpeta in sorted(SALIDAS.iterdir()):
        sello = carpeta.name
        if not carpeta.is_dir() or not _valido(sello):
            continue
        meta = cargar_meta(sello)
        if meta is None or not es_publico(sello, meta):
            continue
        stem = resolver_detalle(sello)
        if stem:
            res.append((sello, meta, stem))
    return res


def mundos_propios(email):
    """Sellos (del mas reciente al mas antiguo) cuyo meta tiene
    `dueno == email`, sean publicos o privados."""
    if not email or not SALIDAS.exists():
        return []
    res = []
    for carpeta in SALIDAS.iterdir():
        sello = carpeta.name
        if not carpeta.is_dir() or not _valido(sello):
            continue
        meta = cargar_meta(sello)
        if meta is not None and meta.get("dueno") == email:
            res.append(sello)
    return sorted(res, reverse=True)


def _normalizar(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def lista_publica(orden="nuevos", q="", n=24):
    """Mundos publicos resumidos. orden: nuevos (sello desc) | azar. `q` casa
    por sello exacto, semilla exacta o subcadena del nombre (sin acentos ni
    mayusculas)."""
    items = _publicos()
    q = _normalizar(q)
    if q:
        items = [it for it in items
                 if it[0] == q or str(_semilla(it[1])) == q
                 or q in _normalizar(nombre_mundo(it[0], it[1]))]
    if orden == "azar":
        random.shuffle(items)
    else:
        items.reverse()
    n = max(1, min(int(n), N_MAX))
    return [_resumen(*it) for it in items[:n]]


def buscar(q, n=24):
    """Atajo: lista_publica(orden='nuevos', q=q)."""
    return lista_publica("nuevos", q, n)


def _hoy():
    """Fecha UTC de hoy (punto de parcheo de las pruebas)."""
    return datetime.now(timezone.utc).date()


def mundo_del_dia(desde=None, email=None):
    """Ficha del mundo del dia: indice = sha256(fecha UTC) mod N sobre los
    publicos ordenados por sello; con `desde`, el siguiente (circular). None si
    no hay publicos."""
    items = _publicos()
    if not items:
        return None
    sellos = [it[0] for it in items]
    if desde in sellos:
        i = (sellos.index(desde) + 1) % len(sellos)
    else:
        h = hashlib.sha256(_hoy().isoformat().encode()).hexdigest()
        i = int(h, 16) % len(sellos)
    sello, _meta, stem = items[i]
    return mundo(sello, stem, email)


# ------------------------------- visibilidad --------------------------------

def cambiar_visibilidad(sello, publico, email):
    """Cambia `publico` si `email` es el dueno. Devuelve 'ok', 'no existe' o
    'prohibido'."""
    meta = cargar_meta(sello)
    if meta is None:
        return "no existe"
    if not email or meta.get("dueno") != email:
        return "prohibido"
    guardar_meta(sello, {"publico": bool(publico)})
    return "ok"
