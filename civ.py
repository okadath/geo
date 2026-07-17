"""civ — capa de civilizacion derivada de la geografia amplificada.

A partir de los MISMOS campos que ya calcula el detallado climatico (elevacion
fina, Koppen, cuencas y rios de la hidrologia fina) genera, de forma puramente
determinista y sin tocar el generador aleatorio de la simulacion:

  - asentamientos humanos : picos de un campo de HABITABILIDAD con separacion
        minima (poblacion segun clima, agua dulce y costa).
  - caminos               : red terrestre de minimo coste entre asentamientos
        (arbol de expansion minima sobre un campo de coste del terreno + algun
        anillo de redundancia).
  - rutas comerciales     : troncales de largo alcance entre las capitales,
        terrestres y MARITIMAS (saltan de continente a continente por el mar).
  - paises                : reparto del suelo entre capitales por Dijkstra
        multi-fuente sobre un coste donde montanas y RIOS son barreras, asi que
        las fronteras caen solas sobre divisorias y cauces (no sobre Koppen).

Todo se calcula sobre una malla de civilizacion reducida (`nc`, <=~200) para que
el A*/Dijkstra en Python puro sea barato; las coordenadas se emiten en CELDAS de
esa malla (quien exporta las escala a pixeles de render). Las polilineas ya
vienen troceadas en los cruces del borde Este-Oeste. Depende solo de numpy.

Geometria ESFERICA (mapa equirrectangular): el eje X (longitud) envuelve y el
eje Y (latitud) termina en los polos — caminos, rutas comerciales, fronteras y
distancias NUNCA cruzan de polo a polo.

Contrato de `campo` (todas (nc,nc), malla esferica):
  tierra(bool), mar(bool), elev(-1..1, 0=costa), alt(0..1), koppen(int16),
  caudal(0..1), rio(bool), cuenca(int).
El `seed` (int) hace reproducible el sembrado y los nombres para un mismo mundo.
"""

import heapq
import numpy as np
from collections import deque

# --- habitabilidad por clase Koppen (id 0..11 de clima.KOPPEN; 255 mar -> 0) ---
# templado humedo/seco arriba; desierto, tundra y hielo casi inhabitables.
_HAB_KOPPEN = np.array([
    0.55,  # 0  Af ecuatorial lluvioso (selva densa, enfermedad)
    0.70,  # 1  Am monzonico
    0.72,  # 2  Aw sabana
    0.06,  # 3  BW desierto
    0.40,  # 4  BS estepa
    1.00,  # 5  Cf templado humedo
    0.80,  # 6  Cw templado seco
    0.62,  # 7  Df continental humedo
    0.42,  # 8  Dw continental seco
    0.25,  # 9  Dc boreal / taiga
    0.08,  # 10 ET tundra
    0.00,  # 11 EF hielo perpetuo
], np.float32)

_SQRT2 = np.float32(np.sqrt(2.0))
_OFF8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1),
         (0, 1), (1, -1), (1, 0), (1, 1))


# ------------------------------- helpers de malla ---------------------------

def _rolly(f, s, axis=0):
    """np.roll SIN envolver en Y (latitud): replica la fila del borde — los
    polos no se tocan. (== tecto.rolly; copiado para no importar tecto.)"""
    g = np.roll(f, s, axis)
    if s == 0:
        return g
    if s > 0:
        g[:s] = f[:1]
    else:
        g[s:] = f[-1:]
    return g


def _dilatar(mask, r):
    """Dilatacion morfologica booleana de `r` pasos con 8-vecindad (X envuelve,
    los polos no): engorda la mascara ~r celdas en todas direcciones."""
    out = mask
    for _ in range(int(r)):
        d = out.copy()
        for di, dj in _OFF8:
            d |= np.roll(_rolly(out, di), dj, 1)
        out = d
    return out


def _dist_esf(i0, j0, i1, j1, ny, nx):
    """Distancia euclidea en la malla esferica: envuelve SOLO en X (longitud);
    en Y (latitud) la distancia es lineal (no hay atajo por los polos)."""
    di = abs(i0 - i1)
    dj = abs(j0 - j1); dj = min(dj, nx - dj)
    return float(np.hypot(di, dj))


def _bfs_continentes(tierra):
    """Etiqueta las componentes conexas de tierra (8-vecindad; X envuelve, los
    polos no) por inundacion. int32 con id de continente en tierra, -1 en mar."""
    ny, nx = tierra.shape
    lab = np.full((ny, nx), -1, np.int32)
    cid = 0
    for i in range(ny):
        for j in range(nx):
            if not tierra[i, j] or lab[i, j] >= 0:
                continue
            pila = deque([(i, j)])
            lab[i, j] = cid
            while pila:
                ci, cj = pila.pop()
                for di, dj in _OFF8:
                    ni = ci + di
                    if ni < 0 or ni >= ny:
                        continue
                    nj = (cj + dj) % nx
                    if tierra[ni, nj] and lab[ni, nj] < 0:
                        lab[ni, nj] = cid
                        pila.append((ni, nj))
            cid += 1
    return lab, cid


def _dist_a_mar(tierra):
    """Distancia (en celdas, 8-vecindad chebyshev) de cada celda de tierra al mar
    mas cercano, por BFS multi-fuente (X envuelve, los polos no). 0 en el mar."""
    ny, nx = tierra.shape
    dist = np.full((ny, nx), np.inf, np.float32)
    cola = deque()
    mar = ~tierra
    ys, xs = np.nonzero(mar)
    for i, j in zip(ys.tolist(), xs.tolist()):
        dist[i, j] = 0.0
        cola.append((i, j))
    while cola:
        ci, cj = cola.popleft()
        d = dist[ci, cj] + 1.0
        for di, dj in _OFF8:
            ni = ci + di
            if ni < 0 or ni >= ny:
                continue
            nj = (cj + dj) % nx
            if d < dist[ni, nj]:
                dist[ni, nj] = d
                cola.append((ni, nj))
    return dist


def _dist_a_agua(rio, mar):
    """Distancia (celdas) al agua dulce o costa mas cercana (rios, lagos y mar)."""
    ny, nx = rio.shape
    dist = np.full((ny, nx), np.inf, np.float32)
    cola = deque()
    fuente = rio | mar
    ys, xs = np.nonzero(fuente)
    for i, j in zip(ys.tolist(), xs.tolist()):
        dist[i, j] = 0.0
        cola.append((i, j))
    while cola:
        ci, cj = cola.popleft()
        d = dist[ci, cj] + 1.0
        for di, dj in _OFF8:
            ni = ci + di
            if ni < 0 or ni >= ny:
                continue
            nj = (cj + dj) % nx
            if d < dist[ni, nj]:
                dist[ni, nj] = d
                cola.append((ni, nj))
    return dist


def _pendiente(elev):
    """Magnitud del gradiente de elevacion (X periodico, Y recortado)."""
    gy = (_rolly(elev, -1) - _rolly(elev, 1)) * 0.5
    gx = (np.roll(elev, -1, 1) - np.roll(elev, 1, 1)) * 0.5
    return np.hypot(gx, gy).astype(np.float32)


# ------------------------------- habitabilidad ------------------------------

def habitabilidad(campo):
    """Campo 0..1 de aptitud para el asentamiento humano. 0 en mar/hielo.
    Combina clima (Koppen), acceso a agua dulce y costa, y castiga la altura y
    la pendiente. Devuelve (H, aux) con aux = campos reutilizables aguas abajo."""
    tierra = campo["tierra"]; mar = campo["mar"]
    ny, nx = tierra.shape
    kop = np.clip(campo["koppen"], 0, 255).astype(np.int32)
    hab_k = np.where(kop < len(_HAB_KOPPEN), _HAB_KOPPEN[np.clip(kop, 0, len(_HAB_KOPPEN) - 1)], 0.0)
    hab_k = hab_k.astype(np.float32)

    d_agua = _dist_a_agua(campo["rio"], mar)
    d_mar = _dist_a_mar(tierra)
    # bono por agua dulce cercana (cae en ~4 celdas) y por caudal del rio local
    agua = np.exp(-d_agua / np.float32(4.0)).astype(np.float32)
    agua = np.clip(agua + np.float32(0.4) * campo["caudal"], 0.0, 1.0)
    # bono costero moderado (puertos): cae en ~5 celdas
    costa = np.exp(-np.clip(d_mar - 1.0, 0.0, None) / np.float32(5.0)).astype(np.float32)
    # castigo por altitud (tierras altas duras) y por pendiente (laderas)
    fac_alt = np.clip(1.0 - np.clip((campo["alt"] - 0.45) / 0.55, 0.0, 1.0) * 0.8, 0.15, 1.0)
    pend = _pendiente(campo["elev"])
    fac_pend = np.clip(1.0 - pend / np.float32(0.18), 0.2, 1.0).astype(np.float32)

    H = (hab_k
         * (np.float32(0.35) + np.float32(0.65) * agua)   # el agua es decisiva
         * (np.float32(0.55) + np.float32(0.45) * (np.float32(0.5) + np.float32(0.5) * costa))
         * fac_alt * fac_pend).astype(np.float32)
    H = np.where(tierra, H, 0.0).astype(np.float32)
    aux = {"agua": agua, "costa": costa, "d_mar": d_mar, "pend": pend}
    return H, aux


# ------------------------------- asentamientos ------------------------------

def sembrar_asentamientos(H, tierra, seed, n_obj, rmin):
    """Elige hasta n_obj celdas como asentamientos: recorre las celdas por
    habitabilidad descendente y acepta una solo si dista >= rmin (X envuelve) de
    toda aceptada. Empuja cada candidata a un maximo local 3x3 para no clavar el
    pueblo en la ladera de al lado del optimo. Determinista."""
    ny, nx = H.shape
    # micro-jitter determinista para desempatar sin tocar el rng global
    rng = np.random.default_rng(seed & 0x7FFFFFFF)
    Hj = H + rng.random(H.shape, dtype=np.float32) * np.float32(1e-4)
    Hj = np.where(tierra & (H > 0.02), Hj, -1.0).astype(np.float32)

    orden = np.argsort(Hj.ravel())[::-1]
    aceptados = []           # (i, j, score)
    ocup = []                # celdas aceptadas para el chequeo de distancia
    rmin2 = rmin * rmin
    for idx in orden.tolist():
        s = Hj.flat[idx]
        if s <= 0.0:
            break
        i, j = divmod(idx, nx)
        libre = True
        for (oi, oj) in ocup:
            di = abs(i - oi)
            dj = abs(j - oj); dj = min(dj, nx - dj)
            if di * di + dj * dj < rmin2:
                libre = False
                break
        if not libre:
            continue
        aceptados.append((i, j, float(H[i, j])))
        ocup.append((i, j))
        if len(aceptados) >= n_obj:
            break
    return aceptados


# ------------------------------- rutas de coste -----------------------------

def _astar(cost, src, dst, ny, nx, cmin):
    """A* 8-vecindad (X envuelve, los polos no) de `src` a `dst` (indices
    planos) sobre `cost`
    (celda infranqueable = inf). Coste de un paso = media de los costes de las dos
    celdas x longitud (1 o sqrt2). Heuristica = dist esferica x cmin (admisible).
    Devuelve la lista de indices planos del camino (incl. extremos) o None."""
    N = ny * nx
    g = np.full(N, np.inf, np.float32)
    prev = np.full(N, -1, np.int64)
    visto = np.zeros(N, bool)
    si, sj = divmod(src, nx); di_, dj_ = divmod(dst, nx)
    g[src] = 0.0
    heap = [(0.0, src)]
    while heap:
        _, u = heapq.heappop(heap)
        if visto[u]:
            continue
        visto[u] = True
        if u == dst:
            break
        ci, cj = divmod(u, nx)
        cu = cost[ci, cj]
        for di, dj in _OFF8:
            ni = ci + di
            if ni < 0 or ni >= ny:
                continue
            nj = (cj + dj) % nx
            cn = cost[ni, nj]
            if not np.isfinite(cn):
                continue
            v = ni * nx + nj
            if visto[v]:
                continue
            paso = _SQRT2 if (di and dj) else np.float32(1.0)
            ng = g[u] + 0.5 * (cu + cn) * paso
            if ng < g[v]:
                g[v] = ng
                prev[v] = u
                # heuristica al destino (X envuelve)
                hi = abs(ni - di_)
                hj = abs(nj - dj_); hj = min(hj, nx - hj)
                h = np.hypot(hi, hj) * cmin
                heapq.heappush(heap, (ng + h, v))
    if not visto[dst]:
        return None
    camino = []
    u = dst
    while u != -1:
        camino.append(int(u))
        u = int(prev[u])
    camino.reverse()
    return camino


def _dijkstra_multi(cost, fuentes, ny, nx):
    """Dijkstra multi-fuente (X envuelve, los polos no): cada celda queda
    asignada a la fuente mas
    barata. Devuelve (asig int32 con el indice de fuente, -1 inalcanzable; g
    float32 con el coste acumulado hasta su fuente, inf donde no llega). El
    mar (cost inf) queda en -1. Una sola pasada -> barato."""
    N = ny * nx
    g = np.full(N, np.inf, np.float32)
    asig = np.full(N, -1, np.int32)
    visto = np.zeros(N, bool)
    heap = []
    for k, (fi, fj) in enumerate(fuentes):
        s = fi * nx + fj
        g[s] = 0.0
        asig[s] = k
        heap.append((0.0, s))
    heapq.heapify(heap)
    while heap:
        d, u = heapq.heappop(heap)
        if visto[u]:
            continue
        visto[u] = True
        ci, cj = divmod(u, nx)
        cu = cost[ci, cj]
        ku = asig[u]
        for di, dj in _OFF8:
            ni = ci + di
            if ni < 0 or ni >= ny:
                continue
            nj = (cj + dj) % nx
            cn = cost[ni, nj]
            if not np.isfinite(cn):
                continue
            v = ni * nx + nj
            if visto[v]:
                continue
            paso = _SQRT2 if (di and dj) else np.float32(1.0)
            ng = d + 0.5 * (cu + cn) * paso
            if ng < g[v]:
                g[v] = ng
                asig[v] = ku
                heapq.heappush(heap, (ng, v))
    return asig.reshape(ny, nx), g.reshape(ny, nx)


def _kruskal(n, aristas):
    """Arbol de expansion minima (Kruskal + union-find) sobre `n` nodos y aristas
    (peso, a, b). Devuelve el subconjunto de aristas del arbol."""
    padre = list(range(n))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    arbol = []
    for w, a, b in sorted(aristas):
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[ra] = rb
            arbol.append((w, a, b))
    return arbol


# ------------------------------- nomenclatura -------------------------------

_ONSET = ["", "b", "d", "g", "k", "l", "m", "n", "r", "s", "t", "v", "z",
          "br", "dr", "gr", "kr", "tr", "th", "kh", "sh", "st", "mor", "val"]
_NUCLEO = ["a", "e", "i", "o", "u", "ae", "ei", "ia", "au", "or", "an", "en"]
_CODA = ["", "", "n", "r", "s", "l", "th", "sk", "rn", "ndor", "gar", "mos"]


def _nombre(rng, sufijos=None):
    """Un topónimo procedural (2-3 silabas). rng local -> determinista."""
    nsil = int(rng.integers(2, 4))
    s = ""
    for k in range(nsil):
        s += _ONSET[int(rng.integers(len(_ONSET)))]
        s += _NUCLEO[int(rng.integers(len(_NUCLEO)))]
        if k == nsil - 1:
            s += _CODA[int(rng.integers(len(_CODA)))]
    s = s[:1].upper() + s[1:]
    if sufijos and rng.random() < 0.5:
        s += sufijos[int(rng.integers(len(sufijos)))]
    return s


_PREF_PAIS = ["Reino de", "República de", "Imperio de", "Confederación de",
              "Ducado de", "Estados de", "Dominio de", "Liga de"]

_TIPO_PROV = ["Provincia de", "Condado de", "Marca de", "Comarca de",
              "Prefectura de", "Cantón de"]
_PREF_MAR = ["Mar de", "Golfo de", "Cuenca de", "Bahía de", "Fosa de",
             "Estrecho de"]


# ------------------------------- subregiones --------------------------------

def _rellenar_huecos(asig, mask):
    """BFS multi-fuente: propaga los ids ya asignados de `asig` hacia las celdas
    de `mask` que quedaron en -1 (8-vecindad; X envuelve). Modifica asig in place.
    Las componentes de mask sin ninguna celda asignada quedan en -1."""
    ny, nx = asig.shape
    cola = deque()
    ys, xs = np.nonzero(mask & (asig >= 0))
    for i, j in zip(ys.tolist(), xs.tolist()):
        cola.append((i, j))
    while cola:
        ci, cj = cola.popleft()
        v = asig[ci, cj]
        for di, dj in _OFF8:
            ni = ci + di
            if ni < 0 or ni >= ny:
                continue
            nj = (cj + dj) % nx
            if mask[ni, nj] and asig[ni, nj] < 0:
                asig[ni, nj] = v
                cola.append((ni, nj))


def _provincias(idmap, costo_f, asent, rng):
    """Subregiones administrativas de cada pais: Dijkstra multi-fuente desde los
    asentamientos del pais, ACOTADO a las celdas del pais (una provincia nunca
    cruza una frontera nacional). Cada asentamiento siembra su provincia, asi
    que las provincias heredan la logica de los paises: fronteras interiores
    sobre rios y divisorias (mismo costo_f). Devuelve (submap int32, lista)."""
    ny, nx = idmap.shape
    sub = np.full((ny, nx), -1, np.int32)
    lista = []
    por_pais = {}
    for k, a in enumerate(asent):
        if a.get("pais", -1) >= 0:
            por_pais.setdefault(a["pais"], []).append(k)
    for p in sorted(por_pais):
        ks = por_pais[p]
        mask = idmap == p
        cost_p = np.where(mask, costo_f, np.inf).astype(np.float32)
        fuentes = [(asent[k]["i"], asent[k]["j"]) for k in ks]
        asig, _ = _dijkstra_multi(cost_p, fuentes, ny, nx)
        asig = np.where(mask, asig, -1).astype(np.int32)
        # celdas del pais que el Dijkstra no alcanzo (enclaves tras barreras
        # infranqueables): se pegan a la provincia asignada mas cercana
        _rellenar_huecos(asig, mask)
        for loc, k in enumerate(ks):
            celdas = asig == loc
            area = int(np.count_nonzero(celdas))
            if area == 0:
                continue
            sid = len(lista)
            sub[celdas] = sid
            tipo = _TIPO_PROV[int(rng.integers(len(_TIPO_PROV)))]
            lista.append({"id": sid, "pais": int(p), "asent": int(k),
                          "area": area,
                          "nombre": f"{tipo} {asent[k]['nombre']}"})
    return sub, lista


def _islas_vacias(tierra, cont, n_cont, submap, costo_f, seed, lista_prov):
    """Subregiones para las islas VACIAS: los continentes que quedaron sin
    ninguna provincia (islas sin asentamientos) tambien son territorio con
    nombre. Las islas separadas solo por un brazo de mar angosto se agrupan en
    un ARCHIPIELAGO; cada grupo con area suficiente se convierte en una o
    varias subregiones propias (pais -1 = tierra neutral). Modifica `submap`
    in place y anexa a `lista_prov`."""
    ny, nx = tierra.shape
    if n_cont == 0:
        return
    # tierra SIN provincia: no solo las islas enteramente vacias, tambien la
    # PARTE LIBRE de una isla que un pais alcanzo solo parcialmente (con
    # tam_paises=2 quedan tierras sin reclamar). El criterio ya no es "el
    # continente tiene alguna provincia" (que excluia la isla entera) sino "esta
    # celda no tiene provincia": asi la zona libre tambien recibe nombre. Las
    # celdas ya provinciadas quedan fuera y no se pisan.
    vacia = tierra & (cont >= 0) & (submap < 0)
    if not vacia.any():
        return
    # umbral de area minima aplicado a cada ZONA LIBRE CONEXA (no al continente
    # ni al archipielago): un islote suelto O un retazo libre al borde de una
    # provincia por debajo del umbral se deja SIN region (submap = -1, como antes
    # de existir esta funcion) -- ese es justo el caso "sliver" que hay que
    # evitar. Umbral ~ nx/24 celdas de area, con piso de 6 (a 200 celdas de
    # ancho = 8 celdas, ~3x3): a esa escala una celda son cientos de km, asi que
    # <8 celdas es ruido de malla, no una isla ni una comarca real.
    area_min = max(6, int(round(nx / 24.0)))
    piezas, npz = _bfs_continentes(vacia)
    if npz:
        areas_pz = np.bincount(piezas[vacia], minlength=npz)
        chica = areas_pz < area_min
        if chica.any():
            vacia &= ~chica[np.maximum(piezas, 0)]
            if not vacia.any():
                return
    # agrupar islas cercanas (mar de por medio <= ~4 celdas) en archipielagos
    glab, ng = _bfs_continentes(_dilatar(vacia, 2))
    rng = np.random.default_rng((seed & 0x7FFFFFFF) ^ 0x151A)
    for g in range(ng):
        celdas_g = vacia & (glab == g)
        area = int(np.count_nonzero(celdas_g))
        if area == 0:
            continue
        # islas FISICAS del grupo: el brazo de mar (hasta ~4 celdas) las separa
        # y el Dijkstra tiene coste inf fuera de celdas_g, asi que NO cruza el
        # agua. Sin una semilla dentro de cada isla, las islas del archipielago
        # que no reciben semilla quedaban sin id (celdas huerfanas, islas
        # grandes "no detectadas"). Sembramos una semilla por isla y ampliamos
        # con muestreo del punto mas lejano hasta n_sub.
        comp_g, ncg = _bfs_continentes(celdas_g)
        n_islas = ncg
        n_sub = max(ncg, int(np.clip(area // 45, 1, 4)))
        ys, xs = np.nonzero(celdas_g)
        pts = list(zip(ys.tolist(), xs.tolist()))
        fs = []
        for c in range(ncg):
            yy, xx = np.nonzero(comp_g == c)
            fs.append((int(yy[0]), int(xx[0])))
        while len(fs) < n_sub:
            fs.append(max(pts, key=lambda p: min(
                _dist_esf(p[0], p[1], q[0], q[1], ny, nx) for q in fs)))
        cost_g = np.where(celdas_g, costo_f, np.inf).astype(np.float32)
        asig, _ = _dijkstra_multi(cost_g, fs, ny, nx)
        asig = np.where(celdas_g, asig, -1).astype(np.int32)
        _rellenar_huecos(asig, celdas_g)
        partes = [loc for loc in range(len(fs))
                  if bool(np.any(asig == loc))]
        for loc in partes:
            m = asig == loc
            sid = len(lista_prov)
            if n_islas > 1:
                pref = "Archipiélago de" if len(partes) == 1 else "Islas"
            else:
                pref = "Isla de" if len(partes) == 1 else "Tierras de"
            # tonos tierra (ocre-verdoso) bien espaciados, ajenos a los paises
            h = 0.09 + 0.08 * ((sid * 0.61803398875) % 1.0)
            lista_prov.append({"id": sid, "pais": -1, "asent": -1,
                               "area": int(np.count_nonzero(m)),
                               "nombre": f"{pref} {_nombre(rng, None)}",
                               "rgb": _hsv(h, 0.42, 0.78)})
            submap[m] = sid


_PREF_OCEANO = ["Mar de", "Cuenca de", "Fosa de"]


def _cuencas_marinas(mar, elev, seed, n_obj=0):
    """Regiones del mar en dos familias.

    MARES CERRADOS: la costa se "cierra" engordando la tierra unas celdas, de
    modo que los estrechos angostos (tipo Gibraltar o Bosforo) quedan sellados
    por los pequenos segmentos costeros que casi se tocan; cada bolsa de mar
    que asi se separa del oceano abierto es un mar con nombre propio
    (Mediterraneo, Negro, Caribe) y NUNCA se mezcla con aguas de afuera. Las
    celdas de la franja costera y del propio estrecho se reparten despues por
    cercania POR MAR, con lo que el limite del mar cerrado cae exactamente en
    el estrecho que lo cierra.

    OCEANO ABIERTO: cada bolsa grande se subdivide en cuencas por Dijkstra
    multi-fuente sembrado en los fondos mas profundos, con un coste casi plano
    en mar abierto (fronteras suaves, casi Voronoi) que solo se encarece cerca
    de tierra o sobre dorsales someras. El numero de cuencas crece con la
    fraccion de mar y con la fragmentacion costera (mares salpicados de islas
    -> cuencas mas chicas y numerosas).

    AGUAS COSTERAS: las islas chicas reciben, en la medida de lo posible, un
    cinturon de mar propio a su alrededor (las islas cercanas comparten uno,
    como archipielago); solo se talla sobre oceano abierto, nunca dentro de un
    mar cerrado.

    Los charcos aislados sin nucleo (lagos, mares interiores diminutos) son
    una region cada uno. Devuelve (marmap int32, lista)."""
    ny, nx = mar.shape
    marmap = np.full((ny, nx), -1, np.int32)
    mar_total = int(mar.sum())
    if mar_total == 0:
        return marmap, []
    tierra = ~mar

    # ---- 1. cierre costero: tapon de tierra engordada y bolsas de mar ----
    rcierre = max(2, int(round(nx / 64.0)))
    tapon = _dilatar(tierra, rcierre)
    nucleo = mar & ~tapon                     # mar lejos de la costa engordada
    lab, ncomp = _bfs_continentes(nucleo)     # cada bolsa = oceano o mar cerrado
    comp = np.where(nucleo, lab, -1).astype(np.int32)
    _rellenar_huecos(comp, mar)               # franja costera/estrechos por cercania

    # ---- 2. campos para sembrar y costear el oceano abierto ----
    prof = np.where(mar, np.clip(-elev, 0.0, 1.0), 0.0).astype(np.float32)
    somero = np.where(mar, np.clip(1.0 + elev, 0.0, 1.0), 1.0).astype(np.float32)
    s = prof; ss = somero
    for _ in range(2):                        # blur 3x3 x2 (X envuelve, polos no)
        acc = np.zeros_like(s); acs = np.zeros_like(ss)
        for di, dj in ((0, 0),) + _OFF8:
            acc += np.roll(_rolly(s, di), dj, 1)
            acs += np.roll(_rolly(ss, di), dj, 1)
        s = acc / 9.0; ss = acs / 9.0
    # distancia de cada celda de mar a la tierra mas cercana (reutiliza
    # _dist_a_mar con el sentido invertido; X envuelve, los polos no)
    d_tierra = _dist_a_mar(mar)
    cerca = np.exp(-d_tierra / np.float32(6.0)).astype(np.float32)
    # coste plano (0.25) en mar abierto; lo somero y la cercania a costa solo
    # pesan junto a tierra -> fronteras casi rectas lejos de toda costa y
    # pegadas a umbrales/estrechos cerca de ella
    costo = (np.float32(0.25)
             + (np.float32(1.0) + np.float32(5.0) * cerca) * ss * ss
             + np.float32(1.2) * cerca).astype(np.float32)

    rng = np.random.default_rng((seed & 0x7FFFFFFF) ^ 0xA9E1)
    sj = np.where(mar, s + rng.random(s.shape, dtype=np.float32) * 1e-4, -1.0)

    mar_frac = mar_total / float(ny * nx)
    # fragmentacion costera: fraccion del mar que es litoral inmediato
    # (perimetro/area). Mares muy salpicados de islas dan un valor alto; un
    # oceano abierto y compacto, bajo. Mas fragmentacion -> mas cuencas.
    frag = float(np.count_nonzero(mar & (d_tierra <= 1.5))) / max(float(mar_total), 1.0)
    if n_obj > 0:
        n_total = int(np.clip(n_obj, 2, 64))
    else:
        tope = int(np.clip(round(30.0 + 34.0 * frag), 30, 64))
        n_total = int(np.clip(round(mar_frac * 40.0 * (1.0 + 1.8 * frag)), 4, tope))
    # una bolsa mas chica que esto no se subdivide: es UN mar cerrado
    umbral_oceano = max(40.0, 0.12 * mar_total)

    def siembra(mask_c, n, rmin):
        """Semillas en los fondos mas profundos de la bolsa, bien separadas."""
        cand = np.where(mask_c, sj, -1.0)
        orden = np.argsort(cand.ravel())[::-1]
        fs = []
        for idx in orden.tolist():
            if cand.flat[idx] <= 0.0:
                break
            i, j = divmod(idx, nx)
            if all(_dist_esf(i, j, oi, oj, ny, nx) >= rmin for oi, oj in fs):
                fs.append((i, j))
            if len(fs) >= n:
                break
        return fs

    tipos = []                                 # tipo de cada id emitido
    areas_comp = np.bincount(comp[comp >= 0], minlength=max(ncomp, 1))

    # ---- 2b. aguas costeras: cinturon de mar alrededor de las islas ----
    # las masas de tierra chicas reciben una franja de mar propia; las islas
    # separadas por un brazo angosto comparten cinturon (archipielago). Solo
    # se talla sobre bolsas de oceano abierto: un mar cerrado no se fragmenta.
    labt, nlabt = _bfs_continentes(tierra)
    if nlabt > 0:
        areas_t = np.bincount(labt[tierra], minlength=nlabt)
        umbral_isla = max(4.0, 0.05 * float(tierra.sum()))
        chica = areas_t <= umbral_isla
        isla = tierra & chica[np.maximum(labt, 0)]
        if isla.any():
            abierta = areas_comp.astype(np.float32) >= umbral_oceano
            glab, ng = _bfs_continentes(_dilatar(isla, 2))
            for g in range(ng):
                cint = _dilatar(isla & (glab == g), rcierre) & mar
                cint &= (comp >= 0) & abierta[np.maximum(comp, 0)]
                cint &= marmap < 0            # sin pisar cinturones previos
                area_cint = int(np.count_nonzero(cint))
                if area_cint < 3:
                    continue
                # el cinturon NO se deja como un solo anillo: se divide en 2-4
                # secciones de costa. k crece con el area del cinturon; los
                # cinturones minusculos (<6 celdas) quedan enteros.
                k = 1 if area_cint < 6 else int(np.clip(area_cint // 40, 2, 4))
                if k <= 1:
                    marmap[cint] = len(tipos)
                    tipos.append("costero")
                    continue
                # k semillas bien separadas dentro del cinturon por muestreo
                # del punto mas lejano (distancia esferica que envuelve en X);
                # determinista al partir del primer pixel del cinturon.
                ys, xs = np.nonzero(cint)
                pts = list(zip(ys.tolist(), xs.tolist()))
                fs = [pts[0]]
                while len(fs) < k:
                    fs.append(max(pts, key=lambda p: min(
                        _dist_esf(p[0], p[1], q[0], q[1], ny, nx) for q in fs)))
                # reparto por Dijkstra multi-fuente ACOTADO al cinturon (coste
                # inf fuera): cada seccion queda como un arco contiguo del
                # anillo, repartido alrededor del grupo/archipielago.
                cost_c = np.where(cint, costo, np.inf).astype(np.float32)
                asig, _ = _dijkstra_multi(cost_c, fs, ny, nx)
                asig = np.where(cint, asig, -1).astype(np.int32)
                _rellenar_huecos(asig, cint)
                for loc in range(len(fs)):
                    celdas = asig == loc
                    if not celdas.any():
                        continue
                    marmap[celdas] = len(tipos)
                    tipos.append("costero")

    for c in np.argsort(areas_comp)[::-1].tolist():
        mask_c = (comp == c) & (marmap < 0)   # lo que no se llevo un cinturon
        area_c = int(np.count_nonzero(mask_c))
        if area_c == 0:
            continue
        fs = []
        if area_c >= umbral_oceano:
            n_bas = max(1, int(round(n_total * area_c / float(mar_total))))
            if n_bas > 1:
                fs = siembra(mask_c, n_bas,
                             max(4.0, 0.8 * np.sqrt(area_c / float(n_bas))))
        if len(fs) >= 2:
            cost_c = np.where(mask_c, costo, np.inf).astype(np.float32)
            asig, _ = _dijkstra_multi(cost_c, fs, ny, nx)
            asig = np.where(mask_c, asig, -1).astype(np.int32)
            _rellenar_huecos(asig, mask_c)
            for loc in range(len(fs)):
                celdas = asig == loc
                if not celdas.any():
                    continue
                marmap[celdas] = len(tipos)
                tipos.append("abierto")
        else:
            marmap[mask_c] = len(tipos)
            tipos.append("cerrado")

    # ---- 3. charcos sin nucleo (aislados bajo el tapon): region propia ----
    resto = mar & (marmap < 0)
    if resto.any():
        ys, xs = np.nonzero(resto)
        for i, j in zip(ys.tolist(), xs.tolist()):
            if marmap[i, j] >= 0:
                continue
            pila = deque([(i, j)])
            marmap[i, j] = len(tipos)
            while pila:
                ci, cj = pila.pop()
                for di, dj in _OFF8:
                    ni = ci + di
                    if ni < 0 or ni >= ny:
                        continue
                    nj = (cj + dj) % nx
                    if resto[ni, nj] and marmap[ni, nj] < 0:
                        marmap[ni, nj] = marmap[i, j]
                        pila.append((ni, nj))
            tipos.append("interior")

    # ---- 4. nombres y colores ----
    lista = []
    for k, tipo in enumerate(tipos):
        area = int(np.count_nonzero(marmap == k))
        if area == 0:
            continue
        rr = np.random.default_rng(((seed & 0xFFFF) << 10) ^ (0xB0CA + k * 40503))
        if tipo == "abierto":
            pref = "Océano" if area >= 0.25 * mar_total else \
                _PREF_OCEANO[int(rr.integers(len(_PREF_OCEANO)))]
        elif tipo == "cerrado":
            pref = "Mar de" if area >= 25 else \
                ("Golfo de" if area >= 8 else "Bahía de")
        elif tipo == "costero":
            pref = "Aguas de" if area >= 8 else "Bajíos de"
        else:
            pref = "Lago" if area < 8 else "Mar interior de"
        # tonos frios bien espaciados alrededor del azul-cian
        h = 0.50 + 0.13 * (((k * 0.61803398875) % 1.0) - 0.5)
        lista.append({"id": k, "nombre": f"{pref} {_nombre(rr, None)}",
                      "area": area, "rgb": _hsv(h, 0.50, 0.85)})
    lista.sort(key=lambda r: -r["area"])      # las cuencas grandes primero
    return marmap, lista


# ------------------------------- orquestacion -------------------------------

def generar(campo, seed, n_asent=0, n_paises=0, tam_paises=0):
    """Genera la capa de civilizacion. Devuelve un dict con:
      asentamientos: [{i,j,rango,poblacion,nombre,costa,rio,pais,continente}]
      caminos:       [{puntos:[[j,i],...], clase}]   (0 camino, 1 troncal)
      rutas:         [{puntos, mar(bool), a, b}]      (comerciales)
      paises:        {"lista":[{id,nombre,capital,rgb,area,poblacion}],
                      "idmap": 2d int, "tierra_total": celdas de tierra}
    Coordenadas en CELDAS de la malla de civilizacion (x=columna j, y=fila i).
    n_asent / n_paises: objetivos pedidos por el usuario (0 = automatico segun
    la fraccion de tierra); se acotan a lo que la geografia permita.
    tam_paises: 0 automatico, 1 GRANDES (imperios: se reparten todo el suelo),
    2 CHICOS (reinos: cada pais solo reclama el territorio barato de alcanzar
    desde su capital y quedan tierras libres entre medio)."""
    tierra = campo["tierra"]; mar = campo["mar"]
    ny, nx = tierra.shape
    rng = np.random.default_rng((seed & 0x7FFFFFFF) ^ 0x5EED)

    H, aux = habitabilidad(campo)
    cont, n_cont = _bfs_continentes(tierra)

    # ---- 1. asentamientos ----
    tierra_frac = float(tierra.sum()) / float(ny * nx)
    if n_asent > 0:
        n_obj = int(np.clip(n_asent, 2, 200))
    else:
        n_obj = int(np.clip(round(tierra_frac * 130.0), 6, 80))
    rmin = max(3.0, nx / 26.0)
    # si el usuario pide mas asentamientos, la separacion minima cede para que
    # quepan (con un piso: dos asentamientos nunca comparten celda vecina)
    if n_asent > 0:
        area_por = tierra_frac * ny * nx / max(1, n_obj)
        rmin = float(min(rmin, max(2.0, 0.7 * np.sqrt(area_por))))
    sitios = sembrar_asentamientos(H, tierra, seed, n_obj, rmin)
    if not sitios:
        # sin asentamientos no hay paises, pero las islas/masas de tierra
        # siguen mereciendo subregion (coste plano: solo importa la forma)
        submap0 = np.full((ny, nx), -1, np.int32)
        lista_t0 = []
        costo0 = np.where(tierra, np.float32(1.0), np.inf).astype(np.float32)
        _islas_vacias(tierra, cont, n_cont, submap0, costo0, seed, lista_t0)
        marmap0, lista_m0 = _cuencas_marinas(mar, campo["elev"], seed)
        return {"asentamientos": [], "caminos": [], "rutas": [],
                "paises": {"lista": [], "idmap": np.full((ny, nx), -1, np.int32),
                           "tierra_total": int(np.count_nonzero(tierra))},
                "subregiones": {
                    "tierra": {"lista": lista_t0, "idmap": submap0},
                    "mar": {"lista": lista_m0, "idmap": marmap0}}}

    asent = []
    for k, (i, j, score) in enumerate(sitios):
        asent.append({
            "i": int(i), "j": int(j), "score": float(score),
            "costa": bool(aux["d_mar"][i, j] <= 2.5),
            "rio": bool(campo["rio"][i, j] or campo["caudal"][i, j] > 0.15),
            "continente": int(cont[i, j]),
        })

    # rango por percentil de score: 0 aldea, 1 pueblo, 2 ciudad (capitales aparte)
    scores = np.array([a["score"] for a in asent])
    u2 = np.quantile(scores, 0.80); u1 = np.quantile(scores, 0.45)
    for a in asent:
        a["rango"] = 2 if a["score"] >= u2 else (1 if a["score"] >= u1 else 0)
        # poblacion orientativa: ~10^2.4 aldea .. ~10^5.5 ciudad; costa da +60 %
        base = 2.4 + 3.1 * (a["score"] - scores.min()) / (np.ptp(scores) + 1e-9)
        a["poblacion"] = int(round((10 ** base) * (1.6 if a["costa"] else 1.0)))

    # ---- 2. capitales: ciudades mayores bien separadas -> semilla de paises ----
    if n_paises > 0:
        n_cap = int(np.clip(n_paises, 1, min(48, len(asent))))
    else:
        n_cap = int(np.clip(round(len(asent) / 7.0), 2, 10))
        # el tamano elegido tuerce el automatico: grandes -> menos paises,
        # chicos -> mas paises (siempre acotado por los asentamientos que hay)
        if tam_paises == 1:
            n_cap = max(2, n_cap // 2)
        elif tam_paises == 2:
            n_cap = int(min(min(48, len(asent)), n_cap * 2))
    orden_sc = sorted(range(len(asent)), key=lambda k: -asent[k]["score"])
    caps = []
    # la separacion cede a la mitad en cada pasada hasta cubrir el objetivo
    # (si el usuario pide mas paises de los que caben bien repartidos)
    rcap = nx / 5.5
    while len(caps) < n_cap and rcap >= 2.0:
        for k in orden_sc:
            if k in caps:
                continue
            i, j = asent[k]["i"], asent[k]["j"]
            ok = True
            for c in caps:
                di = abs(i - asent[c]["i"])
                dj = abs(j - asent[c]["j"]); dj = min(dj, nx - dj)
                if di * di + dj * dj < rcap * rcap:
                    ok = False; break
            if ok:
                caps.append(k)
            if len(caps) >= n_cap:
                break
        rcap *= 0.5
    for k in caps:
        asent[k]["rango"] = 3     # capital

    # ---- 3. coste del terreno y red de caminos ----
    pend = aux["pend"]
    # coste de transito por tierra: barato en llano habitable, caro en montana,
    # desierto y hielo; el agua dulce cercana ABARATA (los caminos siguen valles).
    hostil = np.clip(1.0 - H / (float(H.max()) + 1e-6), 0.0, 1.0).astype(np.float32)
    costo_t = (np.float32(1.0)
               + np.float32(9.0) * pend
               + np.float32(2.5) * np.clip(campo["alt"] - 0.4, 0.0, None)
               + np.float32(2.0) * hostil
               - np.float32(0.4) * aux["agua"]).astype(np.float32)
    costo_t = np.where(tierra, np.clip(costo_t, 0.2, None), np.inf).astype(np.float32)
    cmin_t = float(np.nanmin(costo_t[np.isfinite(costo_t)])) * 0.9

    def astar_celdas(a, b, cost, cmin):
        src = asent[a]["i"] * nx + asent[a]["j"]
        dst = asent[b]["i"] * nx + asent[b]["j"]
        return _astar(cost, src, dst, ny, nx, cmin)

    # aristas candidatas: k vecinos euclideos mas cercanos del MISMO continente
    K = 5
    cand = set()
    for a in range(len(asent)):
        dd = []
        for b in range(len(asent)):
            if b == a or asent[b]["continente"] != asent[a]["continente"]:
                continue
            dd.append((_dist_esf(asent[a]["i"], asent[a]["j"],
                                  asent[b]["i"], asent[b]["j"], ny, nx), b))
        dd.sort()
        for _, b in dd[:K]:
            cand.add((min(a, b), max(a, b)))

    # coste real (por A*) de cada arista candidata; guarda el camino
    aristas = []
    caminos_idx = {}
    for (a, b) in cand:
        cam = astar_celdas(a, b, costo_t, cmin_t)
        if cam is None or len(cam) < 2:
            continue
        w = 0.0
        for u, v in zip(cam[:-1], cam[1:]):
            ui, uj = divmod(u, nx); vi, vj = divmod(v, nx)
            diag = (ui != vi) and (uj != vj)
            w += 0.5 * (costo_t[ui, uj] + costo_t[vi, vj]) * (float(_SQRT2) if diag else 1.0)
        aristas.append((w, a, b))
        caminos_idx[(a, b)] = cam

    arbol = _kruskal(len(asent), aristas)
    en_arbol = {(min(a, b), max(a, b)) for _, a, b in arbol}
    # redundancia: cada asentamiento conserva ademas su vecino mas barato
    mejor_vec = {}
    for (w, a, b) in aristas:
        if a not in mejor_vec or w < mejor_vec[a][0]:
            mejor_vec[a] = (w, b)
        if b not in mejor_vec or w < mejor_vec[b][0]:
            mejor_vec[b] = (w, a)
    usar = set(en_arbol)
    for a, (w, b) in mejor_vec.items():
        usar.add((min(a, b), max(a, b)))

    def trocear(cam):
        """indices planos -> polilineas [[j,i],...] partidas donde la ruta cruza
        el borde Este-Oeste (la longitud envuelve; los polos no)."""
        polis = []; act = []; prev = None
        for u in cam:
            pi, pj = divmod(u, nx)
            if prev is not None and (abs(pj - prev[1]) > nx * 0.5 or abs(pi - prev[0]) > ny * 0.5):
                if len(act) >= 2:
                    polis.append(act)
                act = []
            act.append([round(pj + 0.5, 2), round(pi + 0.5, 2)])
            prev = (pi, pj)
        if len(act) >= 2:
            polis.append(act)
        return polis

    caminos = []
    for key in usar:
        cam = caminos_idx.get(key)
        if not cam:
            continue
        for poli in trocear(cam):
            caminos.append({"puntos": poli, "clase": 0})

    # ---- 4. rutas comerciales: troncal terrestre entre capitales + saltos de mar ----
    rutas = []
    if len(caps) >= 2:
        # MST entre capitales usando el coste de camino ya conocido cuando exista,
        # si no, A* directo. Estas aristas son las troncales terrestres.
        aris_cap = []
        caminos_cap = {}
        for ia in range(len(caps)):
            for ib in range(ia + 1, len(caps)):
                a, b = caps[ia], caps[ib]
                if asent[a]["continente"] != asent[b]["continente"]:
                    continue
                key = (min(a, b), max(a, b))
                cam = caminos_idx.get(key) or astar_celdas(a, b, costo_t, cmin_t)
                if not cam or len(cam) < 2:
                    continue
                w = _dist_esf(asent[a]["i"], asent[a]["j"], asent[b]["i"], asent[b]["j"], ny, nx)
                aris_cap.append((w, ia, ib))
                caminos_cap[(ia, ib)] = (cam, a, b)
        for _, ia, ib in _kruskal(len(caps), aris_cap):
            cam, a, b = caminos_cap[(min(ia, ib), max(ia, ib))]
            for poli in trocear(cam):
                rutas.append({"puntos": poli, "mar": False,
                              "a": caps.index(a), "b": caps.index(b)})

        # rutas maritimas: unen capitales costeras de CONTINENTES distintos por el
        # mar (A* sobre coste marino: barato en mar abierto, prohibido en tierra)
        d_mar = aux["d_mar"]
        costo_m = np.where(mar, np.float32(1.0) + np.float32(0.02) * np.clip(30.0 - d_mar, 0.0, None),
                           np.inf).astype(np.float32)
        cmin_m = 0.9
        caps_costa = [k for k in caps if asent[k]["costa"]]

        def celda_mar_junto(k):
            """celda de mar adyacente a la capital costera k (puerto)."""
            i0, j0 = asent[k]["i"], asent[k]["j"]
            for di, dj in _OFF8:
                ni = i0 + di
                if ni < 0 or ni >= ny:
                    continue
                nj = (j0 + dj) % nx
                if mar[ni, nj]:
                    return ni * nx + nj
            return None

        vistos_par = set()
        for x in range(len(caps_costa)):
            for y in range(x + 1, len(caps_costa)):
                ka, kb = caps_costa[x], caps_costa[y]
                if asent[ka]["continente"] == asent[kb]["continente"]:
                    continue
                pa, pb = celda_mar_junto(ka), celda_mar_junto(kb)
                if pa is None or pb is None:
                    continue
                par = (asent[ka]["continente"], asent[kb]["continente"])
                par = (min(par), max(par))
                if par in vistos_par:      # una sola ruta por par de continentes
                    continue
                cam = _astar(costo_m, pa, pb, ny, nx, cmin_m)
                if not cam or len(cam) < 2:
                    continue
                vistos_par.add(par)
                # anclar la polilinea en las dos capitales (puerto -> puerto)
                cam = [asent[ka]["i"] * nx + asent[ka]["j"]] + cam + [asent[kb]["i"] * nx + asent[kb]["j"]]
                for poli in trocear(cam):
                    rutas.append({"puntos": poli, "mar": True,
                                  "a": caps.index(ka), "b": caps.index(kb)})

    # ---- 5. paises: Dijkstra multi-fuente desde las capitales; RIOS y montanas
    # como barreras -> las fronteras caen sobre divisorias y cauces ----
    costo_f = (np.float32(1.0)
               + np.float32(11.0) * pend
               + np.float32(3.0) * np.clip(campo["alt"] - 0.35, 0.0, None)
               + np.float32(6.0) * campo["caudal"]                # cruzar rio cuesta
               + np.where(campo["rio"], np.float32(8.0), np.float32(0.0))).astype(np.float32)
    costo_f = np.where(tierra, costo_f, np.inf).astype(np.float32)
    fuentes = [(asent[k]["i"], asent[k]["j"]) for k in caps]
    if fuentes:
        idmap, gcost = _dijkstra_multi(costo_f, fuentes, ny, nx)
    else:
        idmap = np.full((ny, nx), -1, np.int32)
        gcost = np.full((ny, nx), np.inf, np.float32)
    # paises CHICOS: cada capital solo retiene el suelo barato de alcanzar; el
    # resto queda como tierras libres (idmap -1). El umbral es un cuantil del
    # coste acumulado sobre el suelo asignado -> escala sola con el mundo.
    if tam_paises == 2:
        val = idmap >= 0
        if val.any():
            lim = float(np.quantile(gcost[val], 0.55))
            idmap = np.where(val & (gcost <= lim), idmap, -1).astype(np.int32)

    # paleta de paises (tonos HSV bien espaciados) determinista
    rgb_pais = []
    for k in range(max(1, len(caps))):
        h = (k * 0.61803398875) % 1.0
        rgb_pais.append(_hsv(h, 0.45, 0.95))

    # asignacion de cada asentamiento a su pais (por idmap en su celda; con
    # paises chicos los que caen en tierras libres quedan en -1)
    pob_asent = np.zeros(max(1, len(caps)), np.float64)
    for a in asent:
        a["pais"] = int(idmap[a["i"], a["j"]])
        if a["pais"] >= 0:
            pob_asent[a["pais"]] += a["poblacion"]

    # nombres, area y POBLACION de cada pais: la de sus asentamientos mas una
    # rural proporcional a la habitabilidad del territorio que domina
    lista_pais = []
    for k, cap_idx in enumerate(caps):
        dom = idmap == k
        area = int(np.count_nonzero(dom))
        rural = float(H[dom].sum()) * 400.0
        nom = _nombre(rng, None)
        pref = _PREF_PAIS[int(rng.integers(len(_PREF_PAIS)))]
        lista_pais.append({"id": k, "nombre": f"{pref} {nom}",
                           "capital": cap_idx, "rgb": rgb_pais[k], "area": area,
                           "poblacion": int(round(pob_asent[k] + rural))})
        asent[cap_idx]["nombre_cap"] = nom

    # nombre de cada asentamiento (las capitales conservan la raiz del pais)
    for k, a in enumerate(asent):
        rr = np.random.default_rng(((seed & 0xFFFF) << 12) ^ (k * 2654435761 & 0xFFFFFFFF))
        a["nombre"] = a.get("nombre_cap") or _nombre(rr, None)
        a.pop("nombre_cap", None)
        a.pop("score", None)

    # ---- 6. subregiones: provincias dentro de cada pais (sembradas por sus
    # asentamientos, mismas barreras que las fronteras) y cuencas marinas
    # pequenas en el mar (fronteras sobre dorsales submarinas) ----
    submap, lista_prov = _provincias(idmap, costo_f, asent, rng)
    # color de provincia: el tono del pais aclarado/oscurecido de forma ciclica
    # (misma familia cromatica que su pais, distinguible entre vecinas)
    n_por_pais = {}
    for r in lista_prov:
        k = n_por_pais.get(r["pais"], 0)
        n_por_pais[r["pais"]] = k + 1
        base = rgb_pais[r["pais"]] if r["pais"] < len(rgb_pais) else [150, 150, 150]
        f = 0.72 + 0.56 * ((k * 0.61803398875) % 1.0)
        r["rgb"] = [int(min(255, round(c * f))) for c in base]
    # islas y archipielagos sin asentamientos: tambien son subregiones
    _islas_vacias(tierra, cont, n_cont, submap, costo_f, seed, lista_prov)
    marmap, lista_mar = _cuencas_marinas(mar, campo["elev"], seed)

    return {
        "asentamientos": asent,
        "caminos": caminos,
        "rutas": rutas,
        "paises": {"lista": lista_pais, "idmap": idmap, "capitales": caps,
                   "tierra_total": int(np.count_nonzero(tierra))},
        "subregiones": {"tierra": {"lista": lista_prov, "idmap": submap},
                        "mar": {"lista": lista_mar, "idmap": marmap}},
    }


def _hsv(h, s, v):
    """HSV(0..1) -> [r,g,b] 0..255 (sin depender de colorsys por claridad)."""
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
    i %= 6
    r, g, b = [(v, t, p), (q, v, p), (p, v, t),
               (p, q, v), (t, p, v), (v, p, q)][i]
    return [int(round(r * 255)), int(round(g * 255)), int(round(b * 255))]
