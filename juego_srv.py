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
MANTEN_TROPA = 0.1       # oro por tropa y turno (mantener la milicia se
                         # descuenta del ingreso; un ejercito enorme arruina)
BONO_DEFENSA = 1.2       # ventaja del defensor
PENA_NAVAL = 0.72        # penalizacion al desembarcar / cruzar el mar
HAB_TROPA = 150          # habitantes que consume cada tropa
DINERO_INICIAL = 120
PA_POR_POB = 150000      # habitantes por punto de accion extra (los paises
                         # poblados mueven mas ordenes por turno)

# ---- poblacion inicial (rebalanceo: piso mas alto, picos mas bajos) ----
POB_BASE_PROV = 6000     # habitantes minimos por provincia de tierra
POB_POR_AREA = 45        # habitantes por unidad de area (antes 25)
POB_UMBRAL = 50000       # por debajo, los asentamientos suman lineal; encima,
                         # su aporte crece sublineal (raiz) para no dominar


def _amortigua_asent(s):
    """Aporte de los asentamientos amortiguado: lineal hasta POB_UMBRAL y
    sublineal (crecimiento tipo raiz, pendiente 1 en el umbral) por encima, para
    que las ciudades gigantes (capitales rango 3) no disparen tanto la provincia."""
    if s <= POB_UMBRAL:
        return s
    return POB_UMBRAL + 2 * POB_UMBRAL * (math.sqrt(s / POB_UMBRAL) - 1)

EDIF = {                 # edificios: nombre, icono y coste en oro
    "bastion": {"nombre": "bastion", "icono": "\U0001F6E1", "costo": 45},
    "torre":   {"nombre": "torre",   "icono": "\U0001F441", "costo": 25},
    "puerto":  {"nombre": "puerto",  "icono": "⚓",     "costo": 55},
}
# puntos de accion (separados del oro)
PA_MOV, PA_NAVAL, PA_REC, PA_EDIF = 1, 2, 1, 2
# gestos diplomaticos activos del jugador (piden algo a la IA): cuestan puntos
# de accion y se COBRAN aunque la IA rechace (el esfuerzo diplomatico se gasta
# igual). Asi no se puede spamear ofertas gratis cada turno.
PA_PAZ, PA_TRATADO = 2, 2

# parametros de la IA por dificultad
# ---------------------------------------------------------------------------
# La dificultad NO es solo inflar numeros: cambia COMO juega la IA. Ademas de
# los multiplicadores economicos (eco/gasto) y de umbral de ataque (margen),
# hay banderas de COMPORTAMIENTO que hacen que "dificil" sea un rival real y
# "facil" siga siendo la IA simple (y algo torpe) de siempre:
#
#   eco       multiplicador al ingreso de la IA (unica ayuda de recursos; se
#             mantiene moderada — la ventaja de "dificil" es sobre todo tactica).
#   gasto     fraccion del oro que gasta en reclutar por turno.
#   agresion  probabilidad de declarar la guerra oportunista.
#   margen    ventaja de fuerza exigida para atacar (1.0 = ataca a la par;
#             mayor = mas timida). "facil" es muy conservadora.
#   edif      probabilidad de construir (bastiones/puertos).
#   reclutas  en cuantas provincias distintas puede reclutar por turno (facil
#             solo en 1 -> desperdicia oro; dificil reparte en varias).
#   objetivo  criterio de eleccion de blanco:
#               "debil"  -> el vecino con MENOS tropas (facil: ignora el valor).
#               "mixto"  -> mezcla debilidad y valor.
#               "valor"  -> prioriza CAPITALES y provincias ricas (dificil).
#   concentra concentra el empuje en UNA punta de lanza (recluta y reagrupa
#             reservas en la misma provincia y golpea el blanco valioso) en vez
#             de dispersar ataques debiles por todo el frente (facil dispersa).
#   defiende  refuerza las provincias amenazadas y no las vacia para atacar;
#             fortifica la capital. "facil" no defiende: deja huecos explotables.
#   cazaLider trata al pais que va GANANDO -incluido el JUGADOR- como amenaza
#             prioritaria (peso extra al declararle la guerra y al elegir blanco)
#             en vez de ignorarlo. Solo "dificil".
#   minAtq    tropas minimas para lanzar un ataque (dificil arriesga con menos).
#   pazFacil  probabilidad de pedir la paz cuando va perdiendo claro (dificil es
#             pragmatica y corta perdidas; facil es cabezona y se desangra).
DIFS = {
    "facil":   {"eco": 0.7,  "gasto": 0.45, "agresion": 0.10, "margen": 1.7,
                "edif": 0.12, "reclutas": 1, "objetivo": "debil", "concentra": False,
                "defiende": False, "cazaLider": False, "minAtq": 6, "pazFacil": 0.3},
    "normal":  {"eco": 1.0,  "gasto": 0.8,  "agresion": 0.28, "margen": 1.2,
                "edif": 0.4,  "reclutas": 2, "objetivo": "mixto", "concentra": False,
                "defiende": True,  "cazaLider": False, "minAtq": 5, "pazFacil": 0.5},
    "dificil": {"eco": 1.35, "gasto": 1.0,  "agresion": 0.5,  "margen": 1.0,
                "edif": 0.65, "reclutas": 4, "objetivo": "valor", "concentra": True,
                "defiende": True,  "cazaLider": True,  "minAtq": 4, "pazFacil": 0.7},
}
# ajustes de partida por defecto. "vision" es el modo de niebla de guerra:
#   "total"   -> todo el mapa siempre visible (las torres no aportan nada)
#   "parcial" -> propias + vecinas; puerto ve un salto naval; torre ve a 2 nodos
#   "oculta"  -> minima: propias + frontera terrestre directa (torres inutiles)
AJUSTES_DEF = {"bastion": 50.0, "naval": 7.0, "recup": 0.6, "vision": "parcial"}
VISIONES = ("total", "parcial", "oculta")


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
        pob = (POB_BASE_PROV + jround(p["area"] * POB_POR_AREA)
               + jround(_amortigua_asent(pob0[pid])))
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
        # las capitales nacen con BASTION; las capitales costeras, ademas, con
        # PUERTO (para no quedar encerradas sin poder embarcar de salida)
        entry = {"dueno": p["dueno0"], "pob": p["pob0"],
                 "ejercito": p["ejercito0"], "movida": False, "agotado": 0,
                 "bastion": bool(p["capital"]), "torre": False,
                 "puerto": bool(p["capital"] and p["costera"])}
        if p["mar"]:
            entry["flotas"] = []     # cuencas: lista de flotas coexistiendo
        prov[pid] = entry
    paises = {}
    for p in mapa["paises"]:
        # AGRESIVIDAD por pais: rasgo fijo en [0,1] sorteado al crear la partida.
        # Mide lo belicoso que es cada pais; se combina con las guerras que
        # declara (guerrasDecl) para modular la duracion de los tratados de no
        # agresion (mas agresivo -> tratado mas corto). Ver _agresividad().
        paises[p["id"]] = {"dinero": DINERO_INICIAL, "puntos": 0,
                           "vivo": True, "ia": True,
                           "agresion": round(random.random(), 3),
                           "guerrasDecl": 0}
    paises[NEUTRAL] = {"dinero": 0, "puntos": 0, "vivo": True, "ia": False,
                       "agresion": 0.0, "guerrasDecl": 0}
    part = {
        "sello": sello, "stem": stem, "turno": 1, "jugador": jugador,
        "difKey": dif_key if dif_key in DIFS else "normal",
        "ajustes": dict(ajustes), "fase": "jugando",
        "ganador": None, "resultado": None,
        # guerras: set de pares "a|b"; tratados: {par -> turnos restantes de no
        # agresion} (durante los cuales nadie puede redeclarar la guerra)
        "guerras": set(), "tratados": {}, "paises": paises, "prov": prov,
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
    # tratados de no agresion: partidas viejas no lo traen -> dict vacio
    part["tratados"] = dict(d.get("tratados", {}))
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


def _mantenimiento_pais(mapa, part, pid):
    """Costo por turno de mantener la milicia: MANTEN_TROPA de oro por cada
    tropa del pais (guarniciones y flotas). Se descuenta del ingreso."""
    _, ej = _resumen_pais(mapa, part, pid)
    return jround(ej * MANTEN_TROPA)


def _ingreso_neto(mapa, part, pid):
    """Ingreso menos mantenimiento de la milicia (puede ser negativo: un
    ejercito desmedido come mas oro del que producen las provincias)."""
    return _ingreso_pais(mapa, part, pid) - _mantenimiento_pais(mapa, part, pid)


def _poblacion_pais(mapa, part, pid):
    return sum(p["pob"] for i, p in part["prov"].items()
               if not mapa["prov"][i]["mar"] and p["dueno"] == pid)


def _resumen_pais(mapa, part, pid):
    provs = 0
    ej = 0
    for i, p in part["prov"].items():
        if mapa["prov"][i]["mar"]:
            f = _flota(part, i, pid)      # incluye flotas coexistiendo en paz
            if f:
                ej += f["n"]
        elif p["dueno"] == pid:
            provs += 1
            ej += p["ejercito"]
    return provs, ej


def _puntos_max(mapa, part, pid):
    """Puntos de accion por turno: base + provincias + POBLACION disponible
    (un punto extra por cada PA_POR_POB habitantes), con tope en 30."""
    provs, _ = _resumen_pais(mapa, part, pid)
    extra_pob = _poblacion_pais(mapa, part, pid) // PA_POR_POB
    return min(30, 4 + provs // 2 + int(extra_pob))


def _nombre_pais(mapa, pid):
    if pid == NEUTRAL:
        return "tierras neutrales"
    for p in mapa["paises"]:
        if p["id"] == pid:
            return p["nombre"]
    return "?"


def _agresividad(part, pid):
    """Metrica de agresividad de un pais en [0,1]: su rasgo fijo (sorteado al
    crear la partida) mas un empujon por cada guerra que haya declarado (satura
    en 1). Un pais que declara muchas guerras se vuelve mas belicoso."""
    p = part["paises"].get(pid, {})
    return min(1.0, p.get("agresion", 0.5) + 0.12 * p.get("guerrasDecl", 0))


def _hay_tratado(part, a, b):
    return part.get("tratados", {}).get(_par_guerra(a, b), 0) > 0


def _dur_tratado(part, a, b):
    """Duracion (1..3 turnos) del tratado de no agresion: cuanto mas agresivo
    sea el mas belicoso del par, mas corto el tratado (paz fragil)."""
    agr = max(_agresividad(part, a), _agresividad(part, b))
    return max(1, min(3, jround(3 - 2 * agr)))


# ===================================================================
#  MOVIMIENTO PARCIAL  (la fatiga es POR TROPA, no por provincia)
# ===================================================================
# Cada provincia de tierra guarda `agotado`: cuantas de sus tropas YA actuaron
# este turno (llegaron moviendose, conquistando u ocupando). Las flotas guardan
# lo mismo en f["a"]. Reglas:
#   - solo las tropas FRESCAS (ejercito - agotado) pueden salir; las que llegan
#     a una celda quedan agotadas hasta el proximo turno (asi no hay cadenas de
#     movimientos larguisimos en un solo turno, ni por tierra ni por mar);
#   - reclutar produce tropas frescas: aunque la provincia ya haya actuado,
#     las recien reclutadas SI pueden moverse este mismo turno;
#   - una provincia puede dar VARIAS ordenes por turno (cada una paga sus 🏃)
#     mientras le queden tropas frescas por encima de la guarnicion.
# El campo `movida` se conserva como derivado (compat de guardados y render del
# front: "actuo y no le queda fuerza fresca").
def _disp_tierra(p):
    """Tropas frescas que pueden salir de una provincia de tierra: las no
    agotadas, dejando siempre al menos 1 de guarnicion."""
    return max(0, min(p["ejercito"] - 1,
                      p["ejercito"] - p.get("agotado", 0)))


def _sinc_tierra(p):
    """Tras mutar tropas en tierra, recalcula los derivados: `agotado` nunca
    excede al ejercito y `movida` marca «actuo y sin fuerza fresca»."""
    p["agotado"] = max(0, min(p.get("agotado", 0), p["ejercito"]))
    p["movida"] = p["agotado"] > 0 and _disp_tierra(p) < 1


def _llegar_tierra(p, n):
    """Suma n tropas RECIEN LLEGADAS a una provincia de tierra: entran agotadas
    (ya gastaron su movimiento del turno)."""
    p["ejercito"] += n
    p["agotado"] = p.get("agotado", 0) + n
    _sinc_tierra(p)


def _disp_flota(f):
    return max(0, f["n"] - f.get("a", 0))


def _sinc_flota(f):
    f["a"] = max(0, min(f.get("a", 0), f["n"]))
    f["m"] = f["n"] > 0 and f["a"] >= f["n"]


def _migrar_actuadas(mapa, part):
    """COMPATIBILIDAD: guardados anteriores marcaban `movida` por provincia (y
    f["m"] por flota) sin contador de tropas agotadas. Se sintetiza: si la
    celda ya actuo, TODAS sus tropas quedan agotadas; si no, ninguna."""
    for i, p in part["prov"].items():
        if mapa["prov"][i]["mar"]:
            for f in p.get("flotas", ()):
                if "a" not in f:
                    f["a"] = f["n"] if f.get("m") else 0
        elif "agotado" not in p:
            p["agotado"] = p["ejercito"] if p.get("movida") else 0


# ===================================================================
#  FLOTAS EN EL MAR  (coexistencia de paises EN PAZ en la misma cuenca)
# ===================================================================
# MODELO ELEGIDO: cada cuenca marina guarda una LISTA de flotas que coexisten,
#   prov[pid]["flotas"] = [{"p": pais, "n": tropas, "m": movida}, ...]
# Se eligio la lista (y no un dueno unico "de paso") porque es el unico modo
# robusto de que varias flotas se DETENGAN en la misma agua sin desplazarse: el
# transito puro (mover dos celdas de golpe) rompe el modelo por turnos. Se
# guardan ademas los campos DERIVADOS dueno/ejercito/movida = flota MAYORITARIA,
# para que todos los lectores viejos (resumen, niebla, pintado, pastillas)
# sigan funcionando sin tocarlos: solo la logica de mover/combatir usa "flotas".
#
# REGLAS:
#   (a) entrar a un mar donde solo hay flotas de paises EN PAZ (o el mar libre)
#       NO es hostil: la flota entra y COEXISTE (no hay batalla ni conquista).
#   (b) si dos paises que comparten agua entran en GUERRA, sus flotas chocan en
#       el acto (_resolver_choques_mar, invocado tras _declarar_guerra): la
#       coexistencia solo dura mientras hay paz. Se eligio "combate al declarar"
#       (y no "coexisten hasta que uno ataque") para no inventar un ataque "en
#       la misma celda": asi el combate sigue siendo siempre celda->celda.
#   (c) atacar una flota con la que YA hay guerra funciona como siempre
#       (celda->celda; el defensor es la suma de flotas enemigas de esa agua).
def _flotas(part, pid):
    return part["prov"][pid].setdefault("flotas", [])


def _flota(part, pid, pais):
    for f in _flotas(part, pid):
        if f["p"] == pais:
            return f
    return None


def _flota_pon(part, pid, pais, n, movida):
    """Agrega n tropas del pais a la cuenca pid (crea o refuerza su flota).
    Con movida=True las recien llegadas entran AGOTADAS (f["a"]), pero las que
    ya estaban frescas en la flota siguen pudiendo moverse este turno."""
    f = _flota(part, pid, pais)
    if not f:
        f = {"p": pais, "n": 0, "a": 0, "m": False}
        _flotas(part, pid).append(f)
    f["n"] += int(n)
    if movida:
        f["a"] = f.get("a", 0) + int(n)
    _sinc_flota(f)


def _sinc_mar(part, pid):
    """Recalcula los campos derivados (dueno/ejercito/movida = flota mayoritaria)
    de una cuenca a partir de sus flotas y descarta las vacias."""
    p = part["prov"][pid]
    fl = [f for f in _flotas(part, pid) if f["n"] > 0]
    p["flotas"] = fl
    if not fl:
        p["dueno"] = NEUTRAL
        p["ejercito"] = 0
        p["movida"] = False
        return
    may = max(fl, key=lambda f: f["n"])
    p["dueno"] = may["p"]
    p["ejercito"] = may["n"]
    p["movida"] = may["m"]


def _declarar_guerra(mapa, part, a, b):
    if a == NEUTRAL or b == NEUTRAL or _en_guerra(part, a, b):
        return
    if _hay_tratado(part, a, b):        # tratado de no agresion vigente
        return
    part["guerras"].add(_par_guerra(a, b))
    if a in part["paises"]:
        part["paises"][a]["guerrasDecl"] = part["paises"][a].get("guerrasDecl", 0) + 1
    _anotar(part, f"{_nombre_pais(mapa, a)} declara la guerra a {_nombre_pais(mapa, b)}")
    # regla (b): las flotas que coexistian en paz chocan en el acto
    _resolver_choques_mar(mapa, part, a, b)


def _resolver_choques_mar(mapa, part, a, b):
    """En cada cuenca donde a y b tienen flota, resuelven un choque simetrico
    (ambos con su azar): la mayor rompe a la menor y queda mermada. Se llama al
    estallar la guerra, para que la coexistencia no sobreviva a la paz rota."""
    for i, p in part["prov"].items():
        if not mapa["prov"][i]["mar"]:
            continue
        fa, fb = _flota(part, i, a), _flota(part, i, b)
        if not fa or not fb:
            continue
        fA = fa["n"] * (0.85 + random.random() * 0.3)
        fB = fb["n"] * (0.85 + random.random() * 0.3)
        nom = mapa["prov"][i]["nombre"]
        if fA >= fB:
            fa["n"] = max(1, jround(fa["n"] * (fA - fB) / fA))
            _sinc_flota(fa)
            p["flotas"] = [f for f in _flotas(part, i) if f["p"] != b]
            gan, per = a, b
        else:
            fb["n"] = max(1, jround(fb["n"] * (fB - fA) / fB))
            _sinc_flota(fb)
            p["flotas"] = [f for f in _flotas(part, i) if f["p"] != a]
            gan, per = b, a
        _sinc_mar(part, i)
        _anotar(part, f"choque naval en {nom}: {_nombre_pais(mapa, gan)} "
                      f"rompe la flota de {_nombre_pais(mapa, per)}", i)


def _migrar_mar(mapa, part):
    """COMPATIBILIDAD: las partidas viejas guardaban una cuenca con un unico
    dueno/ejercito. Al cargarlas, se sintetiza su lista de flotas (una sola)."""
    for i, p in part["prov"].items():
        if mapa["prov"][i]["mar"] and "flotas" not in p:
            if p.get("ejercito", 0) > 0 and p.get("dueno", NEUTRAL) != NEUTRAL:
                p["flotas"] = [{"p": p["dueno"], "n": p["ejercito"],
                                "m": bool(p.get("movida"))}]
            else:
                p["flotas"] = []
            _sinc_mar(part, i)


def _hacer_paz(mapa, part, a, b):
    part["guerras"].discard(_par_guerra(a, b))
    dur = _dur_tratado(part, a, b)
    part.setdefault("tratados", {})[_par_guerra(a, b)] = dur
    _anotar(part, f"{_nombre_pais(mapa, a)} y {_nombre_pais(mapa, b)} firman la paz "
                  f"(no agresion: {dur} turno{'s' if dur != 1 else ''})")


def _firmar_tratado(mapa, part, a, b):
    """Tratado de no agresion en frio (sin guerra previa): misma regla de
    duracion 1..3 turnos que la paz (_dur_tratado)."""
    dur = _dur_tratado(part, a, b)
    part.setdefault("tratados", {})[_par_guerra(a, b)] = dur
    _anotar(part, f"{_nombre_pais(mapa, a)} y {_nombre_pais(mapa, b)} firman un "
                  f"tratado de no agresion ({dur} turno{'s' if dur != 1 else ''})")
    return dur


def _normalizar_mar(mapa, part, pid):
    """Tras mutar tropas en una celda de mar, recalcula sus campos derivados."""
    if mapa["prov"][pid]["mar"]:
        _sinc_mar(part, pid)


def _tropas_disponibles(mapa, part, origen, actor):
    """Tropas FRESCAS que `actor` puede sacar de `origen` (las no agotadas de
    su flota en el mar; las no agotadas menos 1 de guarnicion en tierra). El
    actor puede no ser el dueno mayoritario de una cuenca compartida: por eso
    se pasa explicito y no se deduce del dueno."""
    if mapa["prov"][origen]["mar"]:
        f = _flota(part, origen, actor)
        return _disp_flota(f) if f else 0
    return _disp_tierra(part["prov"][origen])


def _quitar_origen(mapa, part, origen, actor, k):
    """Descuenta k tropas FRESCAS de `actor` en `origen`. Las agotadas que ya
    actuaron se quedan: solo la fuerza fresca viaja, asi la misma celda puede
    seguir dando ordenes con lo que le quede fresco (movimiento parcial)."""
    if mapa["prov"][origen]["mar"]:
        f = _flota(part, origen, actor)
        if f:
            f["n"] -= k
            _sinc_flota(f)
        _sinc_mar(part, origen)
    else:
        A = part["prov"][origen]
        A["ejercito"] -= k
        _sinc_tierra(A)


def _mover_a(mapa, part, origen, destino, actor, n):
    """Mueve n tropas de `actor` de origen a destino SIN combate: reforzar
    tierra propia, u ocupar/entrar/coexistir en una cuenca marina sin enemigo.
    La flota entra ENTERA (en el mar no queda guarnicion)."""
    n = min(n, _tropas_disponibles(mapa, part, origen, actor))
    if n < 1:
        return False
    _quitar_origen(mapa, part, origen, actor, n)
    if mapa["prov"][destino]["mar"]:
        _flota_pon(part, destino, actor, n, True)
        _sinc_mar(part, destino)
    else:
        # las tropas llegan AGOTADAS: no pueden encadenar otro movimiento
        _llegar_tierra(part["prov"][destino], n)
    return True


def _atacar(mapa, part, origen, destino, naval, n=None, atacante=None):
    """Resuelve un ataque origen->destino con `n` tropas (por defecto todas menos
    la guarnicion). Azar del SERVIDOR. Devuelve True si conquista/ocupa/hunde.
    `atacante` es el pais que ordena (puede no ser el dueno mayoritario de una
    cuenca compartida); si es None se deduce del dueno del origen (tierra)."""
    A = part["prov"][origen]
    D = part["prov"][destino]
    A_mar = mapa["prov"][origen]["mar"]
    D_mar = mapa["prov"][destino]["mar"]
    if atacante is None:
        atacante = A["dueno"]
    disp = _tropas_disponibles(mapa, part, origen, atacante)
    tropas = min(disp if n is None else n, disp)
    if tropas < 1:
        return False
    nA = _nombre_pais(mapa, atacante)
    nD = mapa["prov"][destino]["nombre"]

    def azar():
        return 0.85 + random.random() * 0.3

    # ---- destino en el MAR: batalla contra la(s) flota(s) ENEMIGAS ----
    if D_mar:
        enemigos = [f for f in _flotas(part, destino)
                    if f["p"] != atacante and _en_guerra(part, atacante, f["p"])]
        defensa = sum(f["n"] for f in enemigos)
        if defensa <= 0:                      # sin enemigo: entrada pacifica
            _quitar_origen(mapa, part, origen, atacante, tropas)
            _flota_pon(part, destino, atacante, tropas, True)
            _sinc_mar(part, destino)
            _anotar(part, f"{nA} entra en {nD}", destino)
            return True
        fA = tropas * azar() * (PENA_NAVAL if naval else 1)
        fD = max(defensa, 0.5) * BONO_DEFENSA * azar()
        _quitar_origen(mapa, part, origen, atacante, tropas)
        if fA > fD:                           # hunde las flotas enemigas
            sobran = max(1, jround(tropas * (fA - fD) / fA))
            part["prov"][destino]["flotas"] = [
                f for f in _flotas(part, destino)
                if not (f["p"] != atacante and _en_guerra(part, atacante, f["p"]))]
            _flota_pon(part, destino, atacante, sobran, True)
            _sinc_mar(part, destino)
            _anotar(part, f"{nA} hunde la flota enemiga en {nD}", destino)
            return True
        for f in enemigos:                    # la flota enemiga resiste, mermada
            f["n"] = max(1, jround(f["n"] * (fD - fA) / fD))
            _sinc_flota(f)
        _sinc_mar(part, destino)
        _anotar(part, f"la flota de {nD} resiste el ataque de {nA}", destino)
        return False

    # ---- destino en TIERRA ----
    defensor = D["dueno"]
    if defensor == NEUTRAL and D["ejercito"] <= 0:    # tierra libre: ocupar
        _quitar_origen(mapa, part, origen, atacante, tropas)
        D["dueno"] = atacante
        D["ejercito"] = tropas
        D["agotado"] = tropas          # las ocupantes ya actuaron este turno
        _sinc_tierra(D)
        _anotar(part, f"{nA} ocupa {nD}", destino)
        return True

    desembarco = naval or (A_mar and not D_mar)
    bono_bastion = 1 + part["ajustes"]["bastion"] / 100
    fA = tropas * azar() * (PENA_NAVAL if desembarco else 1)
    fD = max(D["ejercito"], 0.5) * BONO_DEFENSA * \
        (bono_bastion if D["bastion"] else 1) * azar()
    defensores = D["ejercito"]
    _quitar_origen(mapa, part, origen, atacante, tropas)

    def despoblar(caidos, es_naval):
        factor = (1 - part["ajustes"]["naval"] / 100) if es_naval else 0.97
        D["pob"] = max(100, jround(D["pob"] * factor - caidos * HAB_TROPA / 2))

    if fA > fD:
        sobran = max(1, jround(tropas * (fA - fD) / fA))
        D["dueno"] = atacante
        D["ejercito"] = sobran
        D["agotado"] = sobran          # las conquistadoras ya actuaron
        _sinc_tierra(D)
        D["bastion"] = False
        despoblar((tropas - sobran) + defensores, desembarco)
        _anotar(part, f"{nA} conquista {nD}" + (" (desembarco)" if desembarco else ""), destino)
        _comprobar_muerte(mapa, part, defensor)
        return True
    D["ejercito"] = max(1, jround(D["ejercito"] * (fD - fA) / fD))
    _sinc_tierra(D)
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
        if mapa["prov"][i]["mar"] and _flota(part, i, pid):
            p["flotas"] = [f for f in _flotas(part, i) if f["p"] != pid]
            _sinc_mar(part, i)
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


# ---- IA por pais ----
def _valor_objetivo(mapa, part, v):
    """Cuanto vale CONQUISTAR la provincia v (mayor = mas deseable). Riqueza por
    poblacion + gran bono si es capital; el mar apenas vale (solo transito). La
    IA "dificil" ataca por VALOR (capitales/provincias ricas) en lugar de por
    "el vecino mas debil", que es lo que hace la IA simple."""
    mp = mapa["prov"][v]
    if mp["mar"]:
        return 0.15
    val = 1.0 + part["prov"][v]["pob"] / 30000.0
    if mp["capital"]:
        val += 5.0
    return val


def _amenaza_sobre(mapa, part, pid, i):
    """Mayor guarnicion ENEMIGA (en guerra, o neutral con tropas) que colinda con
    MI provincia i. Mide lo expuesta que esta: la IA que "defiende" refuerza las
    provincias con amenaza alta y no las vacia para atacar en otra parte."""
    vecinos, navales = mapa["vecinos"], mapa["navales"]
    amenaza = 0
    for v in set(vecinos.get(i, ())) | set(navales.get(i, ())):
        o = part["prov"].get(v)
        if not o or o["dueno"] == pid:
            continue
        if o["dueno"] == NEUTRAL and o["ejercito"] <= 0:
            continue
        if o["dueno"] == NEUTRAL or _en_guerra(part, pid, o["dueno"]):
            amenaza = max(amenaza, o["ejercito"])
    return amenaza


def _lider_actual(mapa, part):
    """Pais VIVO con mas provincias (incluido el jugador). La IA con `cazaLider`
    lo trata como amenaza prioritaria en vez de ignorar al que va ganando."""
    lider, mejor = None, 0
    for q in mapa["paises"]:
        if not part["paises"][q["id"]]["vivo"]:
            continue
        pr, _ = _resumen_pais(mapa, part, q["id"])
        if pr > mejor:
            lider, mejor = q["id"], pr
    return lider


def _turno_ia(mapa, part, pid):
    pais = part["paises"][pid]
    if not pais["vivo"]:
        return
    dif = DIFS[part["difKey"]]
    vecinos, navales = mapa["vecinos"], mapa["navales"]

    # tropas/movida PROPIAS de una celda: en tierra la guarnicion; en el mar la
    # flota de ESTE pais (que puede coexistir en paz con otras, sin ser dueno
    # mayoritario de la cuenca). Asi la IA entiende la coexistencia naval.
    def mif(i):
        if mapa["prov"][i]["mar"]:
            f = _flota(part, i, pid)
            return f["n"] if f else 0
        return part["prov"][i]["ejercito"]

    def midisp(i):
        """Tropas FRESCAS que la IA puede sacar de la celda (misma regla de
        movimiento parcial que el jugador)."""
        if mapa["prov"][i]["mar"]:
            f = _flota(part, i, pid)
            return _disp_flota(f) if f else 0
        return _disp_tierra(part["prov"][i])

    # mis celdas: tierra propia + toda cuenca donde tengo flota (aun minoritaria)
    mias = [i for i, p in part["prov"].items()
            if (not mapa["prov"][i]["mar"] and p["dueno"] == pid)
            or (mapa["prov"][i]["mar"] and _flota(part, i, pid))]
    if not mias:
        return
    # ingreso (con la ayuda economica de la dificultad) MENOS el mantenimiento
    # de la milicia; el oro nunca baja de 0 (no hay deuda)
    pais["dinero"] = max(0, pais["dinero"]
                         + jround(_ingreso_pais(mapa, part, pid) * dif["eco"])
                         - _mantenimiento_pais(mapa, part, pid))
    pais["puntos"] = _puntos_max(mapa, part, pid)
    jugador = part["jugador"]

    mi_fuerza = sum(mif(i) for i in mias)
    lider = _lider_actual(mapa, part) if dif["cazaLider"] else None

    # --- diplomacia: pedir la paz si va perdiendo claro (nunca al jugador) ---
    # `pazFacil` diferencia el temple: "dificil" corta perdidas (0.7), "facil"
    # es cabezona (0.3) y se desangra en guerras perdidas.
    for g in list(part["guerras"]):
        a, b = map(int, g.split("|"))
        if a != pid and b != pid:
            continue
        otro = b if a == pid else a
        _, su_fuerza = _resumen_pais(mapa, part, otro)
        if mi_fuerza < su_fuerza * 0.45 and random.random() < dif["pazFacil"] \
                and otro != jugador:
            _hacer_paz(mapa, part, pid, otro)

    # --- mapa del frente: mis provincias de borde y las provincias enemigas
    # que puedo alcanzar desde ellas (objetivos) ---
    fronteras = {}         # enemigo -> [mis provincias de borde con el]
    objetivos_de = {}      # enemigo -> set(SUS provincias que colindan conmigo)
    for i in mias:
        vs = set(vecinos.get(i, ())) | set(navales.get(i, ()))
        for v in vs:
            o = part["prov"].get(v)
            if not o:
                continue
            if mapa["prov"][v]["mar"]:
                # el frente naval son SOLO las flotas enemigas (en guerra);
                # el mar libre o las flotas en paz que coexisten no son objetivo
                en = [f for f in _flotas(part, v)
                      if f["p"] != pid and _en_guerra(part, pid, f["p"])]
                for f in en:
                    fronteras.setdefault(f["p"], []).append(i)
                    objetivos_de.setdefault(f["p"], set()).add(v)
            elif o["dueno"] != pid:
                fronteras.setdefault(o["dueno"], []).append(i)
                objetivos_de.setdefault(o["dueno"], set()).add(v)
    bordes = list({i for lst in fronteras.values() for i in lst})

    # --- declarar guerra ---
    ya_en_guerra = any(pid in map(int, g.split("|")) for g in part["guerras"])
    if not ya_en_guerra and fronteras and random.random() < dif["agresion"]:
        cand = []
        for otro in fronteras:
            if otro == NEUTRAL or _en_guerra(part, pid, otro) \
                    or _hay_tratado(part, pid, otro):        # respeta el tratado
                continue
            _, f = _resumen_pais(mapa, part, otro)
            cand.append((otro, f))
        elegido = None
        if dif["objetivo"] == "valor":
            # el blanco mas RENTABLE-y-batible: valor de sus provincias de
            # frontera / su fuerza; el lider pesa extra (amenaza a neutralizar).
            mejor_sc = 0.0
            for otro, f in cand:
                if f > mi_fuerza * 0.85:      # no se mete con quien no puede
                    continue
                valfr = sum(_valor_objetivo(mapa, part, v)
                            for v in objetivos_de.get(otro, ()))
                sc = valfr / (f + 1.0)
                if otro == lider:
                    sc *= 1.8
                if sc > mejor_sc:
                    mejor_sc, elegido = sc, otro
        else:
            # facil/normal: el vecino claramente mas debil
            tope = 0.6 if dif["objetivo"] == "debil" else 0.72
            mejor_f = None
            for otro, f in cand:
                if f < mi_fuerza * tope and (mejor_f is None or f < mejor_f):
                    mejor_f, elegido = f, otro
        if elegido is not None:
            _declarar_guerra(mapa, part, pid, elegido)

    # --- punta de lanza (solo `concentra`): la provincia enemiga mas valiosa
    # que puedo atacar y MI provincia de borde mas fuerte para golpearla; hacia
    # ahi se reagrupan reservas y refuerzos en lugar de dispersar el esfuerzo ---
    obj_spear = prov_spear = None
    if dif["concentra"]:
        mejor_v = -1.0
        for enemigo, objs in objetivos_de.items():
            if not (enemigo == NEUTRAL or _en_guerra(part, pid, enemigo)):
                continue
            for v in objs:
                if mapa["prov"][v]["mar"]:
                    continue
                val = _valor_objetivo(mapa, part, v)
                if enemigo == lider:
                    val *= 1.5
                tocan = [i for i in mias if not mapa["prov"][i]["mar"]
                         and v in (set(vecinos.get(i, ())) | set(navales.get(i, ())))]
                if tocan and val > mejor_v:
                    mejor_v = val
                    obj_spear = v
                    prov_spear = max(tocan, key=lambda i: part["prov"][i]["ejercito"])

    # --- construir bastion ---
    if bordes and random.random() < dif["edif"] and pais["puntos"] >= PA_EDIF:
        sin_b = [i for i in bordes if not mapa["prov"][i]["mar"]
                 and not part["prov"][i]["bastion"]]
        if sin_b and pais["dinero"] >= EDIF["bastion"]["costo"] + 30:
            if dif["defiende"]:      # fortifica la capital / lo mas amenazado
                donde = max(sin_b, key=lambda i: (
                    mapa["prov"][i]["capital"], _amenaza_sobre(mapa, part, pid, i)))
            else:                    # facil: el borde con menos tropas, sin criterio
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

    # --- reclutar: facil en 1 sola provincia (malgasta oro/PA); normal/dificil
    # reparten en varias, priorizando la punta de lanza y las mas amenazadas ---
    bordes_tierra = [i for i in bordes if not mapa["prov"][i]["mar"]]
    orden_rec = []
    if dif["concentra"] and prov_spear is not None:
        orden_rec.append(prov_spear)
    if dif["defiende"]:
        orden_rec += sorted(bordes_tierra, reverse=True, key=lambda i:
                            _amenaza_sobre(mapa, part, pid, i) - part["prov"][i]["ejercito"])
    elif bordes_tierra:                # facil: solo la mas floja
        orden_rec.append(min(bordes_tierra, key=lambda i: part["prov"][i]["ejercito"]))
    vistos, cola_rec = set(), []
    for i in orden_rec:
        if i not in vistos:
            vistos.add(i)
            cola_rec.append(i)
    cupo = dif["reclutas"]
    for donde in cola_rec:
        if cupo <= 0 or pais["puntos"] < PA_REC:
            break
        gasto = int(pais["dinero"] * dif["gasto"] // COSTO_TROPA)
        if gasto <= 0:
            break
        n = min(gasto, _reclutable(mapa, part, donde))
        if n > 0:
            part["prov"][donde]["ejercito"] += n
            part["prov"][donde]["pob"] -= n * HAB_TROPA
            pais["dinero"] -= n * COSTO_TROPA
            pais["puntos"] -= PA_REC
            cupo -= 1

    # --- reagrupar reservas hacia el frente (o la punta de lanza) ANTES de
    # atacar; con el movimiento parcial las que LLEGAN quedan agotadas (el
    # golpe lo da la fuerza fresca local del borde; el refuerzo pega al
    # siguiente turno) ---
    interior = [i for i in mias if not mapa["prov"][i]["mar"]
                and _disp_tierra(part["prov"][i]) > 5 and i not in bordes]
    borde_set = set(bordes)
    for i in interior:
        if pais["puntos"] < PA_MOV:
            break
        p = part["prov"][i]
        vs = [v for v in vecinos.get(i, set())
              if part["prov"].get(v) and part["prov"][v]["dueno"] == pid]
        if not vs:
            continue
        if dif["concentra"] and prov_spear is not None and prov_spear in vs:
            destino = prov_spear      # alimenta directamente la punta de lanza
        else:
            destino = vs[0]
            for v in vs[1:]:
                if v in borde_set and destino not in borde_set:
                    destino = v
                elif part["prov"][v]["ejercito"] > part["prov"][destino]["ejercito"] \
                        and not (destino in borde_set and v not in borde_set):
                    destino = v
        enviar = _disp_tierra(p)
        p["ejercito"] -= enviar
        _sinc_tierra(p)
        _llegar_tierra(part["prov"][destino], enviar)
        pais["puntos"] -= PA_MOV

    # --- atacar: eleccion de blanco segun `objetivo`; la punta de lanza va a
    # por su objetivo valioso; con `defiende` no se vacia una provincia que
    # esta ella misma amenazada (salvo que ataque justo a esa amenaza) ---
    for i in mias:
        p = part["prov"][i]
        mi = mif(i)
        disp = midisp(i)              # solo la fuerza FRESCA puede atacar
        if disp < dif["minAtq"]:
            continue
        if pais["puntos"] < PA_MOV:
            break
        p_mar = mapa["prov"][i]["mar"]
        es_spear = (i == prov_spear)
        if dif["defiende"] and not es_spear and not p_mar:
            # provincia expuesta: no la dejo hueca para atacar en otro lado
            if _amenaza_sobre(mapa, part, pid, i) >= mi:
                continue
        best = None       # (score, v, naval)

        def mirar(v, naval, _disp=disp, _pmar=p_mar, _spear=es_spear):
            nonlocal best
            o = part["prov"].get(v)
            if not o:
                return
            o_mar = mapa["prov"][v]["mar"]
            # EMBARCAR desde tierra (destino en el mar) exige PUERTO, igual que
            # para el jugador; los saltos navales ya se filtran con `puede_naval`
            if not _pmar and o_mar and not p["puerto"]:
                return
            if o_mar:
                # solo ataco flotas ENEMIGAS (en guerra); nunca las que coexisten
                # en paz ni el mar libre -> asi la IA no rompe la paz por error
                en = [f for f in _flotas(part, v)
                      if f["p"] != pid and _en_guerra(part, pid, f["p"])]
                defval = sum(f["n"] for f in en)
                if defval <= 0:
                    return
                objdueno = max(en, key=lambda f: f["n"])["p"]
                bast = 1
            else:
                if o["dueno"] == pid:
                    return
                if not (o["dueno"] == NEUTRAL or _en_guerra(part, pid, o["dueno"])):
                    return
                defval = o["ejercito"]
                objdueno = o["dueno"]
                bast = (1 + part["ajustes"]["bastion"] / 100) if o["bastion"] else 1
            eff = _disp * (PENA_NAVAL if (naval or (_pmar and not o_mar)) else 1)
            umbral = max(defval, 0.5) * BONO_DEFENSA * bast * dif["margen"]
            if eff <= umbral:
                return
            if dif["objetivo"] == "debil":
                sc = -defval                              # el mas debil
            else:
                sc = _valor_objetivo(mapa, part, v)       # el mas valioso
                if objdueno == lider:
                    sc *= 1.5
                if dif["objetivo"] == "mixto":
                    sc += max(0.0, 3.0 - defval * 0.1)
            if _spear and v == obj_spear:
                sc += 1000.0        # la punta de lanza va a por SU objetivo
            if best is None or sc > best[0]:
                best = (sc, v, naval)

        for v in vecinos.get(i, set()):
            mirar(v, False)
        # los saltos con puerto valen 2 PA; desde el mar el movimiento a otra
        # cuenca es un vecino naval normal (no requiere puerto)
        puede_naval = p_mar or p["puerto"]
        if (best is None or es_spear) and puede_naval and pais["puntos"] >= PA_NAVAL:
            for v in navales.get(i, set()):
                mirar(v, True)
        if best is not None:
            costo = PA_NAVAL if best[2] else PA_MOV
            if pais["puntos"] < costo:
                continue
            pais["puntos"] -= costo
            _atacar(mapa, part, i, best[1], best[2], atacante=pid)


def _fin_de_turno(mapa, part):
    """Cobra el ingreso del jugador, resuelve la IA de todos los paises,
    aplica crecimiento de poblacion y renueva puntos: un turno global."""
    jugador = part["jugador"]
    # ingreso NETO: producir de las provincias menos mantener la milicia
    # (MANTEN_TROPA por tropa); el oro nunca baja de 0
    part["paises"][jugador]["dinero"] = max(
        0, part["paises"][jugador]["dinero"] + _ingreso_neto(mapa, part, jugador))
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
        p["agotado"] = 0                 # todas las tropas amanecen frescas
        for f in p.get("flotas", ()):    # cada flota de la cuenca vuelve a poder actuar
            f["m"] = False
            f["a"] = 0
        p["pob"] = jround(p["pob"] * crec)
    part["turno"] += 1
    # los tratados de no agresion caducan: un turno global menos cada uno
    for k in list(part.get("tratados", {})):
        part["tratados"][k] -= 1
        if part["tratados"][k] <= 0:
            del part["tratados"][k]
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
                           "oro": _ingreso_neto(mapa, part, pid)}
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
    """Provincias que el JUGADOR ve, segun el modo de vision de la partida:
      - "total":   todo el mapa (las torres no aportan; ver front que las
                   deshabilita).
      - "parcial": propias + vecinas terrestres; con PUERTO ve tambien el salto
                   naval; con TORRE ve a DOS nodos en el grafo de movimiento
                   (vecinos terrestres UNION enlaces navales), incluido el mar.
      - "oculta":  minima: propias + su frontera terrestre directa. Sin vista de
                   mar por puerto y las torres NO tienen efecto.
    La cuenca donde el jugador tiene flota siempre es visible (esta ahi)."""
    modo = part.get("ajustes", {}).get("vision", "parcial")
    prov = part["prov"]
    if modo == "total":
        return set(prov.keys())
    vecinos, navales = mapa["vecinos"], mapa["navales"]
    jugador = part["jugador"]
    vis = set()
    for i, p in prov.items():
        # veo toda cuenca donde tengo flota (aunque sea minoritaria y coexista
        # en paz), en cualquier modo: es donde estan mis barcos
        if mapa["prov"][i]["mar"] and _flota(part, i, jugador):
            vis.add(i)
        if p["dueno"] != jugador:
            continue
        vis.add(i)
        # frontera terrestre directa (comun a "parcial" y "oculta")
        for v in vecinos.get(i, set()):
            vis.add(v)
        if modo == "oculta":
            continue
        # "parcial": el puerto asoma un salto naval; la torre llega a 2 nodos
        if p["puerto"]:
            for v in navales.get(i, set()):
                vis.add(v)
        if p["torre"]:
            paso1 = set(vecinos.get(i, set())) | set(navales.get(i, set()))
            for v in paso1:
                vis.add(v)
                for v2 in (set(vecinos.get(v, set())) | set(navales.get(v, set()))):
                    vis.add(v2)
    return vis


# ===================================================================
#  ESTADO VISIBLE  (lo unico que viaja al front)
# ===================================================================
def _resumen_visible(mapa, part, pid, vision, jugador):
    """Provincias TOTALES (el mapa politico es publico), provincias VISIBLES y
    ejercito VISIBLE de un pais desde la niebla del jugador. El ejercito fuera
    de vision NO se cuenta: asi el total real de un rival nunca viaja al front
    (anti-cheat). Para el propio jugador, visible == total."""
    provs = provs_vis = ej_vis = 0
    for i, p in part["prov"].items():
        ve = (pid == jugador) or (i in vision)
        if mapa["prov"][i]["mar"]:
            f = _flota(part, i, pid)
            if f and ve:
                ej_vis += f["n"]
            continue
        if p["dueno"] == pid:
            provs += 1
            if ve:
                provs_vis += 1
                ej_vis += p["ejercito"]
    return provs, provs_vis, ej_vis


def _estado_visible(mapa, part, con_eventos=False):
    jugador = part["jugador"]
    vision = _calc_vision(mapa, part)
    paises = []
    for p in mapa["paises"]:
        pid = p["id"]
        pp = part["paises"][pid]
        provs, provs_vis, ej = _resumen_visible(mapa, part, pid, vision, jugador)
        item = {"id": pid, "nombre": p["nombre"], "rgb": p["rgb"],
                "vivo": pp["vivo"], "provs": provs, "provsVis": provs_vis,
                "ej": ej}
        if pid == jugador:      # solo el jugador ve su oro y puntos
            item["dinero"] = pp["dinero"]
            item["puntos"] = pp["puntos"]
            item["puntosMax"] = _puntos_max(mapa, part, jugador)
            # ingreso NETO (ya con el mantenimiento de la milicia descontado);
            # el desglose viaja aparte para rotular la barra
            item["ingreso"] = _ingreso_neto(mapa, part, jugador)
            item["ingresoBruto"] = _ingreso_pais(mapa, part, jugador)
            item["mantenimiento"] = _mantenimiento_pais(mapa, part, jugador)
        paises.append(item)
    prov = []
    for i, p in part["prov"].items():
        es_mar = mapa["prov"][i]["mar"]
        visible = p["dueno"] == jugador or i in vision
        propia = p["dueno"] == jugador and not es_mar
        # flotas que coexisten en la cuenca (dueno mayoritario + los demas):
        # solo si el jugador ve la celda (niebla de guerra); incluye la movida
        # de cada flota para que el front sepa cual ya actuo este turno
        flotas = None
        if es_mar and visible:
            # `d` = tropas frescas de la flota (movimiento parcial)
            flotas = [{"p": f["p"], "n": f["n"], "m": f["m"],
                       "d": _disp_flota(f)}
                      for f in _flotas(part, i)]
        prov.append({
            "id": i, "dueno": p["dueno"],
            # ni tropas NI poblacion fuera de vision viajan al front (anti-cheat):
            # el mapa politico es publico, sus numeros no
            "pob": p["pob"] if visible else None,
            "ejercito": p["ejercito"] if visible else None,
            # tropas FRESCAS que aun pueden salir (solo provincias propias)
            "disp": _disp_tierra(p) if propia else None,
            "flotas": flotas,
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
        "tratados": dict(part.get("tratados", {})),
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
    precios = {"tropa": COSTO_TROPA, "manten": MANTEN_TROPA,
               "edif": {k: {"nombre": e["nombre"], "icono": e["icono"],
                            "costo": e["costo"]} for k, e in EDIF.items()},
               "pa": {"mov": PA_MOV, "naval": PA_NAVAL,
                      "rec": PA_REC, "edif": PA_EDIF,
                      "paz": PA_PAZ, "tratado": PA_TRATADO},
               # constantes de combate para que el front ESTIME bajas al atacar
               # (aproximado; el servidor sigue resolviendo la batalla real)
               "combate": {"bonoDefensa": BONO_DEFENSA, "penaNaval": PENA_NAVAL,
                           "azarLo": 0.85, "azarHi": 1.15}}
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
            _migrar_mar(mapa, part)      # compat: cuencas sin lista de flotas
            _migrar_actuadas(mapa, part)  # compat: fatiga por provincia -> por tropa
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
        _migrar_mar(mapa, part)          # compat: cuencas sin lista de flotas
        _migrar_actuadas(mapa, part)     # compat: fatiga por provincia -> por tropa
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
    v = aj.get("vision")
    out["vision"] = v if v in VISIONES else "parcial"
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
        D_mar = mapa["prov"][destino]["mar"]
        # tropas propias en el origen: flota del jugador (mar) o guarnicion (tierra)
        # MOVIMIENTO PARCIAL: solo cuenta la fuerza FRESCA (no agotada); una
        # celda que ya actuo puede seguir ordenando con lo que le quede fresco
        # (p. ej. tropas recien reclutadas o que no se enviaron antes)
        if A_mar:
            fa = _flota(part, origen, jugador)
            disp = _disp_flota(fa) if fa else 0
            if disp < 1:
                return False, "sin flota fresca disponible aqui"
        else:
            if A["dueno"] != jugador:
                return False, "origen invalido"
            disp = _disp_tierra(A)
            if disp < 1:
                return False, "sin tropas frescas para mover"
        es_vecino = destino in mapa["vecinos"].get(origen, set())
        es_naval_dest = destino in mapa["navales"].get(origen, set())
        if not es_vecino and not es_naval_dest:
            return False, "destino no alcanzable"
        naval = not es_vecino
        # EMBARCAR (salir de tierra al agua) exige PUERTO en el origen: tanto el
        # salto naval por enlace como entrar a una cuenca marina vecina. El
        # desembarco (mar -> tierra) no lo requiere. Desde el mar, moverse a otra
        # cuenca es un vecino naval normal (ya estas embarcado).
        embarca = not A_mar and (D_mar or naval)
        if embarca and not A["puerto"]:
            return False, "hace falta un puerto para salir al mar"
        costo = PA_NAVAL if naval else PA_MOV
        if yo["puntos"] < costo:
            return False, "sin puntos de accion"
        tropas = datos.get("tropas")
        n = disp if tropas is None else max(1, min(int(tropas), disp))

        # ¿hay flota ENEMIGA (en guerra) en el destino marino? entrar a un mar
        # con solo flotas EN PAZ (o mar libre) es un movimiento, no un ataque
        enemigo_mar = D_mar and any(
            _en_guerra(part, jugador, f["p"]) for f in _flotas(part, destino))
        # atacar a un pais con tratado de no agresion redeclararia la guerra:
        # prohibido mientras dure (no aplica a entrar en paz a un mar compartido)
        if not D_mar and D["dueno"] != jugador and D["dueno"] != NEUTRAL \
                and not _en_guerra(part, jugador, D["dueno"]) \
                and _hay_tratado(part, jugador, D["dueno"]):
            return False, "tratado de no agresion vigente con ese pais"

        yo["puntos"] -= costo
        if D_mar and not enemigo_mar:             # entrar/coexistir/reforzar mar
            _mover_a(mapa, part, origen, destino, jugador, n)
            _anotar(part, f"tu flota entra en {mapa['prov'][destino]['nombre']}",
                    destino)
        elif not D_mar and D["dueno"] == jugador:  # reforzar tierra propia
            _mover_a(mapa, part, origen, destino, jugador, n)
            _anotar(part, f"mueves {n} tropas de {mapa['prov'][origen]['nombre']} "
                          f"a {mapa['prov'][destino]['nombre']}", destino)
        else:                                      # atacar (tierra o flota enemiga)
            if not D_mar and D["dueno"] != NEUTRAL \
                    and not _en_guerra(part, jugador, D["dueno"]):
                _declarar_guerra(mapa, part, jugador, D["dueno"])
            _atacar(mapa, part, origen, destino, naval, n, atacante=jugador)
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
        p["ejercito"] += n          # las reclutas entran FRESCAS: pueden moverse
        _sinc_tierra(p)             # este mismo turno aunque la provincia actuara
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
        _sinc_tierra(p)
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
    yo = part["paises"][jugador]
    if accion == "guerra":
        if _en_guerra(part, jugador, otro):
            return False, "ya estan en guerra"
        if _hay_tratado(part, jugador, otro):
            return False, "hay un tratado de no agresion vigente"
        _declarar_guerra(mapa, part, jugador, otro)
        return True, "guerra declarada"

    # SOLICITAR LA PAZ (solo si hay guerra). Cuesta PA_PAZ, que se COBRA aunque
    # la IA rechace. La IA acepta con probabilidad = 0.15 + 0.6*(1-agresion),
    # y +0.40 si va perdiendo (su fuerza < la mia): pragmatica corta perdidas,
    # los mas agresivos son cabezones. Si acepta, la paz IMPONE un tratado de
    # no agresion forzoso (_hacer_paz -> _dur_tratado, 1..3 turnos).
    if accion == "paz":
        if not _en_guerra(part, jugador, otro):
            return False, "no estan en guerra"
        if yo["puntos"] < PA_PAZ:
            return False, "sin puntos de accion para negociar"
        yo["puntos"] -= PA_PAZ
        _, mia = _resumen_pais(mapa, part, jugador)
        _, suya = _resumen_pais(mapa, part, otro)
        agr = _agresividad(part, otro)
        prob = 0.15 + 0.6 * (1 - agr)
        if suya < mia * 1.1:               # va perdiendo -> mas ganas de paz
            prob += 0.40
        if random.random() < prob:
            _hacer_paz(mapa, part, jugador, otro)
            return True, "paz aceptada"
        _anotar(part, f"{_nombre_pais(mapa, otro)} rechaza la oferta de paz de "
                      f"{_nombre_pais(mapa, jugador)}")
        return False, "rechazan tu oferta de paz"

    # SOLICITAR TRATADO DE NO AGRESION en frio (estando en paz y sin tratado).
    # Cuesta PA_TRATADO, cobrado aunque rechacen. La IA acepta con probabilidad
    # = 0.25 + 0.6*(1-agresion): los mas pacificos aceptan casi siempre, los
    # belicosos rara vez. Al firmar usa la misma duracion 1..3 (_dur_tratado).
    if accion == "tratado":
        if _en_guerra(part, jugador, otro):
            return False, "estan en guerra: pide antes la paz"
        if _hay_tratado(part, jugador, otro):
            return False, "ya hay un tratado de no agresion vigente"
        if yo["puntos"] < PA_TRATADO:
            return False, "sin puntos de accion para negociar"
        yo["puntos"] -= PA_TRATADO
        agr = _agresividad(part, otro)
        prob = 0.25 + 0.6 * (1 - agr)
        if random.random() < prob:
            _firmar_tratado(mapa, part, jugador, otro)
            return True, "tratado firmado"
        _anotar(part, f"{_nombre_pais(mapa, otro)} rechaza el tratado de no "
                      f"agresion de {_nombre_pais(mapa, jugador)}")
        return False, "rechazan el tratado"
    return False, "accion desconocida"
