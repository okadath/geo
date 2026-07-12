"""Motor del juego de conquista (server-authoritative).

Este modulo es el backend del juego «Age of History» que antes vivia entero en
el navegador (juego.html). Ahora TODA la logica propietaria corre aqui, en
Python, y el navegador queda como cliente delgado de presentacion:

  - Carga del mapa del lado servidor (numpy + PIL): provincias, adyacencias
    (tierra-tierra y tierra-mar-tierra), centroides, poblacion inicial,
    capitales y costas. Se cachea por (sello, stem) en memoria.
  - Motor completo: economia, puntos de accion, ordenes (mover / atacar con
    travesia naval y desembarcos con puerto, reclutar, disolver, construir),
    resolucion de batallas con azar del SERVIDOR, diplomacia, IA por pais,
    crecimiento de poblacion, eliminacion de paises y victoria/derrota.
  - Estado de partida persistido en disco: salidas/<sello>/partidas/<stem>.json
    (un slot por detalle; reemplaza al localStorage del navegador). Un lock de
    hilos protege el estado porque el servidor es multihilo.
  - API JSON bajo /api/juego/*.

Las CONSTANTES DE BALANCE (COSTO_TROPA, BONO_DEFENSA, PENA_NAVAL, PA_*, costes
de edificios, parametros de la IA por dificultad...) viven SOLO aqui. El front
nunca las ve: recibe el «estado visible» (duenos, tropas, poblacion, edificios,
oro y puntos del jugador, guerras, turno, vivos, ganador) y los datos estaticos
para pintar (centroides, adyacencias), pero jamas las formulas ni la logica.

Se enchufa en web.py por el hook de modulos: expone
    manejar_get(handler, url) -> bool
    manejar_post(handler, ruta, datos) -> bool
Solo biblioteca estandar + numpy + Pillow (ver requirements.txt).
"""
import json
import math
import random
import re
import threading
from pathlib import Path
from urllib.parse import parse_qs

import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parent
SALIDAS = BASE / "salidas"

# validacion estricta (sin traversal), igual que en web.py / juego.html
RE_SELLO = re.compile(r"^[0-9]{8}-[0-9]{6}(?:-[0-9]+)?$")
RE_STEM = re.compile(r"^d[0-9]{6}_f[0-9]+_[0-9a-f]{6}$")

# ===================================================================
#  CONSTANTES DE BALANCE  (propietarias: viven SOLO en el servidor)
# ===================================================================
NEUTRAL = -1
COSTO_TROPA = 3          # oro por tropa reclutada
BONO_DEFENSA = 1.2       # ventaja del defensor
PENA_NAVAL = 0.72        # penalizacion al desembarcar / cruzar el mar
HAB_TROPA = 150          # habitantes que consume cada tropa
DINERO_INICIAL = 120

EDIF = {                 # edificios: nombre, icono y coste en oro
    "bastion": {"nombre": "bastion", "icono": "\U0001F6E1", "costo": 45},
    "torre":   {"nombre": "torre",   "icono": "\U0001F441", "costo": 25},
    "puerto":  {"nombre": "puerto",  "icono": "⚓",     "costo": 55},
}
# puntos de accion (separados del oro)
PA_MOV, PA_NAVAL, PA_REC, PA_EDIF = 1, 2, 1, 2

# parametros de la IA por dificultad
DIFS = {
    "facil":   {"eco": 0.8,  "gasto": 0.5,  "agresion": 0.12, "margen": 1.6,  "edif": 0.15},
    "normal":  {"eco": 1.0,  "gasto": 0.8,  "agresion": 0.25, "margen": 1.25, "edif": 0.35},
    "dificil": {"eco": 1.35, "gasto": 0.95, "agresion": 0.4,  "margen": 1.05, "edif": 0.6},
}
AJUSTES_DEF = {"bastion": 50.0, "naval": 7.0, "recup": 0.6}


def jround(x):
    """Redondeo «medio hacia arriba» como el Math.round de JavaScript, para
    reproducir EXACTO el comportamiento numerico del motor original."""
    return int(math.floor(x + 0.5))


# ===================================================================
#  CARGA DEL MAPA  (numpy + PIL) — cacheada por (sello, stem)
# ===================================================================
_cache = {}                 # (sello, stem) -> mapa
_lock = threading.RLock()   # protege _cache y las partidas en disco/memoria


def _rutas(sello, stem):
    d = SALIDAS / sello / "detalles"
    return d / f"{stem}_capas.json", d / f"{stem}_regiones.png"


def _componentes_principales(ids):
    """Agrupa los pixeles del raster en componentes conexas por id (4-conexo,
    envolviendo en x, sin envolver en y — el mundo es esferico: los polos son
    borde) y devuelve, por cada pixel, si pertenece a la componente MAS GRANDE
    de su id («principal»). Sirve para ignorar pixeles sueltos de una provincia
    (islotes/artefactos lejanos de la malla gruesa de civilizacion) que si no se
    aislan generan adyacencias espurias con cuencas marinas lejanas.

    Union-find vectorizado (hook-to-min + compresion por salto de punteros,
    estilo Shiloach-Vishkin): rapido en numpy y se ejecuta una sola vez por
    mapa (queda cacheado)."""
    H, W = ids.shape
    N = H * W
    flat = ids.ravel()
    yy, xx = np.mgrid[0:H, 0:W]
    a = (yy * W + xx).ravel()
    # vecino derecho (envuelve en x)
    br = (yy * W + ((xx + 1) % W)).ravel()
    mh = (flat[a] == flat[br]) & (flat[a] != 0)
    # vecino inferior (NO envuelve en y)
    ad = (yy[:-1] * W + xx[:-1]).ravel()
    bd = ((yy[:-1] + 1) * W + xx[:-1]).ravel()
    md = (flat[ad] == flat[bd]) & (flat[ad] != 0)
    A = np.concatenate([a[mh], ad[md]])
    B = np.concatenate([br[mh], bd[md]])

    parent = np.arange(N, dtype=np.int64)

    def comprimir(p):
        while True:
            np_ = p[p]
            if np.array_equal(np_, p):
                return p
            p = np_

    while True:
        parent = comprimir(parent)
        ra, rb = parent[A], parent[B]
        nuevo = parent.copy()
        np.minimum.at(nuevo, ra, rb)   # hook del root mayor hacia el menor
        np.minimum.at(nuevo, rb, ra)
        if np.array_equal(nuevo, parent):
            break
        parent = nuevo
    roots = comprimir(parent)
    return roots.reshape(H, W)


def _rellenar_huecos(ids, max_iter=16):
    """Rellena los pixeles SIN clasificar (id=0) del raster asignando a cada uno
    el id del pixel clasificado mas cercano. Es una dilatacion multi-fuente de
    1 px por iteracion (frentes de BFS que avanzan a la vez desde todas las
    provincias), asi cada hueco acaba con el id de la region a menor distancia.

    Los huecos son bandas finas que el rasterizado deja en bordes/costas; con
    unas pocas iteraciones (tope `max_iter`) se cierran. Rellenar ANTES de
    calcular adyacencias hace que estas sean por contigüidad real de pixeles y
    elimina las brechas de <=3 px que antes se saltaban (adyacencias espurias).

    Envuelve SOLO en x (el mundo es esferico en longitud); el eje y son los
    polos: bordes que NUNCA se envuelven. Determinista: ante empate entre varios
    vecinos no-cero se toma el id menor."""
    out = ids.copy()
    centinela = np.iinfo(out.dtype).max if np.issubdtype(out.dtype, np.integer) \
        else np.iinfo(np.int64).max
    for _ in range(max_iter):
        ceros = out == 0
        if not ceros.any():
            break
        # candidatos desde los 4 vecinos inmediatos
        izq = np.roll(out, 1, axis=1)       # izquierda: envuelve en x
        der = np.roll(out, -1, axis=1)      # derecha:   envuelve en x
        arr = np.zeros_like(out)            # arriba: NO envuelve en y (polo)
        arr[1:, :] = out[:-1, :]
        aba = np.zeros_like(out)            # abajo:  NO envuelve en y (polo)
        aba[:-1, :] = out[1:, :]
        vecs = np.stack([izq, der, arr, aba])
        # id menor entre los vecinos no-cero (los ceros se ignoran con centinela)
        vpos = np.where(vecs == 0, centinela, vecs)
        vmin = vpos.min(axis=0)
        nuevos = ceros & (vmin != centinela)
        out[nuevos] = vmin[nuevos]
    return out


def _cargar_mapa(sello, stem):
    """Construye (o recupera de cache) el mapa estatico del detalle: provincias,
    paises, adyacencias, centroides, poblacion y guarniciones iniciales."""
    clave = (sello, stem)
    if clave in _cache:
        return _cache[clave]
    fjson, fpng = _rutas(sello, stem)
    if not fjson.exists() or not fpng.exists():
        return None
    capas = json.loads(fjson.read_text(encoding="utf-8"))
    sr = capas.get("subregiones")
    if not sr or not sr.get("png"):
        return None
    nx, ny = capas.get("resolucion", [1024, 1024])

    im = Image.open(fpng).convert("RGB")
    arr = np.asarray(im, dtype=np.uint32)          # (H, W, 3)
    ids = arr[:, :, 0] | (arr[:, :, 1] << 8)       # id de provincia por pixel
    H, W = ids.shape

    # rellena las bandas finas sin clasificar (id=0) que deja el rasterizado en
    # bordes/costas ANTES de calcular componentes y adyacencias: asi la
    # contigüidad es real y no hay que «saltar» huecos (que creaba vecindades
    # terrestres espurias entre provincias separadas por un estrecho/brecha).
    ids = _rellenar_huecos(ids)

    prov = {}          # id -> datos estaticos de la provincia (tierra o mar)
    paises = []        # [{id, nombre, rgb}]
    for r in (sr.get("mar") or []):
        prov[int(r["id"])] = {
            "id": int(r["id"]), "nombre": r.get("nombre", "mar"),
            "mar": True, "area": r.get("area", 0), "capital": False,
            "costera": False, "cx": 0.0, "cy": 0.0, "dueno0": NEUTRAL}
    paises_lista = ((capas.get("paises") or {}).get("lista")) or []
    paises_ids = set()
    for p in paises_lista:
        paises.append({"id": int(p["id"]), "nombre": p.get("nombre", "pais"),
                       "rgb": p.get("rgb", [150, 150, 150])})
        paises_ids.add(int(p["id"]))
    for r in (sr.get("tierra") or []):
        pid = int(r.get("pais", NEUTRAL))
        if pid not in paises_ids:
            pid = NEUTRAL
        prov[int(r["id"])] = {
            "id": int(r["id"]), "nombre": r.get("nombre", "provincia"),
            "mar": False, "area": r.get("area", 0), "capital": False,
            "costera": False, "cx": 0.0, "cy": 0.0, "dueno0": pid}

    # ---- componentes principales, centroides, contactos y adyacencias ----
    yy, xx = np.mgrid[0:H, 0:W]
    roots = _componentes_principales(ids)
    nz = ids != 0
    root_ids = np.full(ids.size, -1, dtype=np.int64)
    rflat = roots.ravel()
    fflat = ids.ravel()
    root_ids[rflat[nz.ravel()]] = fflat[nz.ravel()]
    root_count = np.bincount(rflat[nz.ravel()], minlength=ids.size)
    validos = np.where(root_count > 0)[0]
    vid = root_ids[validos]
    vc = root_count[validos]
    orden = np.lexsort((vc, vid))                  # por id asc, luego count asc
    vid_s = vid[orden]
    vroot_s = validos[orden]
    ultimo = np.ones(len(vid_s), dtype=bool)
    ultimo[:-1] = vid_s[1:] != vid_s[:-1]          # ultimo por id = mayor count
    maxid = int(fflat.max())
    id2root = np.zeros(maxid + 1, dtype=np.int64)
    id2root[vid_s[ultimo]] = vroot_s[ultimo]
    principal = nz & (roots == id2root[ids])       # pixel en la componente principal

    # adyacencia ESTRICTA por vecino inmediato (equivale a SALTO=1) sobre el
    # raster ya relleno: contigüidad genuina de pixeles, sin brechas. La derecha
    # envuelve en x (mundo esferico en longitud); abajo NO envuelve en y (polos).
    der = np.roll(ids, -1, axis=1)
    aba = np.zeros_like(ids)
    aba[:H - 1, :] = ids[1:, :]

    m_der = principal & (der != 0) & (der != ids)
    m_aba = principal & (aba != 0) & (aba != ids)
    pa = np.concatenate([ids[m_der], ids[m_aba]]).astype(np.int64)
    pb = np.concatenate([der[m_der], aba[m_aba]]).astype(np.int64)
    lo = np.minimum(pa, pb)
    hi = np.maximum(pa, pb)
    K = maxid + 1
    clave_par = lo * K + hi
    upar, cont = np.unique(clave_par, return_counts=True)

    # centroides (media circular en x) solo de la componente principal
    TAU = math.pi * 2
    mask_c = principal & np.isin(ids, np.array(list(prov.keys())))
    idc = ids[mask_c].astype(np.int64)
    ang = xx[mask_c] * TAU / W
    ncen = np.bincount(idc, minlength=maxid + 1)
    scos = np.bincount(idc, weights=np.cos(ang), minlength=maxid + 1)
    ssen = np.bincount(idc, weights=np.sin(ang), minlength=maxid + 1)
    sy = np.bincount(idc, weights=yy[mask_c].astype(float), minlength=maxid + 1)
    for pid, p in prov.items():
        if pid <= maxid and ncen[pid] > 0:
            a2 = math.atan2(ssen[pid] / ncen[pid], scos[pid] / ncen[pid])
            if a2 < 0:
                a2 += TAU
            p["cx"] = a2 / TAU * nx
            p["cy"] = sy[pid] / ncen[pid] * ny / H

    # ---- vecinos con umbral (mar exige mas contacto que tierra-tierra) ----
    vecinos = {}
    navales = {}
    mar_adj = {}       # id cuenca -> set(provincias costeras)
    UMBRAL_MAR = max(2, jround(W / 512))

    def _liga(a, b):
        vecinos.setdefault(a, set()).add(b)
        vecinos.setdefault(b, set()).add(a)

    for k, n in zip(upar.tolist(), cont.tolist()):
        a, b = k // K, k % K
        pa_, pb_ = prov.get(a), prov.get(b)
        if not pa_ or not pb_:
            continue
        umbral = UMBRAL_MAR if pa_["mar"] != pb_["mar"] else 1
        if n < umbral:
            continue
        _liga(a, b)
        if pa_["mar"] != pb_["mar"]:
            m_id, t = (a, b) if pa_["mar"] else (b, a)
            mar_adj.setdefault(m_id, set()).add(t)

    # vecinos navales: costas de la misma cuenca (sin repetir los terrestres)
    for costeras in mar_adj.values():
        for a in costeras:
            prov[a]["costera"] = True
        for a in costeras:
            for b in costeras:
                if a == b or b in vecinos.get(a, set()):
                    continue
                navales.setdefault(a, set()).add(b)

    mapa = {"nx": nx, "ny": ny, "rw": W, "rh": H, "ids": ids,
            "prov": prov, "paises": paises,
            "vecinos": vecinos, "navales": navales}

    # ---- poblacion inicial (asentamientos + base por area) y guarniciones ----
    def id_en(rx, ry):
        rxw = ((rx % nx) + nx) % nx
        x = int(rxw * W / nx)
        y = int(ry * H / ny)
        if x < 0 or y < 0 or x >= W or y >= H:
            return 0
        return int(ids[y, x])

    pob0 = {pid: 0 for pid in prov}
    for a in (capas.get("asentamientos") or []):
        pid = id_en(a.get("x", 0), a.get("y", 0))
        p = prov.get(pid)
        if not p or p["mar"]:
            continue
        pob0[pid] += a.get("poblacion", 0) or 0
        if a.get("rango") == 3:
            p["capital"] = True
    for pid, p in prov.items():
        if p["mar"]:
            p["pob0"] = 0
            p["ejercito0"] = 0
            continue
        pob = pob0[pid] + jround(p["area"] * 25)
        p["pob0"] = pob
        if p["dueno0"] == NEUTRAL:
            p["ejercito0"] = 2 + jround(pob / 60000)
        else:
            p["ejercito0"] = 4 + jround(pob / 40000) + (8 if p["capital"] else 0)

    _conectar_componentes(mapa)
    # sets -> se dejan como sets en memoria; se serializan a listas en /mapa
    _cache[clave] = mapa
    return mapa


def _conectar_componentes(mapa):
    """Garantiza que el grafo de MOVIMIENTO (vecinos terrestres UNION enlaces
    navales) sea UNA sola componente conexa. Sin esto, una isla cuya costa quedo
    bajo el umbral de contacto (o una cuenca aislada) seria inalcanzable e
    inconquistable.

    Los enlaces forzados NO se agregan como vecinos TERRESTRES: eso seria
    teletransporte por tierra entre provincias que no se tocan. Se agregan a
    «navales», de modo que cruzarlos exige puerto y paga el costo naval
    (PA_NAVAL), coherente con atravesar el mar. Se prefiere el par mas cercano
    (distancia entre centroides, envolviendo solo en x) en el que al menos una
    provincia sea mar o costera, y se marca costera=True a la(s) de tierra para
    que puedan levantar puerto."""
    prov, vecinos, navales = mapa["prov"], mapa["vecinos"], mapa["navales"]
    nx = mapa["nx"]

    def calc_componentes():
        comp = {}
        n = 0
        for pid in prov:
            if pid in comp:
                continue
            cola = [pid]
            comp[pid] = n
            while cola:
                a = cola.pop()
                # el grafo de movimiento incluye tierra (vecinos) Y mar (navales)
                for b in set(vecinos.get(a, ())) | set(navales.get(a, ())):
                    if b in prov and b not in comp:
                        comp[b] = n
                        cola.append(b)
            n += 1
        return comp, n

    comp_de, ncomp = calc_componentes()
    if ncomp <= 1:
        return

    def dist2(a, b):
        dx = abs(a["cx"] - b["cx"])
        dx = min(dx, nx - dx)
        dy = a["cy"] - b["cy"]
        return dx * dx + dy * dy

    while True:
        grupos = {}
        for pid, c in comp_de.items():
            grupos.setdefault(c, []).append(prov[pid])
        if len(grupos) <= 1:
            break
        chica_c = min(grupos, key=lambda c: len(grupos[c]))
        chica = grupos[chica_c]
        mejor = None          # par mas cercano sin restriccion (respaldo)
        mejor_mar = None      # par mas cercano con contacto potencial de mar
        for a in chica:
            for c, ps in grupos.items():
                if c == chica_c:
                    continue
                for b in ps:
                    d = dist2(a, b)
                    if mejor is None or d < mejor[2]:
                        mejor = (a, b, d)
                    if a["mar"] or b["mar"] or a["costera"] or b["costera"]:
                        if mejor_mar is None or d < mejor_mar[2]:
                            mejor_mar = (a, b, d)
        elegido = mejor_mar or mejor
        if not elegido:
            break
        a, b, _ = elegido
        # enlace NAVAL (no terrestre): exige puerto y paga costo naval
        navales.setdefault(a["id"], set()).add(b["id"])
        navales.setdefault(b["id"], set()).add(a["id"])
        # la(s) provincia(s) de tierra del enlace deben poder tener puerto
        if not a["mar"]:
            a["costera"] = True
        if not b["mar"]:
            b["costera"] = True
        destino = comp_de[b["id"]]
        for pid, c in list(comp_de.items()):
            if c == chica_c:
                comp_de[pid] = destino


# ===================================================================
#  ESTADO DE PARTIDA  (mutable, persistido en disco)
# ===================================================================
def _ruta_partida(sello, stem):
    return SALIDAS / sello / "partidas" / f"{stem}.json"


def _nueva_partida(mapa, sello, stem, jugador, dif_key, ajustes):
    prov = {}
    for pid, p in mapa["prov"].items():
        prov[pid] = {"dueno": p["dueno0"], "pob": p["pob0"],
                     "ejercito": p["ejercito0"], "movida": False,
                     "bastion": False, "torre": False, "puerto": False}
    paises = {}
    for p in mapa["paises"]:
        paises[p["id"]] = {"dinero": DINERO_INICIAL, "puntos": 0,
                           "vivo": True, "ia": True}
    paises[NEUTRAL] = {"dinero": 0, "puntos": 0, "vivo": True, "ia": False}
    part = {
        "sello": sello, "stem": stem, "turno": 1, "jugador": jugador,
        "difKey": dif_key if dif_key in DIFS else "normal",
        "ajustes": dict(ajustes), "fase": "jugando",
        "ganador": None, "resultado": None,
        "guerras": set(), "paises": paises, "prov": prov,
        "historia": [], "replay": [], "_duenoPrev": {}, "_eventos": [],
    }
    part["paises"][jugador]["ia"] = False
    part["paises"][jugador]["puntos"] = _puntos_max(mapa, part, jugador)
    _registrar_historia(mapa, part)
    part["_duenoPrev"] = {pid: p["dueno"] for pid, p in prov.items()}
    part["replay"] = [{"turno": 1, "cambios": {str(pid): p["dueno"]
                                               for pid, p in prov.items()}}]
    return part


def _serializar(part):
    d = dict(part)
    d["guerras"] = sorted(part["guerras"])
    d["_duenoPrev"] = {str(k): v for k, v in part["_duenoPrev"].items()}
    d["paises"] = {str(k): v for k, v in part["paises"].items()}
    d["prov"] = {str(k): v for k, v in part["prov"].items()}
    d.pop("_eventos", None)
    return d


def _deserializar(d):
    part = dict(d)
    part["guerras"] = set(d.get("guerras", []))
    part["paises"] = {int(k): v for k, v in d.get("paises", {}).items()}
    part["prov"] = {int(k): v for k, v in d.get("prov", {}).items()}
    part["_duenoPrev"] = {int(k): v for k, v in d.get("_duenoPrev", {}).items()}
    part.setdefault("historia", [])
    part.setdefault("replay", [])
    part["_eventos"] = []
    return part


def _guardar_partida(part):
    ruta = _ruta_partida(part["sello"], part["stem"])
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(_serializar(part), ensure_ascii=False),
                    encoding="utf-8")


def _cargar_partida(sello, stem):
    ruta = _ruta_partida(sello, stem)
    if not ruta.exists():
        return None
    try:
        return _deserializar(json.loads(ruta.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


# ===================================================================
#  MOTOR  (economia, batallas, IA, fin de turno)  — logica propietaria
# ===================================================================
def _es_mar(mapa, pid):
    return mapa["prov"][pid]["mar"]


def _par_guerra(a, b):
    return f"{a}|{b}" if a < b else f"{b}|{a}"


def _en_guerra(part, a, b):
    return _par_guerra(a, b) in part["guerras"]


def _anotar(part, msj, prov_id=None):
    part["_eventos"].append({"msj": msj, "prov": prov_id})


def _ingreso_prov(mapa, part, pid):
    p = part["prov"][pid]
    return 0.0 if mapa["prov"][pid]["mar"] else 1 + p["pob"] / 45000


def _reclutable(mapa, part, pid):
    if mapa["prov"][pid]["mar"]:
        return 0
    return max(0, (part["prov"][pid]["pob"] - 500) // HAB_TROPA)


def _ingreso_pais(mapa, part, pid):
    s = 0.0
    for i, p in part["prov"].items():
        if p["dueno"] == pid:
            s += _ingreso_prov(mapa, part, i)
    return jround(s)


def _resumen_pais(mapa, part, pid):
    provs = 0
    ej = 0
    for i, p in part["prov"].items():
        if p["dueno"] == pid:
            if not mapa["prov"][i]["mar"]:
                provs += 1
            ej += p["ejercito"]
    return provs, ej


def _puntos_max(mapa, part, pid):
    provs, _ = _resumen_pais(mapa, part, pid)
    return min(30, 4 + provs // 2)


def _nombre_pais(mapa, pid):
    if pid == NEUTRAL:
        return "tierras neutrales"
    for p in mapa["paises"]:
        if p["id"] == pid:
            return p["nombre"]
    return "?"


def _declarar_guerra(mapa, part, a, b):
    if a == NEUTRAL or b == NEUTRAL or _en_guerra(part, a, b):
        return
    part["guerras"].add(_par_guerra(a, b))
    _anotar(part, f"{_nombre_pais(mapa, a)} declara la guerra a {_nombre_pais(mapa, b)}")


def _hacer_paz(mapa, part, a, b):
    part["guerras"].discard(_par_guerra(a, b))
    _anotar(part, f"{_nombre_pais(mapa, a)} y {_nombre_pais(mapa, b)} firman la paz")


def _normalizar_mar(mapa, part, pid):
    p = part["prov"][pid]
    if mapa["prov"][pid]["mar"] and p["ejercito"] <= 0:
        p["dueno"] = NEUTRAL
        p["ejercito"] = 0
        p["movida"] = False


def _atacar(mapa, part, origen, destino, naval, n=None):
    """Resuelve un ataque origen->destino con `n` tropas (por defecto todas menos
    la guarnicion). Azar del SERVIDOR. Devuelve True si conquista."""
    A = part["prov"][origen]
    D = part["prov"][destino]
    A_mar = mapa["prov"][origen]["mar"]
    D_mar = mapa["prov"][destino]["mar"]
    res = 0 if A_mar else 1
    disp = A["ejercito"] - res
    tropas = min(disp if n is None else n, disp)
    if tropas < 1:
        return False
    atacante = A["dueno"]
    defensor = D["dueno"]
    nA = _nombre_pais(mapa, atacante)
    nD = mapa["prov"][destino]["nombre"]
    if defensor == NEUTRAL and D["ejercito"] <= 0:
        A["ejercito"] -= tropas
        A["movida"] = True
        _normalizar_mar(mapa, part, origen)
        D["dueno"] = atacante
        D["ejercito"] = tropas
        D["movida"] = True
        _anotar(part, f"{nA} ocupa {nD}", destino)
        return True

    def azar():
        return 0.85 + random.random() * 0.3

    desembarco = naval or (A_mar and not D_mar)
    bono_bastion = 1 + part["ajustes"]["bastion"] / 100
    fA = tropas * azar() * (PENA_NAVAL if desembarco else 1)
    fD = max(D["ejercito"], 0.5) * BONO_DEFENSA * \
        (bono_bastion if D["bastion"] else 1) * azar()
    defensores = D["ejercito"]
    A["ejercito"] -= tropas
    A["movida"] = True
    _normalizar_mar(mapa, part, origen)

    def despoblar(caidos, es_naval):
        if D_mar:
            return
        factor = (1 - part["ajustes"]["naval"] / 100) if es_naval else 0.97
        D["pob"] = max(100, jround(D["pob"] * factor - caidos * HAB_TROPA / 2))

    if fA > fD:
        sobran = max(1, jround(tropas * (fA - fD) / fA))
        D["dueno"] = atacante
        D["ejercito"] = sobran
        D["movida"] = True
        D["bastion"] = False
        despoblar((tropas - sobran) + defensores, desembarco)
        _anotar(part, f"{nA} conquista {nD}" + (" (desembarco)" if desembarco else ""), destino)
        _comprobar_muerte(mapa, part, defensor)
        return True
    D["ejercito"] = max(1, jround(D["ejercito"] * (fD - fA) / fD))
    despoblar(tropas + (defensores - D["ejercito"]), False)
    _anotar(part, f"{nD} resiste el ataque de {nA}", destino)
    return False


def _comprobar_muerte(mapa, part, pid):
    if pid == NEUTRAL:
        return
    for i, p in part["prov"].items():
        if not mapa["prov"][i]["mar"] and p["dueno"] == pid:
            return
    for i, p in part["prov"].items():          # sus flotas se dispersan
        if mapa["prov"][i]["mar"] and p["dueno"] == pid:
            p["dueno"] = NEUTRAL
            p["ejercito"] = 0
    part["paises"][pid]["vivo"] = False
    for g in list(part["guerras"]):
        if pid in map(int, g.split("|")):
            part["guerras"].discard(g)
    _anotar(part, f"\U0001F480 {_nombre_pais(mapa, pid)} ha sido eliminado")
    _comprobar_victoria(mapa, part)


def _comprobar_victoria(mapa, part):
    if part["fase"] != "jugando":
        return
    provs, _ = _resumen_pais(mapa, part, part["jugador"])
    if not provs:
        part["fase"] = "fin"
        part["resultado"] = "derrota"
        _anotar(part, "\U0001F480 tu pais ha sido borrado del mapa")
        return
    rivales = [p for p in mapa["paises"]
               if p["id"] != part["jugador"] and part["paises"][p["id"]]["vivo"]]
    if not rivales:
        part["fase"] = "fin"
        part["resultado"] = "victoria"
        part["ganador"] = part["jugador"]
        _anotar(part, "\U0001F451 has conquistado el mundo")


# ---- IA por pais (misma logica que juego.html) ----
def _turno_ia(mapa, part, pid):
    pais = part["paises"][pid]
    if not pais["vivo"]:
        return
    dif = DIFS[part["difKey"]]
    vecinos, navales = mapa["vecinos"], mapa["navales"]
    mias = [i for i, p in part["prov"].items() if p["dueno"] == pid]
    if not mias:
        return
    pais["dinero"] += jround(_ingreso_pais(mapa, part, pid) * dif["eco"])
    pais["puntos"] = _puntos_max(mapa, part, pid)
    jugador = part["jugador"]

    mi_fuerza = sum(part["prov"][i]["ejercito"] for i in mias)
    for g in list(part["guerras"]):
        a, b = map(int, g.split("|"))
        if a != pid and b != pid:
            continue
        otro = b if a == pid else a
        _, su_fuerza = _resumen_pais(mapa, part, otro)
        if mi_fuerza < su_fuerza * 0.45 and random.random() < 0.5 and otro != jugador:
            _hacer_paz(mapa, part, pid, otro)

    fronteras = {}    # pid vecino -> [provincias mias de borde]
    for i in mias:
        vs = set(vecinos.get(i, set())) | set(navales.get(i, set()))
        for v in vs:
            o = part["prov"].get(v)
            if o and o["dueno"] != pid and not (
                    mapa["prov"][v]["mar"] and o["dueno"] == NEUTRAL and o["ejercito"] <= 0):
                fronteras.setdefault(o["dueno"], []).append(i)

    # declarar guerra a un vecino claramente mas debil
    ya_en_guerra = any(pid in map(int, g.split("|")) for g in part["guerras"])
    if not ya_en_guerra and random.random() < dif["agresion"]:
        mejor = None
        for otro in fronteras:
            if otro == NEUTRAL or _en_guerra(part, pid, otro):
                continue
            _, f = _resumen_pais(mapa, part, otro)
            if f < mi_fuerza * 0.6 and (mejor is None or f < mejor[1]):
                mejor = (otro, f)
        if mejor:
            _declarar_guerra(mapa, part, pid, mejor[0])

    bordes = list({i for lst in fronteras.values() for i in lst})
    # construir bastion en el borde mas flojo
    if bordes and random.random() < dif["edif"] and pais["puntos"] >= PA_EDIF:
        sin_b = [i for i in bordes if not mapa["prov"][i]["mar"]
                 and not part["prov"][i]["bastion"]]
        if sin_b and pais["dinero"] >= EDIF["bastion"]["costo"] + 30:
            donde = min(sin_b, key=lambda i: part["prov"][i]["ejercito"])
            part["prov"][donde]["bastion"] = True
            pais["dinero"] -= EDIF["bastion"]["costo"]
            pais["puntos"] -= PA_EDIF
    # construir puerto en alguna costa amenazada
    if random.random() < dif["edif"] * 0.6 and \
            pais["dinero"] >= EDIF["puerto"]["costo"] + 40 and pais["puntos"] >= PA_EDIF:
        costa = None
        for i in mias:
            p = part["prov"][i]
            if mapa["prov"][i]["costera"] and not p["puerto"] and any(
                    part["prov"].get(v) and part["prov"][v]["dueno"] != pid
                    for v in navales.get(i, set())):
                costa = i
                break
        if costa is not None:
            part["prov"][costa]["puerto"] = True
            pais["dinero"] -= EDIF["puerto"]["costo"]
            pais["puntos"] -= PA_EDIF

    # reclutar en la provincia de borde mas amenazada
    bordes_tierra = [i for i in bordes if not mapa["prov"][i]["mar"]]
    if bordes_tierra and pais["puntos"] >= PA_REC:
        gasto = int(pais["dinero"] * dif["gasto"] // COSTO_TROPA)
        if gasto > 0:
            donde = min(bordes_tierra, key=lambda i: part["prov"][i]["ejercito"])
            n = min(gasto, _reclutable(mapa, part, donde))
            if n > 0:
                part["prov"][donde]["ejercito"] += n
                part["prov"][donde]["pob"] -= n * HAB_TROPA
                pais["dinero"] -= n * COSTO_TROPA
                pais["puntos"] -= PA_REC

    # atacar: cada provincia con tropas busca el vecino valido mas debil
    for i in mias:
        p = part["prov"][i]
        if p["movida"] or p["ejercito"] < 5 or p["dueno"] != pid:
            continue
        if pais["puntos"] < PA_MOV:
            break
        mejor = None
        mejor_naval = False
        p_mar = mapa["prov"][i]["mar"]

        def mirar(v, naval, _p=p, _pmar=p_mar):
            nonlocal mejor, mejor_naval
            o = part["prov"].get(v)
            if not o or o["dueno"] == pid:
                return
            o_mar = mapa["prov"][v]["mar"]
            if o_mar and o["dueno"] == NEUTRAL and o["ejercito"] <= 0:
                return
            if not (o["dueno"] == NEUTRAL or _en_guerra(part, pid, o["dueno"])):
                return
            eff = (_p["ejercito"] - (0 if _pmar else 1)) * \
                (PENA_NAVAL if (naval or (_pmar and not o_mar)) else 1)
            umbral = o["ejercito"] * BONO_DEFENSA * \
                (1 + part["ajustes"]["bastion"] / 100 if o["bastion"] else 1) * dif["margen"]
            if eff > umbral and (mejor is None or o["ejercito"] < part["prov"][mejor]["ejercito"]):
                mejor = v
                mejor_naval = naval

        for v in vecinos.get(i, set()):
            mirar(v, False)
        if mejor is None and p["puerto"] and pais["puntos"] >= PA_NAVAL:
            for v in navales.get(i, set()):
                mirar(v, True)
        if mejor is not None:
            costo = PA_NAVAL if mejor_naval else PA_MOV
            if pais["puntos"] < costo:
                continue
            pais["puntos"] -= costo
            _atacar(mapa, part, i, mejor, mejor_naval)

    # mover reservas interiores hacia el frente
    interior = [i for i in mias if not part["prov"][i]["movida"]
                and part["prov"][i]["ejercito"] > 6 and i not in bordes]
    borde_set = set(bordes)
    for i in interior:
        if pais["puntos"] < PA_MOV:
            break
        p = part["prov"][i]
        vs = [v for v in vecinos.get(i, set())
              if part["prov"].get(v) and part["prov"][v]["dueno"] == pid]
        if not vs:
            continue
        destino = vs[0]
        for v in vs[1:]:
            if v in borde_set and destino not in borde_set:
                destino = v
            elif part["prov"][v]["ejercito"] > part["prov"][destino]["ejercito"] \
                    and not (destino in borde_set and v not in borde_set):
                destino = v
        enviar = p["ejercito"] - (0 if mapa["prov"][i]["mar"] else 1)
        part["prov"][destino]["ejercito"] += enviar
        p["ejercito"] -= enviar
        p["movida"] = True
        _normalizar_mar(mapa, part, i)
        pais["puntos"] -= PA_MOV


def _fin_de_turno(mapa, part):
    """Cobra el ingreso del jugador, resuelve la IA de todos los paises,
    aplica crecimiento de poblacion y renueva puntos: un turno global."""
    jugador = part["jugador"]
    part["paises"][jugador]["dinero"] += _ingreso_pais(mapa, part, jugador)
    ias = [p["id"] for p in mapa["paises"]
           if p["id"] != jugador and part["paises"][p["id"]]["ia"]
           and part["paises"][p["id"]]["vivo"]]
    random.shuffle(ias)
    for pid in ias:
        _turno_ia(mapa, part, pid)
        if part["fase"] != "jugando":
            break
    crec = 1 + part["ajustes"]["recup"] / 100
    for p in part["prov"].values():
        p["movida"] = False
        p["pob"] = jround(p["pob"] * crec)
    part["turno"] += 1
    part["paises"][jugador]["puntos"] = _puntos_max(mapa, part, jugador)
    _registrar_historia(mapa, part)
    _registrar_replay_diff(part)
    _comprobar_victoria(mapa, part)


def _registrar_historia(mapa, part):
    datos = {}
    for p in mapa["paises"]:
        pid = p["id"]
        if not part["paises"][pid]["vivo"]:
            continue
        pob = sum(pr["pob"] for i, pr in part["prov"].items()
                  if not mapa["prov"][i]["mar"] and pr["dueno"] == pid)
        _, ej = _resumen_pais(mapa, part, pid)
        datos[str(pid)] = {"pob": jround(pob), "mil": ej,
                           "oro": _ingreso_pais(mapa, part, pid)}
    part["historia"].append({"turno": part["turno"], "datos": datos})


def _registrar_replay_diff(part):
    cambios = {}
    for pid, p in part["prov"].items():
        if part["_duenoPrev"].get(pid) != p["dueno"]:
            cambios[str(pid)] = p["dueno"]
            part["_duenoPrev"][pid] = p["dueno"]
    if cambios:
        part["replay"].append({"turno": part["turno"], "cambios": cambios})


# ---- vision / niebla de guerra (para ocultar tropas enemigas al front) ----
def _calc_vision(mapa, part):
    vecinos, navales = mapa["vecinos"], mapa["navales"]
    jugador = part["jugador"]
    vis = set()
    for i, p in part["prov"].items():
        if p["dueno"] != jugador:
            continue
        vis.add(i)
        for v in vecinos.get(i, set()):
            vis.add(v)
            if p["torre"]:
                for v2 in vecinos.get(v, set()):
                    vis.add(v2)
        if p["puerto"]:
            for v in navales.get(i, set()):
                vis.add(v)
    return vis


# ===================================================================
#  ESTADO VISIBLE  (lo unico que viaja al front)
# ===================================================================
def _estado_visible(mapa, part, con_eventos=False):
    jugador = part["jugador"]
    vision = _calc_vision(mapa, part)
    paises = []
    for p in mapa["paises"]:
        pid = p["id"]
        pp = part["paises"][pid]
        provs, ej = _resumen_pais(mapa, part, pid)
        item = {"id": pid, "nombre": p["nombre"], "rgb": p["rgb"],
                "vivo": pp["vivo"], "provs": provs, "ej": ej}
        if pid == jugador:      # solo el jugador ve su oro y puntos
            item["dinero"] = pp["dinero"]
            item["puntos"] = pp["puntos"]
            item["puntosMax"] = _puntos_max(mapa, part, jugador)
            item["ingreso"] = _ingreso_pais(mapa, part, jugador)
        paises.append(item)
    prov = []
    for i, p in part["prov"].items():
        visible = p["dueno"] == jugador or i in vision
        propia = p["dueno"] == jugador and not mapa["prov"][i]["mar"]
        prov.append({
            "id": i, "dueno": p["dueno"], "pob": p["pob"],
            # las tropas enemigas fuera de vision NO se envian (anti-cheat)
            "ejercito": p["ejercito"] if visible else None,
            "movida": p["movida"], "bastion": p["bastion"],
            "torre": p["torre"], "puerto": p["puerto"], "visible": visible,
            # ayudas de presentacion (solo para provincias propias): el ingreso
            # y el maximo reclutable ya calculados, para rotular la ficha sin
            # que el front conozca las formulas
            "ingreso": round(_ingreso_prov(mapa, part, i), 1) if propia else None,
            "reclutable": _reclutable(mapa, part, i) if propia else None})
    est = {
        "existe": True, "turno": part["turno"], "jugador": jugador,
        "fase": part["fase"], "difKey": part["difKey"],
        "ajustes": part["ajustes"], "ganador": part["ganador"],
        "resultado": part["resultado"], "guerras": sorted(part["guerras"]),
        "paises": paises, "prov": prov,
        "historia": part["historia"], "replay": part["replay"],
    }
    if con_eventos:
        est["eventos"] = part["_eventos"]
    return est


def _datos_mapa(mapa):
    """Datos ESTATICOS para pintar (no formulas): provincias con centroide,
    nombre, tipo, capital, costa y pais inicial; adyacencias tierra y navales."""
    prov = []
    ini = {}      # pid -> [provincias iniciales, ejercito inicial] (pantalla de inicio)
    for pid, p in mapa["prov"].items():
        prov.append({"id": pid, "nombre": p["nombre"], "mar": p["mar"],
                     "area": p["area"], "capital": p["capital"],
                     "costera": p["costera"], "cx": p["cx"], "cy": p["cy"],
                     "pais": p["dueno0"]})
        d = p["dueno0"]
        if d != NEUTRAL:
            r = ini.setdefault(d, [0, 0])
            if not p["mar"]:
                r[0] += 1
            r[1] += p["ejercito0"]
    paises = [dict(p, provs=ini.get(p["id"], [0, 0])[0],
                   ej=ini.get(p["id"], [0, 0])[1]) for p in mapa["paises"]]
    vecinos = {str(k): sorted(v) for k, v in mapa["vecinos"].items()}
    navales = {str(k): sorted(v) for k, v in mapa["navales"].items()}
    # precios para ROTULAR los botones (no son la logica: solo etiquetas que
    # el front muestra; el servidor sigue siendo quien valida cada gasto)
    precios = {"tropa": COSTO_TROPA,
               "edif": {k: {"nombre": e["nombre"], "icono": e["icono"],
                            "costo": e["costo"]} for k, e in EDIF.items()},
               "pa": {"mov": PA_MOV, "naval": PA_NAVAL,
                      "rec": PA_REC, "edif": PA_EDIF}}
    return {"nx": mapa["nx"], "ny": mapa["ny"], "rw": mapa["rw"], "rh": mapa["rh"],
            "prov": prov, "paises": paises,
            "vecinos": vecinos, "navales": navales, "precios": precios}


# ===================================================================
#  API  /api/juego/*
# ===================================================================
def _valida(sello, stem):
    return bool(RE_SELLO.match(sello or "")) and bool(RE_STEM.match(stem or ""))


def manejar_get(handler, url):
    ruta = url.path
    if not ruta.startswith("/api/juego/"):
        return False
    q = parse_qs(url.query)
    sello = q.get("sello", [""])[0]
    stem = q.get("d", [""])[0]
    if ruta == "/api/juego/mapa":
        if not _valida(sello, stem):
            handler._json({"error": "sello/d invalidos"}, 400)
            return True
        with _lock:
            mapa = _cargar_mapa(sello, stem)
        if not mapa:
            handler._json({"error": "detalle sin subregiones"}, 404)
            return True
        handler._json(_datos_mapa(mapa))
        return True
    if ruta == "/api/juego/estado":
        if not _valida(sello, stem):
            handler._json({"error": "sello/d invalidos"}, 400)
            return True
        with _lock:
            mapa = _cargar_mapa(sello, stem)
            part = _cargar_partida(sello, stem)
            if not mapa or not part:
                handler._json({"existe": False})
                return True
            handler._json(_estado_visible(mapa, part))
        return True
    handler._json({"error": "no existe"}, 404)
    return True


def manejar_post(handler, ruta, datos):
    if not ruta.startswith("/api/juego/"):
        return False
    sello = str(datos.get("sello", ""))
    stem = str(datos.get("d", ""))
    if not _valida(sello, stem):
        handler._json({"error": "sello/d invalidos"}, 400)
        return True

    if ruta == "/api/juego/nueva":
        with _lock:
            mapa = _cargar_mapa(sello, stem)
            if not mapa:
                handler._json({"error": "detalle sin subregiones"}, 404)
                return True
            jugador = int(datos.get("jugador", datos.get("pais", -999)))
            if jugador not in part_paises_validos(mapa):
                handler._json({"error": "pais invalido"}, 400)
                return True
            dif = str(datos.get("dificultad", "normal"))
            aj = _limpiar_ajustes(datos.get("ajustes") or {})
            part = _nueva_partida(mapa, sello, stem, jugador, dif, aj)
            _guardar_partida(part)
            handler._json(_estado_visible(mapa, part))
        return True

    if ruta == "/api/juego/borrar":
        with _lock:
            r = _ruta_partida(sello, stem)
            if r.exists():
                r.unlink()
        handler._json({"ok": True})
        return True

    # el resto necesita partida cargada
    with _lock:
        mapa = _cargar_mapa(sello, stem)
        part = _cargar_partida(sello, stem)
        if not mapa or not part:
            handler._json({"error": "no hay partida"}, 404)
            return True
        part["_eventos"] = []

        if ruta == "/api/juego/orden":
            ok, msj = _procesar_orden(mapa, part, datos)
            _guardar_partida(part)
            est = _estado_visible(mapa, part, con_eventos=True)
            est["ok"] = ok
            est["mensaje"] = msj
            handler._json(est)
            return True

        if ruta == "/api/juego/turno":
            if part["fase"] != "jugando":
                handler._json({"error": "la partida no esta en juego"}, 400)
                return True
            _fin_de_turno(mapa, part)
            _guardar_partida(part)
            handler._json(_estado_visible(mapa, part, con_eventos=True))
            return True

        if ruta == "/api/juego/diplomacia":
            ok, msj = _procesar_diplomacia(mapa, part, datos)
            _guardar_partida(part)
            est = _estado_visible(mapa, part, con_eventos=True)
            est["ok"] = ok
            est["mensaje"] = msj
            handler._json(est)
            return True

    handler._json({"error": "no existe"}, 404)
    return True


def part_paises_validos(mapa):
    return {p["id"] for p in mapa["paises"]}


def _limpiar_ajustes(aj):
    out = dict(AJUSTES_DEF)
    for k, (lo, hi) in {"bastion": (0, 200), "naval": (0, 50), "recup": (0, 10)}.items():
        try:
            out[k] = min(max(float(aj.get(k, out[k])), lo), hi)
        except (TypeError, ValueError):
            pass
    return out


# ---- procesar una orden del jugador (valida TODO en el servidor) ----
def _procesar_orden(mapa, part, datos):
    if part["fase"] != "jugando":
        return False, "no es tu turno"
    accion = str(datos.get("accion") or datos.get("tipo") or "")
    jugador = part["jugador"]
    yo = part["paises"][jugador]

    if accion in ("mover", "atacar", "orden"):
        try:
            origen = int(datos["origen"])
            destino = int(datos["destino"])
        except (KeyError, TypeError, ValueError):
            return False, "faltan origen/destino"
        if origen not in part["prov"] or destino not in part["prov"]:
            return False, "provincia inexistente"
        A = part["prov"][origen]
        D = part["prov"][destino]
        A_mar = mapa["prov"][origen]["mar"]
        if A["dueno"] != jugador or A["movida"]:
            return False, "origen invalido"
        if A["ejercito"] < (1 if A_mar else 2):
            return False, "sin tropas para mover"
        es_vecino = destino in mapa["vecinos"].get(origen, set())
        es_naval_dest = destino in mapa["navales"].get(origen, set())
        if not es_vecino and not es_naval_dest:
            return False, "destino no alcanzable"
        naval = not es_vecino
        if naval and not A["puerto"]:
            return False, "hace falta un puerto para cruzar el mar"
        costo = PA_NAVAL if naval else PA_MOV
        if yo["puntos"] < costo:
            return False, "sin puntos de accion"
        tropas = datos.get("tropas")
        maxn = A["ejercito"] - (0 if A_mar else 1)
        n = maxn if tropas is None else max(1, min(int(tropas), maxn))
        yo["puntos"] -= costo
        if D["dueno"] == jugador:                 # mover
            D["ejercito"] += n
            A["ejercito"] -= n
            A["movida"] = True
            _normalizar_mar(mapa, part, origen)
            _anotar(part, f"mueves {n} tropas de {mapa['prov'][origen]['nombre']} "
                          f"a {mapa['prov'][destino]['nombre']}", destino)
        else:                                     # atacar
            if D["dueno"] != NEUTRAL and not _en_guerra(part, jugador, D["dueno"]):
                _declarar_guerra(mapa, part, jugador, D["dueno"])
            _atacar(mapa, part, origen, destino, naval, n)
        _comprobar_victoria(mapa, part)
        return True, "orden ejecutada"

    if accion == "reclutar":
        pid = int(datos.get("prov", -1))
        n = int(datos.get("n", 0))
        if pid not in part["prov"]:
            return False, "provincia inexistente"
        p = part["prov"][pid]
        if mapa["prov"][pid]["mar"] or p["dueno"] != jugador:
            return False, "no puedes reclutar aqui"
        costo = n * COSTO_TROPA
        if n < 1 or yo["dinero"] < costo or _reclutable(mapa, part, pid) < n \
                or yo["puntos"] < PA_REC:
            return False, "no puedes reclutar tantas"
        yo["dinero"] -= costo
        yo["puntos"] -= PA_REC
        p["ejercito"] += n
        p["pob"] -= n * HAB_TROPA
        _anotar(part, f"reclutas {n} tropas en {mapa['prov'][pid]['nombre']}", pid)
        return True, "reclutado"

    if accion == "disolver":
        pid = int(datos.get("prov", -1))
        n = int(datos.get("n", 0))
        if pid not in part["prov"]:
            return False, "provincia inexistente"
        p = part["prov"][pid]
        if mapa["prov"][pid]["mar"] or p["dueno"] != jugador or yo["puntos"] < PA_REC:
            return False, "no puedes disolver aqui"
        nn = min(n, p["ejercito"] - 1)
        if nn < 1:
            return False, "debe quedar al menos 1 tropa"
        yo["puntos"] -= PA_REC
        p["ejercito"] -= nn
        p["pob"] += nn * HAB_TROPA
        _anotar(part, f"disuelves {nn} tropas en {mapa['prov'][pid]['nombre']}", pid)
        return True, "disuelto"

    if accion == "construir":
        pid = int(datos.get("prov", -1))
        tipo = str(datos.get("edif", ""))
        if pid not in part["prov"] or tipo not in EDIF:
            return False, "edificio invalido"
        p = part["prov"][pid]
        e = EDIF[tipo]
        if mapa["prov"][pid]["mar"] or p["dueno"] != jugador or p[tipo] \
                or yo["dinero"] < e["costo"] or yo["puntos"] < PA_EDIF:
            return False, "no puedes construir"
        if tipo == "puerto" and not mapa["prov"][pid]["costera"]:
            return False, "el puerto necesita costa"
        yo["dinero"] -= e["costo"]
        yo["puntos"] -= PA_EDIF
        p[tipo] = True
        _anotar(part, f"{e['icono']} {e['nombre']} construido en "
                      f"{mapa['prov'][pid]['nombre']}", pid)
        return True, "construido"

    return False, "accion desconocida"


def _procesar_diplomacia(mapa, part, datos):
    if part["fase"] != "jugando":
        return False, "no es tu turno"
    accion = str(datos.get("accion", ""))
    jugador = part["jugador"]
    try:
        otro = int(datos.get("pais"))
    except (TypeError, ValueError):
        return False, "pais invalido"
    if otro == jugador or otro == NEUTRAL or otro not in part["paises"]:
        return False, "pais invalido"
    if accion == "guerra":
        if _en_guerra(part, jugador, otro):
            return False, "ya estan en guerra"
        _declarar_guerra(mapa, part, jugador, otro)
        return True, "guerra declarada"
    if accion == "paz":
        if not _en_guerra(part, jugador, otro):
            return False, "no estan en guerra"
        _, mia = _resumen_pais(mapa, part, jugador)
        _, suya = _resumen_pais(mapa, part, otro)
        if suya < mia * 1.4 or random.random() < 0.3:
            _hacer_paz(mapa, part, jugador, otro)
            return True, "paz aceptada"
        return False, "rechazan tu oferta de paz"
    return False, "accion desconocida"
