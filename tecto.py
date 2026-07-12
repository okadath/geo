"""
Simulacion geologica ligera: conveccion 3D aproximada -> tectonica 2D -> mapa.

Tres capas de abstraccion:
  1. MANTO 3D (48x48x8): campo de temperatura T. Conveccion aproximada:
     - flotabilidad: velocidad vertical w ~ (T - media horizontal de la capa)
     - continuidad: div_h(u,v) = -dw/dz  ->  flujo horizontal via Poisson/FFT
     - adveccion semi-lagrangiana + difusion. Sin presion, sin Navier-Stokes.
  2. LITOSFERA 2D (256x256): espesor de corteza C advectado por la velocidad
     de la capa superior del manto. Divergencia => corteza nueva delgada
     (oceano/rift). Convergencia => apilamiento (montanas) o subduccion.
  3. RENDER: elevacion = isostasia(C) - nivel del mar, tinte hipsometrico,
     bordes de placa marcados donde |div| o cizalla son altos.

Geometria ESFERICA (mapa equirrectangular): el eje X (longitud) es periodico
y el eje Y (latitud) termina en los polos (NO envuelve; borde Neumann). Costo
por paso: unas cuantas FFTs 48x48 y operaciones vectorizadas 256x256 -> corre
cientos de pasos por segundo.
"""
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import clima            # capa climatica: funcion PURA de la geografia de cada
                        # cuadro (temperatura, vientos, corrientes, lluvia,
                        # biomas, rios). NO retroalimenta la tectonica ni consume
                        # el rng global -> la continuacion de mundos sigue
                        # bit-exacta; se calcula solo al renderizar un frame

rng = np.random.default_rng(7)

# ---------------- parametros ----------------
MX = MY = 48          # resolucion horizontal del manto
MZ = 8                # capas verticales del manto
NX = NY = 256         # resolucion del mapa de superficie (ajustable por CLI)
DT = 1.0
KAPPA = 0.08          # difusion termica
BUOY = 0.9            # ganancia de flotabilidad
VEL_SCALE = 18.0      # cuanto mueve el manto a la corteza (px/paso); mayor =
                      # evolucion geologica mas rapida por paso
C_OCEAN = 0.35        # espesor de corteza oceanica nueva
C_CONT = 1.0          # espesor continental inicial
CONT_UMBRAL = 0.55    # umbral del ruido inicial: menor = mas continente
SEA_LEVEL = 0.52      # nivel del mar en unidades de espesor
EROSION = 0.008
PLUME_EVERY = 70      # cada cuantos pasos nace una pluma nueva en el manto
PLUME_AMP = 0.06      # calor inyectado por paso por cada pluma activa
DECAY = 0.006         # decaimiento de anomalias -> las plumas viejas mueren
AGE_TAU = 70.0        # pasos en que el fondo oceanico joven se hunde
SUBSIDENCE = 0.45     # cuanto se hunde el fondo viejo vs la dorsal
TRENCH = 6.0          # profundidad extra de las fosas de subduccion
SLAB_PULL = 0.1       # cuanto enfria el manto la placa que subduce
RIGID = 0.85          # rigidez de placa: 0=fluido, 1=balsa perfectamente rigida
LGRID = 64            # malla reducida para etiquetar continentes
MOMENTUM = 0.02       # memoria de rumbo de las placas: fraccion por paso con
                      # que la velocidad persistente se relaja hacia el manto
                      # (menor = rumbo mas sostenido, colisiones mas decididas)
RIDGE_PUSH = 0.15     # empuje de dorsal: el fondo joven y elevado desliza las
                      # placas pendiente abajo, alejandolas de la dorsal
SLAB_PULL_SURF = 0.08 # tiron de losa en superficie: la placa es jalada hacia
                      # la fosa donde subduce; si la dorsal se apaga (pluma
                      # muerta) este es el motor que sigue moviendo la placa
HALO_PLACA = 6        # celdas LGRID de banda oceanica adherida al margen
                      # pasivo que remolcan al continente (la placa real no
                      # termina en la costa; una banda y no todo el oceano:
                      # ver el comentario del remolque en Crust.step)
DERIVA = 8.0          # ganancia de la traslacion de balsa: bajo un continente
                      # grande el manto esta casi en punto de estancamiento y
                      # su media se cancela; sin compensarla los continentes
                      # quedan anclados mientras el oceano fluye alrededor
ARRASTRE = 0.015      # relajacion del impulso de placa hacia el empuje del
                      # manto (por paso): la placa en movimiento conserva su
                      # rumbo ~1/ARRASTRE pasos aunque el manto se reorganice
                      # (inercia de deriva: los continentes terminan su viaje)
FUERZA_PLACA = 10.0   # ganancia de las fuerzas de borde (dorsal+losa)
                      # integradas sobre el territorio de la placa; sostienen
                      # ~FUERZA_PLACA/ARRASTRE veces la fuerza media (el
                      # motor direccional de la deriva; ver Crust.step)
DORSAL_PERSIST = 0.985  # memoria de la dorsal: una dorsal, una vez encendida,
                        # sigue siendo un eje de expansion mientras haya ALGO
                        # de apertura; no se recalcula de cero cada paso ni
                        # parpadea. Solo muere cuando la apertura cesa de
                        # verdad (la pluma se apago -> deja de crear corteza) o
                        # cuando la convergencia la alcanza (la subduccion la
                        # consume). Antes era memoryless y desaparecia con
                        # cualquier fluctuacion del campo de divergencia
TRENCH_PERSIST = 0.975  # memoria de la fosa: una zona de subduccion, una vez
                        # iniciada, sigue consumiendo litosfera hasta agotar el
                        # oceano viejo o hasta que cese la convergencia (como en
                        # la Tierra la fosa dura hasta que la placa subduce del
                        # todo); antes se recalculaba de cero cada paso
PLUME_FUERZA_MIN = 0.30 # intensidad (hot) por debajo de la cual una pluma es
                        # "sin fuerza": hotspot/domo local (LIP) que NO organiza
                        # un eje de expansion; ver la regla pluma-dorsal en
                        # Crust.step
ANOS_POR_PASO = 1.0     # millones de anos (Ma) que representa cada paso de
                        # simulacion: fija la escala de tiempo geologico que se
                        # rotula en los frames (un ciclo de Wilson ~ 400-500 Ma)
MAR_AMPLITUD = 0.03     # amplitud de la variacion eustatica del nivel del mar:
                        # transgresiones/regresiones lentas que inundan o
                        # exponen las plataformas continentales (no toca la
                        # tectonica, solo la linea de costa del render)
# --- diales de la capa climatica (solo render, ver clima.py) ---
TEMPERATURA = 0.0       # -1 = bola de nieve .. 0 = templado (Tierra) .. +1 =
                        # invernadero; desplaza toda la curva termica del planeta
PRECIPITACIONES = 1.0   # 0.2 = arido .. 1 = normal .. 2 = muy humedo; escala la
                        # evaporacion/lluvia (mas lluvia = mas selva y rios)

# ---------------- utilidades ----------------
# Geometria esferica sobre malla equirrectangular: X (longitud) envuelve con
# np.roll; Y (latitud) NO envuelve — los polos son borde. `rolly` es el
# desplazamiento en Y que replica la fila del borde (condicion Neumann), y
# `rollg` elige el desplazamiento correcto segun el eje.

def rolly(f, s, axis=0):
    """np.roll SIN envolver a lo largo de `axis` (el eje de latitud): las filas
    que saldrian por un polo se sustituyen por la fila del borde (replicada)."""
    g = np.roll(f, s, axis)
    if s == 0:
        return g
    dst = [slice(None)] * f.ndim
    src = [slice(None)] * f.ndim
    if s > 0:
        dst[axis] = slice(0, s); src[axis] = slice(0, 1)
    else:
        dst[axis] = slice(s, None); src[axis] = slice(-1, None)
    g[tuple(dst)] = f[tuple(src)]
    return g

def rollg(f, s, axis):
    """Desplazamiento geo-consciente: periodico en X (ultimo eje = longitud),
    con borde replicado en Y (penultimo eje = latitud)."""
    return np.roll(f, s, axis) if axis == f.ndim - 1 else rolly(f, s, axis)

def grad_periodic(f):
    """Gradiente centrado: periodico en X, unilateral (borde replicado) en Y."""
    fy = (rolly(f, -1) - rolly(f, 1)) * 0.5
    fx = (np.roll(f, -1, 1) - np.roll(f, 1, 1)) * 0.5
    return fx, fy

def lap_periodic(f, axes=(0, 1)):
    """Laplaciano de 5 puntos: periodico en X, Neumann (borde replicado) en Y.
    Para arrays 3D (z,y,x) el penultimo eje es la latitud."""
    out = -2 * len(axes) * f
    for a in axes:
        out += rollg(f, 1, a) + rollg(f, -1, a)
    return out

def poisson_fft(rhs):
    """Resuelve lap(phi) = rhs via FFT: periodico en X y con condicion Neumann
    en los polos (extension PAR en Y: se refleja el dominio y se resuelve en el
    doble de filas; la mitad superior es la solucion con flujo nulo en los
    bordes de latitud).

    Amortigua los modos de escala mas grande: sin esto 1/k^2 hace que
    domine una sola celda de conveccion global; fisicamente las celdas
    miden ~la profundidad del manto, no todo el dominio.
    """
    ny = rhs.shape[0]
    rhs2 = np.concatenate([rhs, rhs[::-1]], axis=0)   # extension par en Y
    ky = np.fft.fftfreq(rhs2.shape[0]) * 2 * np.pi
    kx = np.fft.fftfreq(rhs2.shape[1]) * 2 * np.pi
    k2 = ky[:, None] ** 2 + kx[None, :] ** 2
    k2[0, 0] = 1.0
    k0 = 2 * np.pi * 2.5 / ny                    # ~2.5 celdas por dominio
    damp = 1.0 - np.exp(-k2 / k0 ** 2)
    phi = np.fft.ifft2(np.fft.fft2(rhs2) * damp / -k2).real
    return phi[:ny]

def advect(f, u, v, dt):
    """Adveccion semi-lagrangiana (backtrace bilineal): periodica en X,
    recortada en Y (nada entra ni sale por los polos)."""
    ny, nx = f.shape
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    sx = (xx - u * dt) % nx
    sy = np.clip(yy - v * dt, 0.0, ny - 1)
    x0 = np.floor(sx).astype(int); y0 = np.floor(sy).astype(int)
    fx = sx - x0; fy = sy - y0
    x1 = (x0 + 1) % nx; y1 = np.minimum(y0 + 1, ny - 1)
    return (f[y0, x0] * (1 - fx) * (1 - fy) + f[y0, x1] * fx * (1 - fy)
            + f[y1, x0] * (1 - fx) * fy + f[y1, x1] * fx * fy)

def upsample(f, ny, nx):
    """Bilineal (periodico en X, recortado en Y) de la malla del manto a la del
    mapa."""
    y = np.arange(ny) * f.shape[0] / ny
    x = np.arange(nx) * f.shape[1] / nx
    y0 = np.floor(y).astype(int); x0 = np.floor(x).astype(int)
    fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
    y1 = np.minimum(y0 + 1, f.shape[0] - 1); x1 = (x0 + 1) % f.shape[1]
    return (f[np.ix_(y0, x0)] * (1 - fy) * (1 - fx) + f[np.ix_(y0, x1)] * (1 - fy) * fx
            + f[np.ix_(y1, x0)] * fy * (1 - fx) + f[np.ix_(y1, x1)] * fy * fx)

def sample_nearest(f, ny, nx):
    """Remuestreo por vecino mas cercano (para mascaras y etiquetas)."""
    y = np.arange(ny) * f.shape[0] // ny
    x = np.arange(nx) * f.shape[1] // nx
    return f[np.ix_(y, x)]

def _upsample_suave(f, ny, nx):
    """Como upsample pero con interpolacion smoothstep: sin los rombos que la
    bilineal pura deja en el ruido (para las octavas del fBm de detallar)."""
    y = np.arange(ny) * f.shape[0] / ny
    x = np.arange(nx) * f.shape[1] / nx
    y0 = np.floor(y).astype(int); x0 = np.floor(x).astype(int)
    fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
    fy = fy * fy * (3.0 - 2.0 * fy); fx = fx * fx * (3.0 - 2.0 * fx)
    y1 = np.minimum(y0 + 1, f.shape[0] - 1); x1 = (x0 + 1) % f.shape[1]
    return (f[np.ix_(y0, x0)] * (1 - fy) * (1 - fx) + f[np.ix_(y0, x1)] * (1 - fy) * fx
            + f[np.ix_(y1, x0)] * fy * (1 - fx) + f[np.ix_(y1, x1)] * fy * fx)

def _upsample_bicubico(f, factor):
    """Bicubico periodico via PIL para los campos de detallar: continuo y sin
    los rombos/mesetas que bilineal o smoothstep dejan a grandes aumentos.
    Rellena un margen (periodico en X, replicado en Y), escala y recorta."""
    m = 4
    g = np.pad(np.asarray(f, np.float32), ((m, m), (0, 0)), mode="edge")
    g = np.pad(g, ((0, 0), (m, m)), mode="wrap")
    im = Image.fromarray(g, mode="F").resize(
        (g.shape[1] * factor, g.shape[0] * factor), Image.BICUBIC)
    a = np.asarray(im)
    return a[m * factor:-m * factor, m * factor:-m * factor]

def _fbm(rng_d, ny, nx, esc0=8, persistencia=0.55):
    """Ruido fractal (fBm) periodico ~[-1,1]: suma de rejillas aleatorias
    suavizadas, cada octava con el doble de frecuencia y `persistencia` de la
    amplitud de la anterior. `rng_d` es un generador propio del detalle: no
    toca el rng de la simulacion."""
    out = np.zeros((ny, nx), np.float32)
    amp, esc = 1.0, int(esc0)
    while esc <= ny:
        g = rng_d.random((min(esc, ny), min(esc, nx)), dtype=np.float32) * 2 - 1
        out += (amp * _upsample_suave(g, ny, nx)).astype(np.float32)
        amp *= persistencia
        esc *= 2
    # a escala unitaria por percentil (la suma de octavas casi nunca llega a
    # +-1): asi las amplitudes con que se mezcla significan lo que dicen
    return out / np.float32(np.percentile(np.abs(out), 99.5) + 1e-9)

def label_components(mask):
    """Componentes conexas por propagacion de maximos (periodico solo en X:
    los polos no conectan filas opuestas).

    Puro numpy: cada celda toma el id maximo de sus vecinas hasta converger.
    La propagacion a los 4 vecinos se hace por SLICING con max in-place en vez
    de np.roll: mismo resultado bit a bit, pero sin el overhead por-llamada de
    np.roll (normalize_axis, empty_like...), que dominaba el perfil (~2.4x mas
    rapido en 256x256, el caso del render).
    """
    idx = np.arange(mask.size, dtype=np.int64).reshape(mask.shape)
    lab = np.where(mask, idx, -1)
    neg = ~mask
    for _ in range(2 * mask.shape[0]):
        nxt = lab.copy()
        np.maximum(nxt[1:], lab[:-1], out=nxt[1:])      # vecino de arriba
        np.maximum(nxt[:-1], lab[1:], out=nxt[:-1])     # vecino de abajo
        np.maximum(nxt[:, 1:], lab[:, :-1], out=nxt[:, 1:])    # vecino izquierdo
        np.maximum(nxt[:, :1], lab[:, -1:], out=nxt[:, :1])
        np.maximum(nxt[:, :-1], lab[:, 1:], out=nxt[:, :-1])   # vecino derecho
        np.maximum(nxt[:, -1:], lab[:, :1], out=nxt[:, -1:])
        nxt[neg] = -1
        if np.array_equal(nxt, lab):
            break
        lab = nxt
    return lab

def nivel_mar(paso):
    """Variacion eustatica del nivel del mar en el paso `paso`: pequena y lenta,
    suma de senos de varios periodos (ciclos tectonicos de volumen de dorsal +
    ciclos mas cortos tipo glacial). Sube -> transgresion (inunda plataformas);
    baja -> regresion (las expone). Determinista en el paso, asi la reconstruccion
    y la continuacion de un mundo dan el MISMO nivel. Devuelve el desplazamiento
    a sumar a SEA_LEVEL (no toca la tectonica, solo la costa del render)."""
    p = float(paso)
    return MAR_AMPLITUD * (0.60 * np.sin(2 * np.pi * p / 430.0)
                           + 0.30 * np.sin(2 * np.pi * p / 150.0 + 1.1)
                           + 0.10 * np.sin(2 * np.pi * p / 57.0 + 2.3))

# ---------------- 1. manto 3D ----------------
class Mantle:
    def __init__(self):
        # T[z, y, x]; z=0 fondo caliente, z=MZ-1 tope frio
        self.profile = np.linspace(1.0, 0.0, MZ)[:, None, None]
        self.T = self.profile + 0.15 * rng.standard_normal((MZ, MY, MX))
        self.t = 0
        self.plumes = []   # plumas activas: derivan lento y tienen vida finita

    def _blob(self, cy, cx, r):
        """Gaussiana centrada en (cy,cx): periodica en X, recta en Y (los
        polos no se tocan)."""
        dy = np.abs(np.arange(MY)[:, None] - cy)
        dx = np.abs(np.arange(MX)[None, :] - cx); dx = np.minimum(dx, MX - dx)
        return np.exp(-(dy ** 2 + dx ** 2) / (2 * r ** 2))

    def step(self, sink=None):
        T = self.T
        self.t += 1
        # nacimiento de plumas: sitio aleatorio, deriva propia lenta (deja
        # cadenas de islas lineales en superficie) y vida finita
        if self.t % PLUME_EVERY == 0:
            self.plumes.append({
                "y": float(rng.uniform(0, MY)), "x": float(rng.uniform(0, MX)),
                "dy": float(rng.normal(0, 0.04)), "dx": float(rng.normal(0, 0.04)),
                "age": 0, "life": int(rng.integers(250, 600))})
        alive = []
        for p in self.plumes:
            p["age"] += 1
            p["y"] += p["dy"]
            if p["y"] < 0.0 or p["y"] > MY - 1:   # rebota en el polo (no envuelve)
                p["dy"] = -p["dy"]
                p["y"] = min(max(p["y"], 0.0), float(MY - 1))
            p["x"] = (p["x"] + p["dx"]) % MX
            if p["age"] < p["life"]:
                fade = min(p["age"] / 60, 1.0, (p["life"] - p["age"]) / 60)
                blob = self._blob(p["y"], p["x"], r=3.5)
                for z in range(3):
                    T[z] += PLUME_AMP * fade * (1 - z / 3) * blob
                alive.append(p)
        self.plumes = alive
        # muerte de plumas: las anomalias decaen hacia el perfil conductivo
        T += DECAY * (self.profile - T)
        # arrastre de losa: donde subduce corteza, el manto superior se enfria
        # (ancla la corriente descendente bajo las fosas)
        if sink is not None:
            for z in (MZ - 2, MZ - 3):
                T[z] -= SLAB_PULL * sink
        # flotabilidad: anomalia termica de cada capa -> velocidad vertical
        w = BUOY * (T - T.mean(axis=(1, 2), keepdims=True))        # (MZ,MY,MX)
        # continuidad por capa: div_h = -dw/dz -> potencial de flujo horizontal
        dwdz = np.gradient(w, axis=0)
        us, vs = np.empty_like(T), np.empty_like(T)
        for z in range(MZ):
            phi = poisson_fft(-dwdz[z])
            us[z], vs[z] = grad_periodic(phi)
        # adveccion horizontal por capa + transporte vertical upwind
        for z in range(MZ):
            T[z] = advect(T[z], us[z] * 20, vs[z] * 20, DT)
        wpos = np.clip(w, 0, None); wneg = np.clip(w, None, 0)
        dTdz_up = T - np.roll(T, 1, 0)      # trae de abajo si sube
        dTdz_dn = np.roll(T, -1, 0) - T     # trae de arriba si baja
        T += DT * 0.5 * (wpos * -dTdz_up * -1 + wneg * -dTdz_dn * -1)
        T -= DT * 0.5 * (wpos * dTdz_up + wneg * dTdz_dn)
        # cabezas de pluma -> puntos calientes: columna ascendente integrada
        # del manto medio, umbral auto-escalado (una pluma destaca sobre la
        # media sea cual sea la vigorosidad de la conveccion en ese momento)
        wcol = np.clip(w[1:MZ - 1].mean(axis=0), 0, None)
        wm = wcol.mean() + 1e-9
        thr = np.percentile(wcol, 97)   # solo el 3% mas vigoroso son plumas
        self.hot = np.clip((wcol - thr) / (3.0 * wm), 0, 1)
        # difusion + condiciones de borde termicas
        T += KAPPA * lap_periodic(T, axes=(1, 2))
        T[1:-1] += KAPPA * (T[:-2] - 2 * T[1:-1] + T[2:])
        T[0] = 1.0 + 0.12 * rng.standard_normal((MY, MX))   # fondo caliente
        T[-1] = 0.0                                          # tope frio
        np.clip(T, -0.2, 1.4, out=T)
        self.T = T
        # velocidad superficial que siente la litosfera (capa superior)
        return us[-1], vs[-1]

# ---------------- 2. litosfera 2D ----------------
class Crust:
    def __init__(self):
        # continentes iniciales: ruido de baja frecuencia umbralizado
        n = np.zeros((NY, NX))
        for s, a in [(6, 1.0), (12, 0.6), (24, 0.3)]:
            n += a * upsample(rng.standard_normal((s, s)), NY, NX)
        self.F = np.where(n > CONT_UMBRAL, 1.0, 0.0)  # fraccion continental (conservada)
        self.F_total = self.F.sum()            # el material continental no se crea ni destruye
        self.C = C_OCEAN + self.F * (C_CONT - C_OCEAN)
        self.C += 0.03 * rng.standard_normal((NY, NX))
        self.A = np.full((NY, NX), 5 * AGE_TAU)  # edad del fondo: nace viejo
        self.trench = np.zeros((NY, NX))         # intensidad de subduccion
        self.volcano_arc = np.zeros((NY, NX))    # volcanismo de arco
        self.volcano_hot = np.zeros((NY, NX))    # volcanismo de punto caliente
        self.foreland = np.zeros((NY, NX))       # flexion de cuenca de antepais
        # textura fractal de detalle: solo afecta al render (costas rugosas,
        # relieve fino) y viaja advectada con la placa -> detalle "gratis"
        d = np.zeros((NY, NX))
        for s, a in [(16, 1.0), (32, 0.5), (64, 0.25), (128, 0.12)]:
            s = min(s, NY)
            d += a * upsample(rng.standard_normal((s, s)), NY, NX)
        self.D0 = d / (np.abs(d).max() + 1e-9)
        self.D = self.D0.copy()
        self.tick = 0                # etiquetado de placas cada 10 pasos
        self.lab_ids = self.lab_inv = None
        self.Pu = self.Pv = None     # campo de momento: rumbo persistente
        self.Qu = self.Qv = None     # impulso rigido por placa (inercia de deriva)
        self.fzx = np.zeros((NY, NX))  # fuerzas de borde del paso (dorsal+losa)
        self.fzy = np.zeros((NY, NX))
        self.dorsal = np.zeros((NY, NX))  # eje de dorsal activo (cresta fina)
        self.open_mem = np.zeros((NY, NX))  # memoria escalar de apertura: da a
                                          # la dorsal persistencia temporal sin
                                          # ensancharla (se le extrae la cresta)
        self.fosa = np.zeros((NY, NX))    # eje DELGADO de la fosa (render/placas)
        self.rift = np.zeros((NY, NX))    # desgarre continental activo
        self.sea = SEA_LEVEL              # nivel del mar del paso (con eustasia)

    def step(self, um, vm, hot=None):
        u = upsample(um, NY, NX) * VEL_SCALE
        v = upsample(vm, NY, NX) * VEL_SCALE
        # --- rigidez de placa: cada continente se mueve como balsa ---
        # sin esto la velocidad decae a cero en la linea de convergencia
        # (punto de estancamiento) y los mares nunca terminan de cerrarse
        # reetiquetar CADA paso: con etiquetas viejas la velocidad de balsa usa
        # la huella desactualizada del continente y su borde de ataque genera
        # lineas de convergencia falsas (crestas paralelas artificiales)
        self.tick += 1
        mask = sample_nearest(self.F, LGRID, LGRID) > 0.5
        lab = label_components(mask)
        self.lab_ids, self.lab_inv = np.unique(lab, return_inverse=True)
        # memoria de rumbo (inercia efectiva / arrastre de losa): el campo de
        # momento viaja con la placa y solo se relaja despacio hacia el manto
        # instantaneo; sin el, cada pluma nueva desvia a los continentes antes
        # de que alcancen a cruzar el oceano y colisionar
        if self.Pu is None:
            self.Pu, self.Pv = u.copy(), v.copy()
        else:
            self.Pu = advect(self.Pu, u, v, DT) * (1 - MOMENTUM) + MOMENTUM * u
            self.Pv = advect(self.Pv, u, v, DT) * (1 - MOMENTUM) + MOMENTUM * v
            # empuje de dorsal (ridge push): la corteza recien creada queda
            # elevada y las placas se deslizan pendiente abajo, alejandose de
            # la dorsal -> una pluma que abre un rift en medio de un oceano o
            # continente empuja las placas hasta colisionar en el lado opuesto
            ridge = np.exp(-self.A / AGE_TAU)
            rx, ry = grad_periodic(ridge)
            self.Pu -= RIDGE_PUSH * rx
            self.Pv -= RIDGE_PUSH * ry
            self.fzx = -RIDGE_PUSH * rx
            self.fzy = -RIDGE_PUSH * ry
            # tiron de losa (slab pull / succion de fosa): la placa es jalada
            # hacia la fosa donde su borde subduce. Cuando una dorsal se
            # apaga porque su pluma murio deja de crear corteza y de empujar;
            # a partir de ahi son los movimientos de las otras placas --la
            # subduccion en sus margenes y el arrastre del manto-- los que
            # siguen moviendo esa placa, hasta que sea consumida por completo
            pull = self.trench
            for sh in (1, 2, 3, 4):
                pull = 0.2 * (pull + rolly(pull, sh) + rolly(pull, -sh)
                              + np.roll(pull, sh, 1) + np.roll(pull, -sh, 1))
            pull = np.clip(pull / max(pull.max(), 1e-3), 0, 1)
            tx, ty = grad_periodic(pull)
            self.Pu += SLAB_PULL_SURF * tx
            self.Pv += SLAB_PULL_SURF * ty
            self.fzx += SLAB_PULL_SURF * tx
            self.fzy += SLAB_PULL_SURF * ty
        us = sample_nearest(self.Pu, LGRID, LGRID).ravel()
        vs = sample_nearest(self.Pv, LGRID, LGRID).ravel()
        # remolque oceanico: la placa NO termina en la costa; una banda de
        # fondo oceanico soldado al margen pasivo (tipo Atlantico sur
        # adherido a Sudamerica) pertenece a la MISMA balsa y el empuje
        # acumulado en su momento remolca al continente. Sin la banda la
        # media de balsa solo muestrea el manto BAJO el continente (casi
        # un punto de estancamiento entre celdas de conveccion: media ~0)
        # y los continentes quedan anclados mientras el oceano fluye
        # alrededor. Es una BANDA (HALO_PLACA celdas por dilatacion), no
        # todo el oceano por Voronoi: la suma global de velocidades es ~0
        # (incompresibilidad), asi que promediar territorios completos
        # diluye el empuje de vuelta a cero
        lab_ext = lab
        for _ in range(HALO_PLACA):
            for ax in (0, 1):
                for sh in (1, -1):
                    vec = rollg(lab_ext, sh, ax)
                    lab_ext = np.where((lab_ext < 0) & (vec >= 0), vec, lab_ext)
        inv_ext = np.searchsorted(self.lab_ids, lab_ext.ravel())
        nlab = len(self.lab_ids)
        cnt = np.bincount(inv_ext, minlength=nlab).astype(float)
        cnt[cnt == 0] = 1.0
        mu = np.bincount(inv_ext, us, minlength=nlab) / cnt
        mv = np.bincount(inv_ext, vs, minlength=nlab) / cnt
        # motor de fuerzas de borde: la media de VELOCIDAD sobre la placa se
        # cancela (la suma global es 0 por incompresibilidad y el oceano
        # converge simetrico sobre un continente ya asentado en la linea de
        # convergencia), pero la media de FUERZA no: para una placa con
        # dorsal a un lado y fosa al otro, el empuje de dorsal y el tiron
        # de losa apuntan AMBOS de la dorsal a la fosa sobre todo su
        # territorio -- el Voronoi completo del oceano al continente mas
        # cercano, que aproxima "la placa llega hasta la dorsal". Integrada
        # contra el arrastre del impulso, la fuerza media sostiene
        # ~FUERZA_PLACA/ARRASTRE veces su valor: el motor del ciclo de
        # Wilson (las velocidades solas no lo dan, medido: quitar este
        # termino deja la deriva neta en cero)
        terr = lab_ext
        while (terr < 0).any():
            prev = terr
            for ax in (0, 1):
                for sh in (1, -1):
                    vec = rollg(terr, sh, ax)
                    terr = np.where((terr < 0) & (vec >= 0), vec, terr)
            if np.array_equal(prev, terr):     # mapa sin continentes
                break
        inv_t = np.searchsorted(self.lab_ids, terr.ravel())
        cnt_t = np.bincount(inv_t, minlength=nlab).astype(float)
        cnt_t[cnt_t == 0] = 1.0
        fx = np.bincount(inv_t, sample_nearest(self.fzx, LGRID, LGRID).ravel(),
                         minlength=nlab) / cnt_t
        fy = np.bincount(inv_t, sample_nearest(self.fzy, LGRID, LGRID).ravel(),
                         minlength=nlab) / cnt_t
        # impulso de placa (inercia de deriva): la velocidad de balsa NO se
        # rederiva del manto cada paso; cada placa conserva un impulso
        # propio -- un valor rigido por placa, guardado en un campo que su
        # propio territorio recupera al paso siguiente -- que se relaja
        # despacio (ARRASTRE) hacia el empuje actual del manto + dorsal +
        # losa. Un continente en marcha atraviesa asi las reorganizaciones
        # del manto (la muerte de la pluma que lo empujaba) y termina su
        # viaje hasta colisionar, como en un ciclo de Wilson real; al
        # fusionarse dos placas sus impulsos se promedian por area
        if self.Qu is None:
            qu, qv = DERIVA * mu, DERIVA * mv
        else:
            qs = sample_nearest(self.Qu, LGRID, LGRID).ravel()
            qt = sample_nearest(self.Qv, LGRID, LGRID).ravel()
            qu = np.bincount(inv_ext, qs, minlength=nlab) / cnt
            qv = np.bincount(inv_ext, qt, minlength=nlab) / cnt
            qu = (1 - ARRASTRE) * qu + ARRASTRE * (DERIVA * mu) + FUERZA_PLACA * fx
            qv = (1 - ARRASTRE) * qv + ARRASTRE * (DERIVA * mv) + FUERZA_PLACA * fy
        # rotacion rigida (polo de Euler): ademas de trasladarse, cada placa
        # gira segun el torque que el flujo ejerce sobre su huella; sin esto
        # las balsas solo se trasladan y la deriva se ve robotica. Se ajusta
        # la rotacion por minimos cuadrados alrededor del centroide (media
        # circular SOLO en X; en Y la media es lineal: los polos no envuelven)
        yy0, xx0 = np.meshgrid(np.arange(LGRID), np.arange(LGRID), indexing="ij")

        def _cmedia(q):
            a = q.ravel() * (2 * np.pi / LGRID)
            s = np.bincount(inv_ext, np.sin(a), minlength=nlab)
            c = np.bincount(inv_ext, np.cos(a), minlength=nlab)
            return (np.arctan2(s, c) % (2 * np.pi)) * LGRID / (2 * np.pi)
        cy = np.bincount(inv_ext, yy0.ravel().astype(float), minlength=nlab) / cnt
        cx = _cmedia(xx0)
        ry = yy0.ravel() - cy[inv_ext]
        rx = (xx0.ravel() - cx[inv_ext] + LGRID / 2) % LGRID - LGRID / 2
        r2 = np.bincount(inv_ext, ry ** 2 + rx ** 2, minlength=nlab) + 1e-9
        om = np.bincount(inv_ext, rx * (vs - mv[inv_ext]) - ry * (us - mu[inv_ext]),
                         minlength=nlab) / r2
        # tope de giro: la velocidad de rotacion en el borde de la placa no
        # supera su propia traslacion (una placa chica con flujo ruidoso
        # alrededor no debe ponerse a girar como remolino)
        rmax = np.zeros(nlab)
        np.maximum.at(rmax, inv_ext, np.hypot(ry, rx))
        tope = (0.6 * np.hypot(qu, qv) + 0.02) / (rmax + 1e-9)
        om = np.clip(om, -tope, tope)
        u_r = (qu[inv_ext] - om[inv_ext] * ry).reshape(LGRID, LGRID)
        v_r = (qv[inv_ext] + om[inv_ext] * rx).reshape(LGRID, LGRID)
        # el impulso rigido queda almacenado sobre el territorio de cada
        # placa; el paso siguiente lo recupera promediando sobre el nuevo
        # territorio (el etiquetado re-hecho sigue al material sin
        # necesidad de rastrear identidades de placa entre pasos)
        self.Qu = upsample(qu[inv_ext].reshape(LGRID, LGRID), NY, NX)
        self.Qv = upsample(qv[inv_ext].reshape(LGRID, LGRID), NY, NX)
        # el oceano no es balsa: lleva su velocidad local (NO cero — un cero
        # en huecos o suturas dentro del continente crea pozos de velocidad
        # que fabrican crestas orogenicas paralelas artificiales)
        if self.lab_ids[0] == -1:
            oc = (self.lab_inv == 0).reshape(LGRID, LGRID)
            u_r = np.where(oc, us.reshape(LGRID, LGRID), u_r)
            v_r = np.where(oc, vs.reshape(LGRID, LGRID), v_r)
        u_raft = upsample(u_r, NY, NX)
        v_raft = upsample(v_r, NY, NX)
        # suavizar la cuantizacion de la malla de balsas (bloques de 4 px que
        # de otro modo depositan crestas en escalera en los bordes de placa)
        for sh in (1, 2, 3):
            u_raft = 0.2 * (u_raft + rolly(u_raft, sh) + rolly(u_raft, -sh)
                            + np.roll(u_raft, sh, 1) + np.roll(u_raft, -sh, 1))
            v_raft = 0.2 * (v_raft + rolly(v_raft, sh) + rolly(v_raft, -sh)
                            + np.roll(v_raft, sh, 1) + np.roll(v_raft, -sh, 1))
        # peso: continente firme, pero un rift activo lo ablanda para
        # que las plumas nuevas aun puedan desgarrarlo
        ux0, _ = grad_periodic(u); _, vy0 = grad_periodic(v)
        open_m = np.clip(ux0 + vy0, 0, None)
        w = RIGID * np.clip(self.F, 0, 1) * np.clip(1 - open_m * 25, 0, 1)
        u = u * (1 - w) + u_raft * w
        v = v * (1 - w) + v_raft * w
        # velocidad final de placa (para flechas del mapa tectonico)
        self.u_vis, self.v_vis = u, v

        C = advect(self.C, u, v, DT)
        F = np.clip(advect(self.F, u, v, DT), 0, 1)
        ux, uy = grad_periodic(u); vx, vy = grad_periodic(v)
        div = ux + vy
        shear = np.sqrt((ux - vy) ** 2 + (uy + vx) ** 2)
        conv = np.clip(-div, 0, None)
        opening = np.clip(div, 0, None)
        # eje de dorsal/rift: la dorsal NO es la pluma (un punto), es el
        # limite divergente entre celdas de conveccion que UNE las plumas.
        # Se extrae como la CRESTA del campo de divergencia por supresion de
        # no-maximos (maximo local transversal en x o en y): una linea de
        # 1-2 px que sigue el eje tambien en los tramos debiles entre plumas
        # -> dorsales continuas que recorren el oceano en grandes tramos,
        # no manchas redondas alrededor de cada pluma.
        #
        # PERSISTENCIA: la memoria NO se aplica a la cresta ya extraida (eso
        # dejaba una estela ancha al migrar el eje y llenaba el oceano de
        # naranja), sino al campo ESCALAR de apertura, que decae despacio. De
        # ese campo persistente se extrae la cresta CADA paso, asi que la
        # dorsal es siempre una linea fina (como la fosa) y a la vez DURA en
        # el tiempo: los tramos que el eje dejo atras decaen por debajo del eje
        # fresco y la supresion de no-maximos los descarta. Cuando la apertura
        # cesa de verdad (la pluma murio -> deja de crear corteza) open_mem
        # decae y la cresta desaparece: la dorsal muere, como en la Tierra,
        # cuando deja de generar fondo oceanico (o cuando la fosa la alcanza)
        self.open_mem = np.maximum(opening, self.open_mem * DORSAL_PERSIST)
        self.open_mem *= np.clip(1.0 - conv * 20.0, 0.0, 1.0)   # la fosa la apaga
        opn = self.open_mem
        for sh in (1, 1, 2, 2):
            opn = 0.2 * (opn + rolly(opn, sh) + rolly(opn, -sh)
                         + np.roll(opn, sh, 1) + np.roll(opn, -sh, 1))
        fondo = opn
        for sh in (1, 2, 3, 4):
            fondo = 0.2 * (fondo + rolly(fondo, sh) + rolly(fondo, -sh)
                           + np.roll(fondo, sh, 1) + np.roll(fondo, -sh, 1))
        eje = np.zeros(opn.shape, bool)
        for ax in (0, 1):
            mx = opn
            for sh in (1, 2):
                mx = np.maximum(mx, np.maximum(rollg(opn, sh, ax),
                                               rollg(opn, -sh, ax)))
            eje |= opn >= mx - 1e-12
        # compuertas: la cresta necesita divergencia real (no ruido en zona
        # quieta) y debe sobresalir de su fondo local (no meseta plana)
        p98 = np.percentile(opn, 98) + 1e-9
        eje &= (opn > 0.15 * p98) & (opn > fondo)
        eje = (eje | rolly(eje, 1) | rolly(eje, -1)
               | np.roll(eje, 1, 1) | np.roll(eje, -1, 1))
        self.dorsal = eje * np.clip(opn / p98 * 1.5, 0, 1)
        # regla pluma-dorsal: una pluma que crea terreno DEBE ser parte de una
        # dorsal (un eje de expansion) salvo dos excepciones geologicas:
        #   - pluma SIN FUERZA (hot < PLUME_FUERZA_MIN): domo/gran provincia
        #     ignea que no logra abrir un eje de expansion (queda un hotspot)
        #   - placa 100% OCEANICA bajo la pluma: hotspot intraplaca tipo Hawai,
        #     una cadena de islas que la placa arrastra, sin dorsal asociada
        # En cualquier otro caso (pluma con fuerza sobre litosfera que incluye
        # continente) la pluma organiza una dorsal: el rift desgarra el
        # continente y abre un oceano nuevo (Mar Rojo, Rift de Africa oriental,
        # Islandia sobre la dorsal atlantica). Antes se suprimia la dorsal de
        # TODA pluma solitaria; ahora solo la de esas dos excepciones -> una
        # pluma con fuerza conserva y sostiene su dorsal
        if hot is not None and self.dorsal.any():
            hm = hot > 0.15
            if hm.any():
                my, mxh = hot.shape
                esc = NY / my
                labh = label_components(hm)
                yyN, xxN = np.meshgrid(np.arange(NY), np.arange(NX), indexing="ij")
                cents = []
                for i in np.unique(labh[labh >= 0]):
                    ys, xs = np.nonzero(labh == i)
                    ax_ = 2 * np.pi * xs / mxh
                    cy = float(ys.mean())      # Y lineal: los polos no envuelven
                    cx = (np.angle(np.exp(1j * ax_).mean()) % (2 * np.pi)) * mxh / (2 * np.pi)
                    fuerza = float(hot[ys, xs].max())     # fuerza de la pluma
                    cents.append((cy * esc, cx * esc, fuerza))
                r_sup, R = 9 * esc, 18 * esc
                for cy, cx, fuerza in cents:
                    dy = np.abs(yyN - cy)
                    dx = np.abs(xxN - cx); dx = np.minimum(dx, NX - dx)
                    d2 = dy ** 2 + dx ** 2
                    dentro = d2 < R ** 2
                    F_local = float(self.F[dentro].mean()) if dentro.any() else 0.0
                    oceanica = F_local < 0.05             # placa 100% oceanica
                    sin_fuerza = fuerza < PLUME_FUERZA_MIN
                    if sin_fuerza or oceanica:
                        # excepcion: hotspot puro (Hawai) o domo debil -> se
                        # suprime el eje de expansion alrededor de la pluma; se
                        # apaga tambien open_mem para que la cresta no reaparezca
                        supp = np.clip(d2 / r_sup ** 2, 0, 1)
                        self.dorsal *= supp
                        self.open_mem *= supp
                    # else: pluma con fuerza sobre continente -> conserva su
                    # dorsal (el rift real); no se suprime nada
        # rift continental: el mismo umbral de desgarre que usa la fisica
        # para partir continentes (opening > 0.006)
        self.rift = np.clip(opening - 0.006, 0, None)
        # --- subduccion: SOLO el fondo oceanico VIEJO (denso) subduce ---
        # el fondo joven que rodea la dorsal es flotante y no se hunde: sin
        # esta compuerta cada anillo de convergencia alrededor de una pluma
        # abria una fosa pegada a su propia dorsal. Un margen pasivo
        # (continente empujado por el fondo de SU misma placa, tipo
        # Atlantico) tampoco abre fosa: sin salto real de velocidad la
        # convergencia queda bajo el umbral. Fosa => limite de placas
        madura = np.clip(self.A / AGE_TAU - 1.0, 0, 1)   # >2*AGE_TAU: denso
        cerca = self.dorsal
        for sh in (1, 2, 3):
            cerca = 0.2 * (cerca + rolly(cerca, sh) + rolly(cerca, -sh)
                           + np.roll(cerca, sh, 1) + np.roll(cerca, -sh, 1))
        lejos = np.clip(1 - 5.0 * cerca, 0, 1)           # nunca junto al eje
        subd_ign = np.clip(conv - 0.008, 0, None) * madura * lejos   # ignicion
        # persistencia de la fosa: una vez iniciada la subduccion sigue
        # consumiendo litosfera mientras haya convergencia (alive_t) y quede
        # oceano viejo que tragar (madura). No desaparece por una fluctuacion
        # del campo de velocidad; muere cuando cesa la convergencia o cuando la
        # placa oceanica se consumio del todo (la fosa dura hasta que la placa
        # subduce por completo). subd es la BANDA de subduccion (consumo, slab
        # pull, arcos); mas abajo se extrae su EJE delgado (self.fosa) para el
        # render, igual que la dorsal
        alive_t = np.clip((conv - 0.002) / 0.006, 0, 1) * lejos
        subd = np.maximum(subd_ign, self.trench * TRENCH_PERSIST * alive_t * madura)
        # falla transformante: cizalla alta con divergencia baja -> las placas
        # solo se rozan; no hay orogenia ni fosa, apenas un valle de falla
        transform = np.clip(shear - 2.5 * np.abs(div), 0, None)
        C -= 0.3 * transform * DT
        # convergencia: solo el oceano viejo subduce (se consume); el
        # continente se apila (orogenia: la colision levanta cordilleras)
        C = np.where(F < 0.4, C - subd * C * DT * 1.5, C + conv * C * DT * 1.8)
        # arco de subduccion: la placa oceanica que se hunde bajo el margen
        # continental levanta una cordillera costera en la placa que cabalga
        # (tipo Andes): la fosa difuminada, aplicada solo sobre continente
        arc = subd * (F < 0.4)
        for sh in (1, 2, 3):   # desplazamientos crecientes: blur sin peine
            arc = 0.2 * (arc + rolly(arc, sh) + rolly(arc, -sh)
                         + np.roll(arc, sh, 1) + np.roll(arc, -sh, 1))
        C += 1.8 * arc * F * DT
        # cuenca de antepais: la corteza se flexiona hacia abajo frente al
        # orogeno en crecimiento -> depresion que puede inundarse (mar
        # interior, como el que habia frente a los Andes). Flexion = carga
        # orogenica difuminada ancha menos el nucleo del orogeno
        G = (conv + arc) * F
        basin = G
        for sh in (1, 2, 3, 4):   # desplazamientos crecientes = blur suave sin peine
            basin = 0.2 * (basin + rolly(basin, sh) + rolly(basin, -sh)
                           + np.roll(basin, sh, 1) + np.roll(basin, -sh, 1))
        self.foreland = np.clip(basin - 1.5 * G, 0, None) * (F > 0.3)
        # divergencia: se abre rift -> corteza oceanica nueva (diluye F)
        C -= opening * (C - C_OCEAN) * DT * 1.2
        # desgarramiento: solo un rift FUERTE y sostenido parte un continente;
        # la divergencia debil no desgasta la corteza continental (esta no se
        # hunde ni desaparece, solo la oceanica subduce)
        F -= np.clip(opening - 0.006, 0, None) * F * DT * 2.0
        # anti-difusion biestable: empuja F hacia 0 o 1 para que los bordes
        # continentales no se degraden en neblina numerica; se apaga donde
        # hay rift activo para no soldar lo que la pluma esta desgarrando
        F += 0.08 * F * (1 - F) * (2 * F - 1) * np.clip(1 - opening * 25, 0, 1) * DT
        # conservacion: el material continental total es constante (un rift
        # parte un continente, no lo destruye)
        F = np.clip(F * self.F_total / max(F.sum(), 1e-9), 0, 1)
        # flotabilidad continental: el continente nunca baja de su espesor base
        floor = C_OCEAN + F * (C_CONT - C_OCEAN) * 0.92
        C = np.maximum(C, floor)
        # relajacion lenta; el relieve continental resiste mucho mas que el
        # oceanico (las cordilleras interiores no se aplanan solas)
        C -= 0.001 * (C - floor) * (1 - 0.75 * F) * DT
        self.F = F
        # edad del fondo oceanico: se advecta, envejece, y renace SOLO en el
        # eje de la dorsal — la divergencia debil de fondo no rejuvenece el
        # oceano (antes lo hacia y la edad no tenia estructura: mediana ~8
        # pasos en todo el mapa, dorsales por todas partes)
        A = advect(self.A, u, v, DT) + DT
        A *= np.clip(1.0 - 3.0 * self.dorsal, 0.02, 1)
        self.A = np.clip(A, 0, 10 * AGE_TAU)
        # fosa de subduccion (BANDA): la intensidad persistente con compuertas
        # (fondo viejo + lejos de la dorsal + convergencia); alimenta el consumo
        # de corteza, el slab pull (superficie y manto) y los arcos volcanicos
        self.trench = subd * (F < 0.4)
        # eje DELGADO de la fosa: la CRESTA de la banda de subduccion por
        # supresion de no-maximos, igual que la dorsal -> una linea de 1-2 px
        # (no un hueco ancho) que sigue el limite de placa en tramos largos.
        # Es lo que dibujan el mapa (batimetria de la fosa) y el mapa de placas
        tb = self.trench
        for sh in (1, 1, 2, 2):
            tb = 0.2 * (tb + rolly(tb, sh) + rolly(tb, -sh)
                        + np.roll(tb, sh, 1) + np.roll(tb, -sh, 1))
        ejf = np.zeros(tb.shape, bool)
        for ax in (0, 1):
            mxf = tb
            for sh in (1, 2):
                mxf = np.maximum(mxf, np.maximum(rollg(tb, sh, ax),
                                                 rollg(tb, -sh, ax)))
            ejf |= tb >= mxf - 1e-12
        pf = np.percentile(tb, 98) + 1e-9
        ejf &= tb > 0.15 * pf
        ejf = (ejf | rolly(ejf, 1) | rolly(ejf, -1)
               | np.roll(ejf, 1, 1) | np.roll(ejf, -1, 1))
        self.fosa = ejf * np.clip(tb / pf * 1.5, 0, 1) * (F < 0.4)
        # --- volcanismo ---
        # puntos calientes: donde una cabeza de pluma toca la litosfera
        hs = np.zeros((NY, NX))
        if hot is not None:
            hs = np.clip(upsample(hot, NY, NX), 0, None) * 0.25
        # en el mar el punto caliente construye un edificio volcanico (islas
        # tipo Hawai; la placa que deriva encima deja una cadena) y el domo
        # termico rejuvenece el fondo (queda somero)
        isl = hs * (F < 0.4)
        # el edificio volcanico crece y EMERGE como isla (Hawai, Polinesia): la
        # placa que deriva sobre el punto caliente casi-fijo deja una CADENA de
        # islas —el edificio viaja advectado con C y, al alejarse del foco, su
        # fondo envejece y se hunde (isla -> guyot -> monte submarino). Emerge
        # claro sobre el mar pero sigue siendo volcanismo puntual, no continente
        C += 0.22 * isl * np.clip(1.05 - C, 0, 1) * DT
        # el foco rejuvenece el fondo justo debajo (domo termico somero); al
        # alejarse la isla ya no se rejuvenece y empieza a subsidir -> la cadena
        # se hunde progresivamente con la distancia al punto caliente
        self.A *= np.clip(1 - 3 * isl, 0.2, 1)
        # arco de ISLAS: la subduccion intraoceanica (tipo Marianas, Caribe,
        # arco de Japon) construye un arco volcanico de islas paralelo a su
        # fosa. Emerge junto a la fosa, no encima (ahi la subduccion se lo
        # comeria): el halo excluye el nucleo de la fosa y el arco crece a un
        # lado como una cadena de islas que rompe la superficie
        iarc = self.trench
        for sh in (1, 2):
            iarc = 0.2 * (iarc + rolly(iarc, sh) + rolly(iarc, -sh)
                          + np.roll(iarc, sh, 1) + np.roll(iarc, -sh, 1))
        halo = np.clip(1 - self.trench * 50, 0, 1)
        C += 2.6 * iarc * halo * (F < 0.4) * np.clip(1.18 - C, 0, 1) * DT
        # actividad volcanica para el render: arcos de subduccion
        # (continentales y de islas) + cabezas de pluma
        self.volcano_arc = arc * F + iarc * (F < 0.4)
        self.volcano_hot = hs
        # el detalle viaja con la placa; una gota del original por paso
        # compensa la difusion numerica sin dejar textura estatica
        self.D = advect(self.D, u, v, DT) * 0.90 + 0.10 * self.D0
        # erosion con rebote isostatico: al erosionarse una cordillera la raiz
        # cortical empuja de vuelta hacia arriba, asi que solo ~35% de lo
        # erosionado se pierde en las cimas (por eso los Apalaches persisten);
        # lo depositado en los valles se conserva completo
        land = C > getattr(self, "sea", SEA_LEVEL)
        d = EROSION * lap_periodic(C) * land * (1 - 0.7 * F)
        C += np.where(d < 0, 0.35 * d, d)
        # suavizado debil global: borra los "anillos de crecimiento" de la
        # orogenia (franjas de 2 px por paso) sin aplanar el relieve grande
        C += 0.05 * lap_periodic(C) * DT
        np.clip(C, 0.2, 2.2, out=C)
        self.C = C
        # cizalla para pintar bordes de placa; se atenua sobre las cabezas de
        # pluma para que no salgan como manchas redondas (ahi el volcan rojo
        # ya marca el punto caliente)
        boundary = (np.abs(div) + shear) * (1 - np.clip(hs * 30, 0, 0.95))
        # los arcos volcanicos y las cordilleras nacidas de la colision
        # tambien son limite de placa (marcan la sutura/el margen activo):
        # se suman al campo de borde, que alimenta tanto los trazos rojos
        # del mapa como la segmentacion del mapa de placas
        boundary = boundary + 3.0 * self.volcano_arc
        return boundary

    def elevation(self, detail=0.6):
        # nivel del mar con su variacion eustatica del paso actual (self.sea lo
        # fija el bucle de simulacion / la reconstruccion); mundos viejos o un
        # render suelto caen al nivel base
        sea = getattr(self, "sea", SEA_LEVEL)
        elev = (self.C - sea) * 1.1
        # en tierra la escala es cuadratica: llanuras verdes cerca del mar,
        # solo las zonas de colision llegan a cordillera/nieve
        elev = np.where(elev > 0, 0.5 * elev ** 2 + 0.03, elev)
        ocean = self.F < 0.5
        # subsidencia termica: el fondo joven (dorsal) queda somero y el
        # viejo se hunde -> cordilleras submarinas donde diverge el manto
        elev -= SUBSIDENCE * (1 - np.exp(-self.A / AGE_TAU)) * ocean
        # plataforma continental: el margen sumergido del continente sigue
        # siendo corteza continental -> mar somero y plano que bordea las
        # costas, con talud abrupto hacia el abisal (halo de F difuminado,
        # remapeado casi-binario para que la plataforma sea plana y el
        # quiebre nitido). Se aplica antes de la fosa: los margenes activos
        # la pierden bajo la fosa de subduccion
        marg = self.F
        for sh in (1, 2, 3, 4):
            marg = 0.2 * (marg + rolly(marg, sh) + rolly(marg, -sh)
                          + np.roll(marg, sh, 1) + np.roll(marg, -sh, 1))
        plataforma = np.clip(6.0 * (marg - 0.18), 0, 1) * ocean
        elev += np.clip(-0.025 - elev, 0, None) * plataforma
        # fosa de subduccion: depresion batimetrica DELGADA (el eje de la fosa,
        # no la banda ancha) -> una linea profunda como en la Tierra, no un
        # hueco. getattr: mundos guardados antes del eje delgado no traen fosa
        elev -= TRENCH * getattr(self, "fosa", self.trench)
        # cuenca de antepais: depresion flexural frente a la cordillera en
        # crecimiento; si baja del nivel del mar se inunda (mar interior)
        elev -= 14.0 * self.foreland
        # rugosidad fractal: mas fuerte en montana, sutil en el mar; corta
        # las costas de forma irregular sin costo de simulacion
        elev += detail * self.D * (0.04 + 0.11 * np.clip(elev, 0, 1))
        return np.clip(elev, -1, 1)

# ---------------- 3. render ----------------
HYPSO = np.array([  # (nivel, r,g,b) elevacion normalizada -1..1
    (-1.0, 10, 20, 60), (-0.4, 15, 60, 120), (-0.06, 55, 125, 178),
    (-0.035, 90, 175, 190),   # banda somera: plataforma continental
    (0.0, 105, 180, 180), (0.02, 190, 180, 120), (0.15, 110, 150, 70),
    (0.4, 140, 120, 80), (0.7, 150, 140, 130), (1.0, 255, 255, 255),
], dtype=float)

def render(elev, boundary, volcanoes=None):
    img = np.empty(elev.shape + (3,))
    for ch in range(3):
        img[..., ch] = np.interp(elev, HYPSO[:, 0], HYPSO[:, ch + 1])
    # sombreado simple por pendiente (relieve)
    gx, gy = grad_periodic(elev)
    shade = np.clip(1.0 + 2.2 * (gx - gy), 0.78, 1.22)
    img *= shade[..., None]
    # bordes de placa en rojo oscuro translucido (suavizados para que se
    # lean como limites lineales y no como manchas)
    for _ in range(2):
        boundary = 0.2 * (boundary + rolly(boundary, 1) + rolly(boundary, -1)
                          + np.roll(boundary, 1, 1) + np.roll(boundary, -1, 1))
    b = np.clip(boundary / (np.percentile(boundary, 98) + 1e-9) - 0.6, 0, 1)[..., None]
    img = img * (1 - 0.45 * b) + np.array([180, 40, 30]) * 0.45 * b
    # volcanes: punto rojo en cada maximo local de actividad volcanica
    # (arcos de subduccion y puntos calientes)
    if volcanoes is not None:
        dots = np.zeros(elev.shape, bool)
        for vol, vmin, win in volcanoes:
            if vol.max() < vmin:
                continue
            m = vol
            for dy in range(-win, win + 1):
                for dx in range(-win, win + 1):
                    m = np.maximum(m, np.roll(rolly(vol, dy), dx, 1))
            dots |= (vol >= m) & (vol > max(vmin, 0.35 * vol.max()))
        dots = (dots | rolly(dots, 1) | rolly(dots, -1)
                | np.roll(dots, 1, 1) | np.roll(dots, -1, 1))
        img[dots] = (235, 45, 25)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))

# paleta del manto: azul = anomalia fria (losas que bajan), oscuro = neutro,
# naranja/amarillo = anomalia caliente (plumas que suben)
_PALETA_MANTO = np.array([
    (-1.0, 30, 55, 130), (-0.35, 28, 45, 95), (0.0, 24, 22, 34),
    (0.35, 150, 60, 20), (0.7, 235, 120, 25), (1.0, 255, 230, 120),
], dtype=float)

def render_manto(T, plumes=(), n=None):
    """Mapa del manto: plumas calientes que ascienden (naranja/amarillo,
    anomalia de las capas BAJAS, donde se inyectan) y zonas de hundimiento
    (azul, anomalia fria de las capas ALTAS: las losas que subducen enfrian
    el manto superior bajo las fosas). Separar por capas evita que la
    dorsal salga azul: la dorsal no es una bajada del manto, es el eje
    divergente en superficie y queda neutra. Anillo blanco = pluma activa.
    Se calcula solo desde T, asi tambien sirve para reconstruir mundos."""
    n = n or NX
    an = T - T.mean(axis=(1, 2), keepdims=True)
    sube = np.clip(upsample(an[1:MZ // 2 + 1].mean(axis=0), n, n) / 0.30, 0, 1)
    baja = np.clip(upsample(an[MZ - 3:MZ - 1].mean(axis=0), n, n) / 0.20, -1, 0)
    a = sube + baja
    img = np.empty((n, n, 3))
    for ch in range(3):
        img[..., ch] = np.interp(a, _PALETA_MANTO[:, 0], _PALETA_MANTO[:, ch + 1])
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    esc = n / MX
    r = 3.5 * esc
    for p in plumes:
        fade = min(p["age"] / 60, 1.0, (p["life"] - p["age"]) / 60)
        if fade <= 0:
            continue
        cx, cy = p["x"] * esc, p["y"] * esc
        # copias solo en X (longitud periodica): un anillo que cruza la orilla
        # izquierda/derecha reaparece por la otra; en Y los polos no envuelven
        for ox in (-n, 0, n):
            x, y = cx + ox, cy
            d.ellipse([x - r, y - r, x + r, y + r],
                      outline=(255, 255, 255, int(80 + 150 * fade)), width=2)
    return im

# ---------------- mapa tectonico (placas, flechas y simbologia) ----------------
def _flechas(d, u, v, n):
    """Flechas de deriva: velocidad de placa promediada en una malla gruesa."""
    paso = max(16, n // 11)
    for y in range(paso // 2, n - 2, paso):
        for x in range(paso // 2, n - 2, paso):
            du = float(u[y - 2:y + 3, x - 2:x + 3].mean()) * 14
            dv = float(v[y - 2:y + 3, x - 2:x + 3].mean()) * 14
            L = (du * du + dv * dv) ** 0.5
            if L < 2.5:        # placa casi quieta: sin flecha
                continue
            if L > paso * 0.85:
                du *= paso * 0.85 / L
                dv *= paso * 0.85 / L
            x1, y1 = x + du, y + dv
            ang = np.arctan2(dv, du)
            pa = (x1 - 4 * np.cos(ang - 0.5), y1 - 4 * np.sin(ang - 0.5))
            pb = (x1 - 4 * np.cos(ang + 0.5), y1 - 4 * np.sin(ang + 0.5))
            # trazo blanco debajo y oscuro encima: legible sobre cualquier fondo
            for color, w in (((255, 255, 255, 210), 3), ((25, 25, 30, 255), 1)):
                d.line([(x, y), (x1, y1)], fill=color, width=w)
                d.line([pa, (x1, y1), pb], fill=color, width=w)

def _linea_placa(campo):
    """Difumina y normaliza un campo de intensidad de limite (mismo criterio
    que los bordes rojos del mapa: 2 pasadas de blur + percentil 98)."""
    for _ in range(2):
        campo = 0.2 * (campo + rolly(campo, 1) + rolly(campo, -1)
                       + np.roll(campo, 1, 1) + np.roll(campo, -1, 1))
    return campo / (np.percentile(campo, 98) + 1e-9)

# paleta de relleno por placa (tonos suaves distinguibles, tipo mapa escolar)
_PALETA_PLACAS = np.array([
    (166, 206, 227), (178, 223, 138), (251, 154, 153), (253, 191, 111),
    (202, 178, 214), (255, 255, 153), (141, 211, 199), (190, 186, 218),
    (128, 177, 211), (253, 180, 98), (179, 222, 105), (252, 205, 229),
    (217, 217, 217), (188, 128, 189), (204, 235, 197), (255, 237, 111),
    (137, 195, 165), (222, 165, 164), (169, 169, 219), (196, 156, 148),
], float)

def _compactar(lab):
    _, inv = np.unique(lab, return_inverse=True)
    return inv.reshape(lab.shape)

# --- imposicion de los ejes fisicos como limites de placa (dorsal/fosa/rift) ---
# La particion por velocidad (SLIC + fusion) da placas coherentes pero NO
# garantiza que una dorsal caiga en un borde: con frecuencia una dorsal (o una
# fosa) queda DENTRO de una placa. Geologicamente eso es imposible: un limite
# divergente/convergente ES, por definicion, el borde entre dos placas. Estas
# funciones imponen esa regla como post-proceso solo-render: prolongan los
# cabos sueltos de cada eje hasta la red de limites mas cercana (la
# "continuidad hasta la placa/dorsal mas cercana") y subdividen cada placa por
# los ejes que la cruzan, de modo que todo eje pasa a SER un borde de placa y
# ninguno queda en el interior. NOTA: NO se intento reducir el numero de placas
# fusionando a traves de ejes debiles — ese camino colapsa a UNA placa gigante
# (el mismo fallo documentado en §5.3 de la fusion sin limite real).
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))

def _vecinos4(m):
    """OR de los 4 vecinos (arriba/abajo/izq/der) por SLICING: periodico en X,
    sin envolver en Y (los polos no conectan). Identico a acumular los
    desplazamientos ±1 pero sin el overhead por-llamada de np.roll: acelera
    los BFS y la dilatacion del cierre de red."""
    o = np.zeros_like(m)
    o[1:] |= m[:-1]
    o[:-1] |= m[1:]
    o[:, 1:] |= m[:, :-1]; o[:, :1] |= m[:, -1:]
    o[:, :-1] |= m[:, 1:]; o[:, -1:] |= m[:, :1]
    return o

def _dilata(m, r=1):
    for _ in range(r):
        m = m | _vecinos4(m)
    return m

def _bfs_dist(seed, maxd=None, plano=False):
    """Distancia de manzana (city-block) al conjunto `seed` (periodica en X).
    Con `maxd` se detiene ahi (lo no alcanzado queda en el centinela).
    Con `plano` la malla NO envuelve (para operar en ventanas recortadas)."""
    D = np.full(seed.shape, 1 << 30, np.int64)
    D[seed] = 0
    cur = seed.copy(); d = 0
    while cur.any() and (maxd is None or d < maxd):
        d += 1; nxt = _vecinos4(cur)
        if plano:
            nxt[[0, -1], :] = False; nxt[:, [0, -1]] = False
        nxt &= D > d; D[nxt] = d; cur = nxt
    return D

def _bfs_en(mask, py, px):
    """Distancia geodesica DENTRO de `mask` (4-conexa, periodica solo en X)
    desde un pixel. Para hallar los extremos de un fragmento de eje."""
    D = np.full(mask.shape, 1 << 30, np.int64)
    D[py, px] = 0
    cur = np.zeros_like(mask); cur[py, px] = True
    d = 0
    while cur.any():
        d += 1; nxt = _vecinos4(cur)
        nxt &= mask & (D > d); D[nxt] = d; cur = nxt
    return D

def _extremos(comp):
    """Los dos extremos geodesicos de un fragmento (diametro del grafo,
    por doble BFS): los cabos REALES de la linea, aunque sea corta, curva
    o gruesa — el criterio de masa local fallaba en fragmentos cortos."""
    ys, xs = np.nonzero(comp)
    d0 = _bfs_en(comp, ys[0], xs[0])
    d0[~comp] = -1
    p1 = np.unravel_index(d0.argmax(), comp.shape)
    d1 = _bfs_en(comp, *p1)
    d1[~comp] = -1
    p2 = np.unravel_index(d1.argmax(), comp.shape)
    return p1, p2

def _tangente(comp, py, px, R=5):
    """Direccion saliente del fragmento en un extremo: opuesta al centroide
    de los pixeles del fragmento cercanos al extremo (X periodico, Y plano)."""
    n = comp.shape[0]
    ys, xs = np.nonzero(comp)
    dy = ys - py
    dx = (xs - px + n // 2) % n - n // 2
    sel = (np.abs(dy) <= R) & (np.abs(dx) <= R)
    my, mx = dy[sel].mean(), dx[sel].mean()
    nn = (my * my + mx * mx) ** 0.5
    if nn < 0.3:                     # blob sin direccion clara
        return 0.0, 0.0
    return -my / nn, -mx / nn

def _caminar(py, px, ty, tx, Dt, maxpaso, rumbo=1.5, inercia=0.7):
    """Prolonga un cabo desde (py,px) con direccion inicial (ty,tx): en cada
    paso elige el vecino-8 que minimiza distancia_a_red - rumbo*avance. El
    sesgo de rumbo hace que los DOS cabos de un fragmento salgan en sentidos
    OPUESTOS y toquen la red en puntos distintos -> fragmento + puentes
    forman un corte que separa placas. (El puenteo por camino mas corto
    llevaba ambos cabos al MISMO punto: arbol colgante, sin separacion.)"""
    n = Dt.shape[0]
    path = []
    y, x, dy, dx = py, px, ty, tx
    for _ in range(maxpaso):
        if Dt[y, x] == 0:
            return path, True
        mejor = None
        for sy in (-1, 0, 1):
            for sx in (-1, 0, 1):
                if not sy and not sx:
                    continue
                nrm = 1.4142135 if sy and sx else 1.0
                ny_ = y + sy
                if ny_ < 0 or ny_ >= n:          # no cruzar el polo
                    continue
                nx_ = (x + sx) % n
                s = Dt[ny_, nx_] - rumbo * (sy * dy + sx * dx) / nrm
                if (ny_, nx_) in path:
                    s += 4.0                     # no repisar el propio camino
                if mejor is None or s < mejor[0]:
                    mejor = (s, ny_, nx_, sy / nrm, sx / nrm)
        if mejor is None:                        # acorralado contra el polo
            break
        _, y, x, sy, sx = mejor
        dy, dx = inercia * dy + (1 - inercia) * sy, inercia * dx + (1 - inercia) * sx
        nn = (dy * dy + dx * dx) ** 0.5 + 1e-9
        dy, dx = dy / nn, dx / nn
        path.append((y, x))
    return path, bool(Dt[y, x] == 0)

def _masa(m, R=4):
    """Masa de linea en un disco de radio R alrededor de cada pixel."""
    f = m.astype(np.float32); acc = np.zeros_like(f)
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            if dy * dy + dx * dx <= R * R:
                acc += np.roll(rolly(f, dy), dx, 1)
    return acc

def _zona(comp, margen):
    """Ventana centrada en un fragmento: desplazamiento que lo centra
    (periodico en X; en Y el centroide es lineal y el corrimiento rellena con
    vacio, no envuelve) y recorte cuadrado que lo contiene con margen. Operar
    en la ventana evita BFS de mapa completo por cada fragmento."""
    n = comp.shape[0]
    ys, xs = np.nonzero(comp)
    cy = int(ys.mean())
    cx = int((np.angle(np.exp(2j * np.pi * xs / n).mean()) % (2 * np.pi))
             * n / (2 * np.pi))
    sy, sx = n // 2 - cy, n // 2 - cx
    dy = np.abs(ys + sy - n // 2).max()
    dx = np.abs((xs + sx) % n - n // 2).max()
    h = min(n // 2, int(max(dy, dx)) + margen)
    return sy, sx, slice(n // 2 - h, n // 2 + h)

def _rec(m, sy, sx, sl):
    """Recorte de la ventana: X envuelve (np.roll); Y se desplaza SIN envolver
    y rellena con vacio (no hay mapa al otro lado de los polos)."""
    g = np.roll(m, sx, 1)
    out = np.zeros_like(g)
    if sy > 0:
        out[sy:] = g[:-sy] if sy < g.shape[0] else 0
    elif sy < 0:
        out[:sy] = g[-sy:]
    else:
        out = g
    return out[sl, sl]

def _cabos(comp, acc):
    """Puntos de arranque de los puentes de un fragmento: TODAS las puntas de
    rama (pixeles con poca masa de linea en su disco, umbral relativo a la
    mediana DEL fragmento — una red ramificada tiene mas de dos cabos) mas
    los dos extremos geodesicos como respaldo (una banda gruesa o corta puede
    no tener ninguna punta por masa local)."""
    tips = comp & (acc < 0.55 * np.median(acc[comp]))
    reps = []
    tl = label_components(tips)
    for t in np.unique(tl[tl >= 0]):
        ys, xs = np.nonzero(tl == t)
        k = len(ys) // 2
        reps.append((int(ys[k]), int(xs[k])))
    n = comp.shape[0]
    for (py, px) in _extremos(comp):
        cerca = any(abs(py - y)
                    + min(abs(px - x), n - abs(px - x)) <= 4
                    for (y, x) in reps)
        if not cerca:
            reps.append((py, px))
    return reps

def _puentes_de(comp, red, acc, maxpaso, rumbo=1.5, inercia=0.7):
    """Puentes desde todos los cabos de un fragmento hasta `red`, calculados
    en una ventana local. Devuelve pixeles en coordenadas del mapa."""
    n = comp.shape[0]
    sy, sx, sl = _zona(comp, maxpaso + 6)
    compz = _rec(comp, sy, sx, sl)
    Dt = _bfs_dist(_rec(red, sy, sx, sl), maxd=maxpaso + 2, plano=True)
    accz = _rec(acc, sy, sx, sl)
    a = sl.start
    out = []
    for (py, px) in _cabos(compz, accz):
        ty, tx = _tangente(compz, py, px)
        camino, _ = _caminar(py, px, ty, tx, Dt, maxpaso, rumbo, inercia)
        # de vuelta a coords del mapa: X envuelve; Y fuera de rango (mas alla
        # del polo) se descarta
        out += [(a + yy - sy, (a + xx - sx) % n) for yy, xx in camino
                if 0 <= a + yy - sy < n]
    return out

def _cerrar_red(ejes, borde, maxpaso):
    """Cierra la red de limites: cada fragmento de eje se prolonga por todos
    sus cabos hasta la red mas cercana (OTRO fragmento de eje o un borde de
    placa). Es la 'continuidad hasta la dorsal/placa mas cercana': una dorsal
    partida en tramos se une en una linea continua y los cabos restantes se
    sueldan a la red de bordes, de modo que cada eje separe dos placas."""
    acc = _masa(ejes)
    comps = label_components(ejes)
    puentes = np.zeros_like(ejes)
    red = borde | ejes
    for cid in np.unique(comps[comps >= 0]):
        comp = comps == cid
        if comp.sum() < 3:
            continue                             # ruido puntual sin direccion
        for yy, xx in _puentes_de(comp, red & ~comp, acc, maxpaso):
            puentes[yy, xx] = True
    return ejes | puentes

def _subdividir(L, cortes, ids=None):
    """Parte cada placa por los ejes que la cruzan: quita los pixeles de eje,
    re-etiqueta las componentes conexas resultantes (los dos flancos de una
    dorsal que la cruza entera pasan a ser placas distintas) y re-asigna los
    pixeles del eje al vecino mas cercano. La dorsal deja de estar dentro de
    una placa y pasa a SER el borde entre las dos. Con `ids` solo se
    re-particionan esas placas (reintento barato tras la verificacion)."""
    lab = np.full(L.shape, -1, np.int64)
    sig = int(L.max()) + 1
    if ids is None:
        todos = range(sig)
    else:
        todos = sorted(ids)
        fuera = ~np.isin(L, todos)
        lab[fuera] = L[fuera]
    seeds = np.where(~cortes, L, -1)
    for i in todos:
        cc = label_components(seeds == i)
        for cid in np.unique(cc[cc >= 0]):
            lab[cc == cid] = sig; sig += 1
    while (lab < 0).any():
        prog = False
        for dy, dx in _DIRS:
            vec = rolly(lab, dy) if dx == 0 else np.roll(lab, dx, 1)
            take = (lab < 0) & (vec >= 0)
            if take.any():
                lab[take] = vec[take]; prog = True
        if not prog:
            break
    return _compactar(lab)

def _ejes_fisicos(crust):
    """Mascara de los ejes que son limite de placa por definicion fisica:
    dorsal (divergente sobre oceano), fosa (convergente con subduccion) y
    rift (divergente sobre continente). Los MISMOS campos que dibuja el mapa
    (§5.3) y usa la simulacion (§4.10-4.11)."""
    tierra = crust.F > 0.5
    fosa = getattr(crust, "fosa", crust.trench)   # eje delgado de la fosa
    return (((crust.dorsal > 0.3) & ~tierra)
            | ((_linea_placa(fosa) > 0.5) & ~tierra)
            | ((crust.rift > 0.008) & tierra))

# memoria entre frames del mapa de placas (solo render): centroides SLIC del
# frame anterior (arranque en caliente -> particion estable) y colores por
# placa (heredados por solapamiento -> sin parpadeo en el GIF)
_SEG_PREV = {}

def _segmentar_placas(crust, boundary):
    """Particion del mapa en placas desde el campo de VELOCIDAD (la
    definicion fisica: una placa es una region que se mueve coherente).

    1. Superpixeles tipo SLIC sobre (u, v, posicion) en malla 64x64: ~36
       regiones compactas cuyas fronteras caen donde la velocidad salta.
    2. Fusion: dos regiones vecinas se unen si sus velocidades medias son
       similares Y su frontera comun no tiene deformacion real (|div|+shear
       bajo). El oceano suave coalesce en placas grandes; solo sobreviven
       los bordes fisicos (dorsales, fosas, saltos de velocidad) -> pocas
       placas grandes + medianas + microplacas, como en la Tierra.
    Devuelve (etiquetas nxn, bordes bool). Solo render: no toca la fisica."""
    n = boundary.shape[0]
    m = min(64, n)
    u = sample_nearest(crust.u_vis, m, m)
    v = sample_nearest(crust.v_vis, m, m)
    # limite real = deformacion + los ejes fisicos (dorsal, fosa, rift).
    # La fusion solo respeta fronteras con limite real: todo lo que hay
    # entre la dorsal y el continente (margen pasivo, sin fosa) es parte de
    # la MISMA placa, y el interior de un continente tambien, salvo que una
    # colision o un rift de pluma nueva lo este partiendo
    fis = (np.clip(crust.dorsal, 0, 1) + np.clip(crust.rift / 0.008, 0, 1)
           + np.clip(_linea_placa(getattr(crust, "fosa", crust.trench)), 0, 1))
    for _ in range(2):
        fis = 0.2 * (fis + rolly(fis, 1) + rolly(fis, -1)
                     + np.roll(fis, 1, 1) + np.roll(fis, -1, 1))
    defo = sample_nearest(_linea_placa(boundary) + 3.0 * fis, m, m)
    # media movil exponencial de lo que ve el segmentador: la velocidad
    # instantanea fluctua y hace parpadear la particion entre frames; la
    # EMA (tau ~2.5 frames) la vuelve un mapa que evoluciona despacio
    if _SEG_PREV.get("m") == m:
        u = 0.6 * _SEG_PREV["uema"] + 0.4 * u
        v = 0.6 * _SEG_PREV["vema"] + 0.4 * v
        defo = 0.6 * _SEG_PREV["dema"] + 0.4 * defo
    _SEG_PREV["uema"], _SEG_PREV["vema"], _SEG_PREV["dema"] = u, v, defo
    un = u / (u.std() + 1e-9)
    vn = v / (v.std() + 1e-9)
    # --- 1. SLIC: asignacion iterativa a centroides (velocidad + posicion) ---
    K, lam = 36, 0.8
    S = m / np.sqrt(K)
    yy, xx = np.meshgrid(np.arange(m), np.arange(m), indexing="ij")
    if _SEG_PREV.get("m") == m:
        # arranque en caliente: los centroides del frame anterior ya estan
        # cerca de la solucion -> particion temporalmente estable
        cys, cxs = _SEG_PREV["cys"].copy(), _SEG_PREV["cxs"].copy()
        cu, cv = _SEG_PREV["cu"].copy(), _SEG_PREV["cv"].copy()
        iters = 4
    else:
        lado = int(round(np.sqrt(K)))
        cy = (np.arange(lado) + 0.5) * m / lado
        cys, cxs = np.meshgrid(cy, cy, indexing="ij")
        cys, cxs = cys.ravel().copy(), cxs.ravel().copy()
        cu = np.array([un[int(y) % m, int(x) % m] for y, x in zip(cys, cxs)])
        cv = np.array([vn[int(y) % m, int(x) % m] for y, x in zip(cys, cxs)])
        iters = 8
    for _ in range(iters):
        D = np.empty((K, m, m))
        for k in range(K):
            dy = np.abs(yy - cys[k])              # Y lineal: no envuelve
            dx = np.abs(xx - cxs[k]); dx = np.minimum(dx, m - dx)
            D[k] = ((un - cu[k]) ** 2 + (vn - cv[k]) ** 2
                    + lam * (dy ** 2 + dx ** 2) / S ** 2)
        asg = D.argmin(0)
        for k in range(K):
            sel = asg == k
            if not sel.any():
                continue
            cu[k] = un[sel].mean(); cv[k] = vn[sel].mean()
            # centroide: media circular SOLO en X; lineal en Y (sin polos)
            ax_ = 2 * np.pi * xx[sel] / m
            cys[k] = float(yy[sel].mean())
            cxs[k] = (np.angle(np.exp(1j * ax_).mean()) % (2 * np.pi)) * m / (2 * np.pi)
    _SEG_PREV.update(m=m, cys=cys, cxs=cxs, cu=cu, cv=cv)
    # separar componentes conexas de cada cluster y absorber esquirlas
    lab = np.full((m, m), -1, np.int64)
    sig = 0
    for k in np.unique(asg):
        cc = label_components(asg == k)
        for cid in np.unique(cc[cc >= 0]):
            lab[cc == cid] = sig
            sig += 1
    ids, cnt = np.unique(lab, return_counts=True)
    lab = np.where(np.isin(lab, ids[cnt < 10]), -1, lab)
    while (lab < 0).any():
        for ax in (0, 1):
            for sh in (1, -1):
                vec = rollg(lab, sh, ax)
                lab = np.where((lab < 0) & (vec >= 0), vec, lab)
    lab = _compactar(lab)
    # --- 2. fusion de vecinos coherentes (union-find) ---
    # tolerancias: la de deformacion manda (sin limite real en la frontera,
    # dos regiones son la misma placa aunque sus velocidades difieran algo);
    # la de velocidad solo evita fusionar a traves de saltos cinematicos
    # enormes que la deformacion muestreada pudiera no captar
    TOLV, TOLD = 1.5, 0.5
    for _ in range(6):
        nl = lab.max() + 1
        mu = np.array([un[lab == i].mean() for i in range(nl)])
        mv = np.array([vn[lab == i].mean() for i in range(nl)])
        sums, cnts = {}, {}
        for ax in (0, 1):
            l2 = rollg(lab, 1, ax)
            sel = lab != l2
            for i, j, dd in zip(lab[sel], l2[sel], defo[sel]):
                key = (min(i, j), max(i, j))
                sums[key] = sums.get(key, 0.0) + dd
                cnts[key] = cnts.get(key, 0) + 1
        padre = list(range(nl))
        def raiz(x):
            while padre[x] != x:
                padre[x] = padre[padre[x]]
                x = padre[x]
            return x
        fusiones = 0
        for (i, j), s in sums.items():
            dv = np.hypot(mu[i] - mu[j], mv[i] - mv[j])
            if dv < TOLV and s / cnts[(i, j)] < TOLD:
                ri, rj = raiz(i), raiz(j)
                if ri != rj:
                    padre[max(ri, rj)] = min(ri, rj)
                    fusiones += 1
        if not fusiones:
            break
        lab = _compactar(np.array([raiz(i) for i in range(nl)])[lab])
    # upsample suave: indicador bilineal por placa + argmax -> los bordes
    # salen como curvas, no la escalera del vecino mas cercano 64->n
    mejor = np.full((n, n), -1.0)
    L = np.zeros((n, n), np.int64)
    for i in range(lab.max() + 1):
        p = upsample((lab == i).astype(float), n, n)
        gana = p > mejor
        L[gana] = i
        mejor[gana] = p[gana]
    borde = np.zeros((n, n), bool)
    for ax in (0, 1):
        borde |= L != rollg(L, 1, ax)
    # --- 3. los ejes fisicos SON limites de placa: se imponen aqui ---
    # La velocidad no basta para separar los dos flancos de una dorsal joven o
    # de baja apertura, asi que la dorsal queda dentro de una placa. Se cierra
    # la red prolongando los DOS extremos de cada fragmento hasta la red mas
    # cercana y se subdivide por los ejes; luego se VERIFICA fragmento por
    # fragmento y el que aun no separe dos placas se prolonga RECTO por su
    # propia direccion hasta la red -> ninguna dorsal/fosa queda en el interior.
    ejes = _ejes_fisicos(crust)
    if ejes.any():
        # motas de menos de 6 px: ruido numerico, no un eje (sin direccion
        # definible, sus puentes degeneran en arboles colgantes que no
        # separan nada); se excluyen de la red de cortes
        comps0 = label_components(ejes)
        ids0, cnt0 = np.unique(comps0[comps0 >= 0], return_counts=True)
        ejes &= ~np.isin(comps0, ids0[cnt0 < 6])
    if ejes.any():
        maxpaso = max(24, n // 6)
        ejes_d = _dilata(ejes, 1)
        cortes = _cerrar_red(ejes_d, borde, maxpaso)
        L = _subdividir(L, cortes)
        # verificacion: los pixeles de cada fragmento se reasignaron a las
        # placas que lo flanquean; si todos cayeron en UNA placa el corte fue
        # un arbol colgante y no separo nada -> reintento con paso recto
        borde = np.zeros((n, n), bool)
        for ax in (0, 1):
            borde |= L != rollg(L, 1, ax)
        comps = label_components(ejes_d)
        Db = _bfs_dist(borde, maxd=5)
        acc = _masa(ejes_d)
        extra = np.zeros_like(ejes_d)
        fallidas = set()
        for cid in np.unique(comps[comps >= 0]):
            comp = comps == cid
            # el fragmento separa placas si (casi) todo el queda pegado al
            # borde final; si no, el corte fue un arbol colgante (o solo lo
            # cruza un borde ajeno) y se prolonga RECTO hasta la red
            if comp.sum() < 3 or (Db[comp] <= 3).mean() >= 0.85:
                continue
            red = borde | (cortes & ~comp)
            for yy, xx in _puentes_de(comp, red, acc, 2 * maxpaso,
                                      rumbo=6.0, inercia=0.9):
                extra[yy, xx] = True
            fallidas.update(int(i) for i in np.unique(L[comp]))
        if fallidas:
            L = _subdividir(L, cortes | extra, ids=fallidas)
        borde = np.zeros((n, n), bool)
        for ax in (0, 1):
            borde |= L != rollg(L, 1, ax)
    return L, borde

def _colores_de_placas(L):
    """Color por placa, estable entre frames: cada placa hereda el color de
    la placa del frame anterior con la que mas se solapa (>50%); si es nueva
    recibe uno por su centroide cuantizado. Sin esto el GIF parpadea."""
    prevL = _SEG_PREV.get("L")
    prevcol = _SEG_PREV.get("col", {})
    colores = np.zeros(L.shape + (3,))
    col = {}
    usados = set()
    ids, cnts = np.unique(L, return_counts=True)
    for pid in ids[np.argsort(-cnts)]:        # las grandes eligen primero
        sel = L == pid
        c = None
        if prevL is not None and prevL.shape == L.shape:
            vals, vc = np.unique(prevL[sel], return_counts=True)
            j = int(vals[vc.argmax()])
            # herencia pegajosa; una placa que se parte no duplica color en
            # sus dos mitades (la mayor hereda, la menor recibe uno nuevo)
            if vc.max() / sel.sum() > 0.35 and j in prevcol and j not in usados:
                c = prevcol[j]
                usados.add(j)
        if c is None:
            ys, xs = np.nonzero(sel)
            cy, cx = int(ys.mean()) // 16, int(xs.mean()) // 16
            c = tuple(_PALETA_PLACAS[(cy * 31 + cx * 17) % len(_PALETA_PLACAS)])
        col[pid] = c
        colores[sel] = c
    _SEG_PREV["L"] = L
    _SEG_PREV["col"] = col
    return colores

def render_placas(crust, boundary, elev):
    """Mapa tectonico. El dominio se TESELA en placas (regiones cerradas,
    grandes y pequenas, cada una con su color) y los limites se clasifican
    POR TIPO desde los mismos campos que usa la fisica: divergente sobre
    oceano = dorsal, divergente sobre continente = rift, convergente con
    fondo viejo = fosa; el resto de bordes (transformantes, suturas) queda
    en rojo. Ademas: costas, cordilleras y flechas de deriva. La leyenda
    vive en la pagina web (web.html), no en la imagen."""
    n = elev.shape[0]
    img = np.empty(elev.shape + (3,))
    for ch in range(3):
        img[..., ch] = np.interp(elev, HYPSO[:, 0], HYPSO[:, ch + 1])
    img = img * 0.30 + np.array([235.0, 235.0, 230.0]) * 0.70  # fondo palido
    # teselacion en placas: relleno translucido por placa
    L, borde = _segmentar_placas(crust, boundary)
    img = img * 0.68 + _colores_de_placas(L) * 0.32
    tierra = crust.F > 0.5
    interior = tierra
    for ax in (0, 1):
        for sh in (1, -1):
            interior = interior & rollg(tierra, sh, ax)
    img[tierra & ~interior] = (95, 95, 95)          # linea de costa
    img[elev > 0.20] = (115, 62, 25)                # cadenas montanosas
    # tipos de limite desde los MISMOS campos que usa la simulacion, pero
    # RECORTADOS al borde de placa: la subdivision por ejes (_segmentar_placas)
    # ya puso un borde sobre cada dorsal/fosa/rift, asi que se dibujan solo
    # donde coinciden con ese borde. Un tramo que no llego a separar placas (un
    # cabo residual que el puente no cerro) NO se pinta: una dorsal jamas
    # aparece dentro de una placa.
    en_borde = _dilata(borde, 2)
    dorsal_m = (crust.dorsal > 0.3) & ~tierra & en_borde
    rift_m = (crust.rift > 0.008) & tierra & en_borde
    fosa_m = (_linea_placa(getattr(crust, "fosa", crust.trench)) > 0.5) & ~tierra & en_borde
    # el limite ES la dorsal y ES la fosa: el contorno generico de la
    # teselacion se borra cerca de esos ejes para no dibujar una linea
    # roja paralela al lado del limite verdadero
    lineas = dorsal_m | rift_m | fosa_m
    cerca = lineas
    for ax in (0, 1):
        acc = cerca
        for sh in range(1, 7):
            acc = acc | rollg(cerca, sh, ax) | rollg(cerca, -sh, ax)
        cerca = acc
    img[borde & ~cerca] = (205, 60, 45)   # transformantes, suturas
    img[dorsal_m] = (240, 165, 25)        # dorsal: el eje es el limite
    img[rift_m] = (255, 96, 0)            # rift continental
    img[fosa_m] = (105, 25, 140)          # fosa: la fosa es el limite
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im, "RGBA")
    _flechas(d, crust.u_vis, crust.v_vis, n)
    return im

# ---------------- almacenamiento de mundos ----------------
# cada mundo vive en mundos/<nombre>/: config.json con todos los parametros,
# base.npz (textura de detalle) y frames/PASO.npz con el estado COMPLETO de
# la simulacion por frame -> cualquier frame se puede re-renderizar o usarse
# como punto de partida para continuar la simulacion.
# estado de la simulacion: se guarda en float64 SIN redondear — el sistema
# tiene umbrales discretos (etiquetado de placas, percentiles) que amplifican
# cualquier redondeo, y con f32 una continuacion diverge de la corrida
# original en ~100 pasos; con f64 es bit-exacta. trench es estado: alimenta
# el slab pull (sink) del paso siguiente
# dorsal es estado: su memoria (persistencia) entra en el paso siguiente; una
# continuacion debe recuperarla o la dorsal renaceria de cero y parpadearia
CAMPOS_ESTADO = ("C", "F", "A", "Pu", "Pv", "Qu", "Qv", "D", "trench", "dorsal",
                 "open_mem")

def _parametros_de(args):
    claves = ("tiempo", "cada", "ms", "semilla", "resolucion", "detalle",
              "velocidad", "mar", "continentes", "plumas", "erosion",
              "empuje", "momento", "rigidez", "deriva", "anos_paso",
              "temperatura", "precipitaciones")
    p = {k: getattr(args, k) for k in claves}
    # los flags de clima son None por defecto (para distinguir "no dado" en
    # --detallar); en el config del mundo guardamos los defaults de modulo
    if p["temperatura"] is None:
        p["temperatura"] = TEMPERATURA
    if p["precipitaciones"] is None:
        p["precipitaciones"] = PRECIPITACIONES
    return p

def _aplicar_parametros(p):
    global NX, NY, VEL_SCALE, SEA_LEVEL, CONT_UMBRAL, PLUME_EVERY
    global EROSION, RIDGE_PUSH, MOMENTUM, RIGID, DERIVA, ANOS_POR_PASO
    global TEMPERATURA, PRECIPITACIONES
    NX = NY = int(p["resolucion"])
    VEL_SCALE, SEA_LEVEL = float(p["velocidad"]), float(p["mar"])
    CONT_UMBRAL = float(p["continentes"])
    PLUME_EVERY, EROSION = max(int(p["plumas"]), 1), float(p["erosion"])
    RIDGE_PUSH, MOMENTUM = float(p["empuje"]), float(p["momento"])
    RIGID = min(max(float(p["rigidez"]), 0.0), 1.0)
    # .get: los mundos guardados antes de este dial no traen la clave
    DERIVA = float(p.get("deriva", DERIVA))
    ANOS_POR_PASO = float(p.get("anos_paso", ANOS_POR_PASO))
    # diales de clima: mundos guardados antes de la capa climatica no los traen
    TEMPERATURA = float(p.get("temperatura", TEMPERATURA))
    # los mundos viejos guardan el dial con la clave "humedad"
    PRECIPITACIONES = float(
        p.get("precipitaciones", p.get("humedad", PRECIPITACIONES)))

def _crear_mundo_en(carpeta, params, nombre, crust=None):
    """Crea la estructura de un mundo (estado reanudable) en `carpeta`:
    config.json (parametros) + frames/ (estado por checkpoint) + base.npz (la
    textura de detalle y la masa continental, constantes de la corrida)."""
    from datetime import datetime
    carpeta = Path(carpeta)
    (carpeta / "frames").mkdir(parents=True, exist_ok=True)
    cfg = {"nombre": nombre,
           "creado": datetime.now().isoformat(timespec="seconds"),
           "version": 1, "parametros": params}
    (carpeta / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    if crust is not None:
        np.savez_compressed(carpeta / "base.npz", D0=crust.D0,
                            F_total=crust.F_total)
    return carpeta

def _crear_mundo(args):
    from datetime import datetime
    p = _parametros_de(args)
    nombre = f"{Path(args.salida).name}_s{p['semilla']}_{datetime.now():%Y%m%d-%H%M%S}"
    return _crear_mundo_en(Path("mundos") / nombre, p, nombre)

def _cargar_estado(carpeta, npz_path):
    """Reconstruye (mantle, crust, sink) desde el estado completo guardado en
    `npz_path` (+ base.npz de `carpeta`) y deja el rng global donde iba. Es el
    inverso de guardar_frame; lo usan continuar y extrapolar. Devuelve tambien
    el paso del checkpoint cargado."""
    global rng
    carpeta = Path(carpeta)
    d = np.load(npz_path)
    meta = json.loads(d["meta"].item())
    rng = np.random.default_rng(0)   # temporal: los constructores consumen rng
    mantle, crust = Mantle(), Crust()
    mantle.T = d["T"].astype(float)
    mantle.t = meta["t"]
    mantle.plumes = meta["plumes"]
    for k in CAMPOS_ESTADO:
        # mundos guardados antes de un dial no traen su campo: se dejan como
        # los sembro el constructor y el primer paso los reconstruye
        if k in d.files:
            setattr(crust, k, d[k].astype(float))
    crust.trench = d["trench"].astype(float)
    # derivados de render (f16 en el npz): un paso de simulacion los recalcula,
    # pero detallar puede renderizar el cuadro EXACTO de un checkpoint sin
    # avanzar ninguno — ahi hacen falta tal como quedaron guardados
    for k, attr in (("fosa", "fosa"), ("foreland", "foreland"), ("rift", "rift"),
                    ("va", "volcano_arc"), ("vh", "volcano_hot")):
        if k in d.files:
            setattr(crust, attr, d[k].astype(float))
    base = np.load(carpeta / "base.npz")
    crust.D0 = base["D0"].astype(float)
    crust.F_total = float(base["F_total"])
    rng = np.random.default_rng()
    rng.bit_generator.state = meta["rng"]   # el azar sigue donde iba
    sink = upsample(crust.trench, MY, MX)
    return mantle, crust, sink, int(meta.get("paso", int(Path(npz_path).stem)))

def guardar_frame(carpeta, paso, mantle, crust, boundary):
    """Estado completo de un frame: reproducible y reanudable."""
    meta = {"paso": int(paso), "t": int(mantle.t),
            "plumes": [{"y": float(q["y"]), "x": float(q["x"]),
                        "dy": float(q["dy"]), "dx": float(q["dx"]),
                        "age": int(q["age"]), "life": int(q["life"])}
                       for q in mantle.plumes],
            "rng": rng.bit_generator.state}
    f16 = np.float16
    np.savez_compressed(
        carpeta / "frames" / f"{paso:06d}.npz",
        meta=json.dumps(meta), T=mantle.T,
        **{k: getattr(crust, k) for k in CAMPOS_ESTADO},
        # derivados solo para re-renderizar (media precision basta); dorsal ya
        # va en CAMPOS_ESTADO (f64). fosa = eje delgado de la fosa para el mapa
        foreland=crust.foreland.astype(f16), fosa=crust.fosa.astype(f16),
        rift=crust.rift.astype(f16),
        va=crust.volcano_arc.astype(f16), vh=crust.volcano_hot.astype(f16),
        boundary=boundary.astype(f16),
        u=crust.u_vis.astype(f16), v=crust.v_vis.astype(f16))

def _simular(mantle, crust, pasos, cada, carpeta=None, detalle=None,
             paso0=0, sink=None, paso_estado=None):
    """Corre la simulacion. Si detalle no es None devuelve los frames
    renderizados (mapa, placas, manto) + el timeline por cuadro. Si carpeta no
    es None guarda el ESTADO completo: en cada frame si paso_estado es None
    (mundo --datos), o solo cada paso_estado pasos si se da (checkpoints del
    reproductor, para extrapolar desde cualquier cuadro sin guardar todo)."""
    frames_m, frames_p, frames_ma, frames_c, boundary = [], [], [], [], None
    meta_frames = []
    checkpoints = []
    for i in range(paso0, paso0 + pasos):
        u, v = mantle.step(sink)
        crust.sea = SEA_LEVEL + nivel_mar(i)   # eustasia del paso actual
        boundary = crust.step(u, v, mantle.hot)
        sink = upsample(crust.trench, MY, MX)  # la losa fria ancla la bajada
        if i % cada == 0:
            if detalle is not None:
                elev = crust.elevation(detalle)
                vol = ((crust.volcano_arc, 0.003, 3), (crust.volcano_hot, 0.012, 2))
                frames_m.append(render(elev, boundary, vol))
                frames_p.append(render_placas(crust, boundary, elev))
                frames_ma.append(render_manto(mantle.T, mantle.plumes))
                # clima: funcion PURA del elev ya calculado (mismos diales para
                # todo el mundo). Corre DESPUES de la fisica y no toca el rng
                # global -> la continuacion de mundos sigue bit-exacta
                campos = clima.simular_clima(elev, temperatura=TEMPERATURA,
                                             precipitaciones=PRECIPITACIONES)
                frames_c.append(clima.render_clima(campos, elev))
                # timeline por frame: tiempo geologico y valores intermedios
                # (nivel del mar, nº de plumas, fraccion de tierra) que el
                # reproductor web lee para rotular cada cuadro coordinado
                es_cp = carpeta is not None and (
                    paso_estado is None or i % paso_estado == 0)
                # resumen climatico del cuadro para el reloj web: temperatura
                # media del aire sobre tierra (NaN-safe si el mundo es oceano
                # total) y fraccion de superficie helada
                tierra_c = elev > 0
                tmedia = (round(float(campos["tair"][tierra_c].mean()), 3)
                          if tierra_c.any() else None)
                meta_frames.append({
                    "paso": int(i), "ma": round(i * ANOS_POR_PASO, 3),
                    "mar": round(float(crust.sea), 4),
                    "plumas": len(mantle.plumes),
                    "tierra": round(float((elev > 0).mean()), 4),
                    "clima": {"tmedia": tmedia,
                              "hielo": round(float((campos["hielo"] > 0.5).mean()), 4)},
                    "checkpoint": bool(es_cp)})
            if carpeta is not None and (paso_estado is None or i % paso_estado == 0):
                guardar_frame(carpeta, i, mantle, crust, boundary)
                checkpoints.append(int(i))
        rel = i - paso0
        if rel % 200 == 0 and rel:
            print(f"  paso {rel}/{pasos}...")
    return frames_m, frames_p, frames_ma, frames_c, boundary, meta_frames

def _guardar_gifs(carpeta, frames_m, frames_p, frames_ma, frames_c, ms):
    frames_m[-1].save(carpeta / "mapa_final.png")
    for nombre, fr in (("mapa.gif", frames_m), ("placas.gif", frames_p),
                       ("manto.gif", frames_ma), ("clima.gif", frames_c)):
        fr[0].save(carpeta / nombre, save_all=True, append_images=fr[1:],
                   duration=ms, loop=0)

def _guardar_reproductor(salida, frames_m, frames_p, frames_ma, frames_c,
                         meta_frames, cada, ms, mundo_nombre=None):
    """Guarda, en la carpeta de resultados, los CUADROS individuales (PNG de
    mapa/placas/manto por frame) y un JSON con la configuracion y el timeline
    (tiempo Ma + valores intermedios por cuadro). Es lo que permite el
    reproductor web recorrer el mapa cuadro a cuadro —adelante, reversa, pausa
    en un punto dado— con el reloj geologico coordinado; el GIF no se puede
    recorrer en el navegador. `mundo_nombre` es la carpeta de checkpoints
    (estado completo) desde la que la web extrapola. `salida` = prefijo de -o."""
    base = Path(f"{salida}_cuadros")
    if base.exists():
        shutil.rmtree(base)               # una tanda limpia de cuadros por corrida
    base.mkdir(parents=True, exist_ok=True)
    for f, (fm, fp, fma, fc) in enumerate(
            zip(frames_m, frames_p, frames_ma, frames_c)):
        fm.save(base / f"mapa_{f:04d}.png")
        fp.save(base / f"placas_{f:04d}.png")
        fma.save(base / f"manto_{f:04d}.png")
        fc.save(base / f"clima_{f:04d}.png")
    cfg = {"anos_por_paso": ANOS_POR_PASO, "cada": int(cada), "ms": int(ms),
           "nframes": len(meta_frames), "cuadros": base.name,
           "mundo": mundo_nombre, "frames": meta_frames}
    Path(f"{salida}_repro.json").write_text(
        json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return len(meta_frames)

def reconstruir(ruta):
    """Re-renderiza mapa.gif y placas.gif desde los datos guardados."""
    carpeta = Path(ruta)
    cfg = json.loads((carpeta / "config.json").read_text())
    p = cfg["parametros"]
    _aplicar_parametros(p)
    ficheros = sorted((carpeta / "frames").glob("*.npz"))
    if not ficheros:
        raise SystemExit(f"no hay frames guardados en {carpeta}/frames")
    frames_m, frames_p, frames_ma, frames_c = [], [], [], []
    for fz in ficheros:
        d = np.load(fz)
        c = Crust.__new__(Crust)   # cascaron: solo los campos del render
        for k in ("C", "F", "A", "D"):
            setattr(c, k, d[k].astype(float))
        c.trench = d["trench"].astype(float)
        c.foreland = d["foreland"].astype(float)
        c.dorsal = d["dorsal"].astype(float)
        # fosa: eje delgado; mundos previos a este campo caen a la banda trench
        c.fosa = d["fosa"].astype(float) if "fosa" in d.files else c.trench
        c.rift = d["rift"].astype(float)
        c.volcano_arc = d["va"].astype(float)
        c.volcano_hot = d["vh"].astype(float)
        c.u_vis, c.v_vis = d["u"].astype(float), d["v"].astype(float)
        boundary = d["boundary"].astype(float)
        meta = json.loads(d["meta"].item())
        paso = meta.get("paso", int(fz.stem))
        c.sea = SEA_LEVEL + nivel_mar(paso)   # mismo nivel eustatico que en vivo
        elev = c.elevation(p["detalle"])
        vol = ((c.volcano_arc, 0.003, 3), (c.volcano_hot, 0.012, 2))
        frames_m.append(render(elev, boundary, vol))
        frames_p.append(render_placas(c, boundary, elev))
        frames_ma.append(render_manto(d["T"].astype(float), meta["plumes"]))
        # clima: derivado puro, no se guarda en el npz -> se recalcula desde el
        # elev de este cuadro con los diales del mundo (.get para mundos viejos)
        campos = clima.simular_clima(
            elev, temperatura=float(p.get("temperatura", TEMPERATURA)),
            precipitaciones=float(
                p.get("precipitaciones", p.get("humedad", PRECIPITACIONES))))
        frames_c.append(clima.render_clima(campos, elev))
    _guardar_gifs(carpeta, frames_m, frames_p, frames_ma, frames_c, p["ms"])
    print(f"-> {carpeta}/mapa.gif, placas.gif, manto.gif, clima.gif y "
          f"mapa_final.png ({len(frames_m)} frames reconstruidos)")

def continuar(ruta, pasos, desde=None):
    """Retoma la simulacion desde un frame guardado (el ultimo por defecto)
    y reconstruye ambos GIFs. Con --desde se parte de ese paso y los frames
    posteriores se descartan (la historia se reescribe desde ahi)."""
    import time
    carpeta = Path(ruta)
    cfg = json.loads((carpeta / "config.json").read_text())
    p = cfg["parametros"]
    _aplicar_parametros(p)
    disponibles = {int(f.stem): f for f in (carpeta / "frames").glob("*.npz")}
    if not disponibles:
        raise SystemExit(f"no hay frames guardados en {carpeta}/frames")
    paso0 = max(disponibles) if desde is None else desde
    if paso0 not in disponibles:
        raise SystemExit(f"no existe el frame del paso {paso0}; hay frames "
                         f"cada {p['cada']} pasos hasta {max(disponibles)}")
    if desde is not None:
        for q, f in disponibles.items():
            if q > desde:
                f.unlink()
    mantle, crust, sink, paso0 = _cargar_estado(carpeta, disponibles[paso0])
    print(f"continuando '{cfg['nombre']}' desde el paso {paso0} (+{pasos} pasos)")
    t0 = time.time()
    _simular(mantle, crust, pasos, p["cada"], carpeta, paso0=paso0 + 1, sink=sink)
    print(f"{pasos} pasos en {time.time()-t0:.1f}s; reconstruyendo GIFs...")
    from datetime import datetime
    cfg.setdefault("continuaciones", []).append(
        {"desde": paso0, "pasos": pasos,
         "fecha": datetime.now().isoformat(timespec="seconds")})
    (carpeta / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    reconstruir(carpeta)

def extrapolar(mundo, desde_paso, pasos, salida, ms=None, detalle=None,
               cada=None, cada_estado=10):
    """Extrapolacion NO destructiva desde un solo cuadro. Carga el checkpoint
    completo mas cercano <= desde_paso, avanza en SILENCIO (bit-exacto) hasta
    reproducir el estado exacto de ese cuadro y luego simula `pasos` mas,
    escribiendo un reproductor NUEVO (cuadros + repro.json + su propio mundo de
    checkpoints) en el prefijo `salida`. No toca el mundo de origen: la
    evolucion original queda intacta y esta es una rama independiente."""
    import time
    from datetime import datetime
    mundo = Path(mundo)
    cfg = json.loads((mundo / "config.json").read_text())
    p = dict(cfg["parametros"])
    _aplicar_parametros(p)
    cada = int(cada or p["cada"])
    ms = int(ms if ms is not None else p["ms"])
    detalle = float(detalle if detalle is not None else p["detalle"])
    cps = sorted(int(f.stem) for f in (mundo / "frames").glob("*.npz"))
    if not cps:
        raise SystemExit(f"no hay checkpoints en {mundo}/frames")
    previos = [c for c in cps if c <= desde_paso]
    cp = previos[-1] if previos else cps[0]
    mantle, crust, sink, cp = _cargar_estado(mundo, mundo / "frames" / f"{cp:06d}.npz")
    # avance silencioso checkpoint -> desde_paso: reproduce el estado EXACTO del
    # cuadro pausado (determinista con f64) sin renderizar ni guardar
    for i in range(cp + 1, desde_paso + 1):
        u, v = mantle.step(sink)
        crust.sea = SEA_LEVEL + nivel_mar(i)
        boundary = crust.step(u, v, mantle.hot)
        sink = upsample(crust.trench, MY, MX)
    # rama nueva: su propio mundo de checkpoints para poder re-extrapolar
    rama_mundo = Path(f"{salida}_mundo")
    if rama_mundo.exists():
        shutil.rmtree(rama_mundo)
    _crear_mundo_en(rama_mundo, p, Path(salida).name, crust)
    print(f"extrapolando desde el paso {desde_paso} (checkpoint {cp}) "
          f"+{pasos} pasos -> rama '{Path(salida).name}'")
    t0 = time.time()
    fm, fp, fma, fc, boundary, meta_frames = _simular(
        mantle, crust, pasos, cada, rama_mundo, detalle,
        paso0=desde_paso + 1, sink=sink, paso_estado=cada * max(int(cada_estado), 1))
    if not fm:
        raise SystemExit("la extrapolacion no produjo cuadros (revisa -t y --cada)")
    print(f"{pasos} pasos en {time.time()-t0:.1f}s")
    fm[-1].save(f"{salida}_final.png")
    for suf, fr in (("", fm), ("_placas", fp), ("_manto", fma), ("_clima", fc)):
        fr[0].save(f"{salida}{suf}.gif", save_all=True,
                   append_images=fr[1:], duration=ms, loop=0)
    _guardar_reproductor(salida, fm, fp, fma, fc, meta_frames, cada, ms,
                         mundo_nombre=rama_mundo.name)
    cfg_rama = json.loads((rama_mundo / "config.json").read_text())
    cfg_rama["rama_de"] = {"mundo": str(mundo), "desde_paso": int(desde_paso),
                           "fecha": datetime.now().isoformat(timespec="seconds")}
    (rama_mundo / "config.json").write_text(
        json.dumps(cfg_rama, indent=2, ensure_ascii=False))
    print(f"-> {salida}.gif, _placas, _manto, _clima, _cuadros/, _repro.json, _mundo/")
    return len(meta_frames)

def detallar(mundo, paso, factor, salida, semilla=0, casquetes=0.18, relieve=1.0,
             temperatura=None, precipitaciones=None, sinuosidad=1.0,
             semilla_civ=0, asentamientos=0, paises=0, tam_paises=0):
    """Detallado NO destructivo de UN solo cuadro. Igual que extrapolar, carga
    el checkpoint mas cercano <= `paso` y avanza en silencio hasta el estado
    EXACTO de ese cuadro; pero en vez de seguir la simulacion, super-muestrea
    ese unico frame a `factor` veces la resolucion y le anade la geografia
    menor que la tectonica no resuelve, por METODOS DE RUIDO (fBm periodico +
    deformacion de dominio) condicionados por los campos fisicos del cuadro:
    costas rotas e islitas de plataforma, colinas abisales, cadenas de islas
    sobre los puntos calientes, arcos insulares sobre el volcanismo de
    subduccion, mares interiores en las cuencas continentales bajas y
    casquetes polares. Rinde <salida>.png (relieve; bajo el mar solo la
    plataforma continental, sin fondo abisal) + <salida>_clima.png (mapa
    fisico-climatico snapshot a PLENA resolucion del detalle: biomas
    reclasificados pixel a pixel con la geografia fina, relieve sombreado, rios,
    corrientes y hielo; la fisica se calcula sobre una malla capada por costo
    pero el render va a la resolucion completa) + .json con los metadatos. El
    mundo de origen NO se toca: su evolucion subsiguiente queda intacta, y la
    misma semilla de ruido reproduce el mismo detalle."""
    import time
    from datetime import datetime
    mundo = Path(mundo)
    cfg = json.loads((mundo / "config.json").read_text())
    p = dict(cfg["parametros"])
    _aplicar_parametros(p)
    # el clima del detalle es un dial propio del cuadro: si se da, sobreescribe
    # el del mundo que acaba de fijar _aplicar_parametros; si no, se conserva
    global TEMPERATURA, PRECIPITACIONES
    if temperatura is not None:
        TEMPERATURA = float(temperatura)
    if precipitaciones is not None:
        PRECIPITACIONES = float(precipitaciones)
    factor = min(max(int(factor), 2), 32)
    cps = sorted(int(f.stem) for f in (mundo / "frames").glob("*.npz"))
    if not cps:
        raise SystemExit(f"no hay checkpoints en {mundo}/frames")
    previos = [c for c in cps if c <= paso]
    cp = previos[-1] if previos else cps[0]
    mantle, crust, sink, cp = _cargar_estado(mundo, mundo / "frames" / f"{cp:06d}.npz")
    paso = max(paso, cp)
    faltan = paso - cp
    for i in range(cp + 1, paso + 1):   # avance silencioso: estado exacto del cuadro
        u, v = mantle.step(sink)
        crust.sea = SEA_LEVEL + nivel_mar(i)
        crust.step(u, v, mantle.hot)
        sink = upsample(crust.trench, MY, MX)
        if (i - cp) % 20 == 0:
            print(f"  paso {i - cp}/{faltan}...")
    crust.sea = SEA_LEVEL + nivel_mar(paso)
    ny, nx = NY * factor, NX * factor
    print(f"detallando el cuadro del paso {paso} (checkpoint {cp}) a {nx}x{ny} "
          f"({factor}x, ruido {semilla})...")
    t0 = time.time()
    f32 = np.float32
    # los campos del cuadro, super-muestreados: la tectonica manda, el ruido
    # solo rellena las escalas que la malla original no resuelve. bicubico:
    # bilineal convierte cada pixel aislado (p.ej. un pozo de fondo viejo)
    # en un rombo evidente a estos aumentos
    elev_orig = crust.elevation(p["detalle"])   # cuadro original (mapa pequeno):
                                                # de aqui salen las corrientes
    eu = _upsample_bicubico(elev_orig, factor)
    Fu = _upsample_bicubico(crust.F, factor)
    Du = _upsample_bicubico(np.abs(crust.D), factor)
    vh = _upsample_bicubico(crust.volcano_hot, factor)
    va = _upsample_bicubico(crust.volcano_arc, factor)
    # generador PROPIO del detalle (semilla, paso): otra semilla = otra
    # geografia menor sobre la misma tectonica; el rng de la simulacion ni se lee
    rng_d = np.random.default_rng([int(semilla) & 0x7FFFFFFF, int(paso)])
    r1 = _fbm(rng_d, ny, nx, esc0=max(NY // 2, 8))       # sub-rejilla fina
    wy = _fbm(rng_d, ny, nx, esc0=max(NY // 8, 4))       # deformacion de dominio:
    wx = _fbm(rng_d, ny, nx, esc0=max(NY // 8, 4))       # el detalle serpentea en
    r1 = advect(r1, wx * (2.5 * factor), wy * (2.5 * factor), 1.0).astype(f32)
    del wy, wx                                           # vez de verse algodonoso
    rr = f32(1.0) - f32(2.0) * np.abs(_fbm(rng_d, ny, nx, esc0=max(NY, 8)))
    baja = _fbm(rng_d, ny, nx, esc0=max(NY // 8, 4))     # muy baja frecuencia
    costa = np.exp(-(eu / f32(0.06)) ** 2)               # banda costera+plataforma
    elev2 = (eu + f32(relieve) * (
        f32(0.055) * costa * r1                          # costas rotas, islitas,
                                                         # bahias y lagunas
        + f32(0.15) * np.clip(eu, 0, None) * (f32(0.35) + f32(0.65) * Du) * rr
                                                         # crestas de montana
        + f32(0.02) * np.clip(-eu / f32(0.25), 0, 1) * r1))  # colinas abisales
    del costa, rr
    # mares interiores: depresiones de muy baja frecuencia en el interior
    # continental bajo; donde caen bajo el nivel del mar, se inundan
    interior = (np.clip((Fu - f32(0.6)) / f32(0.3), 0, 1)
                * np.clip(f32(1.0) - eu / f32(0.12), 0, 1) * (eu > 0))
    elev2 -= f32(0.05 * relieve) * np.clip(baja - f32(0.25), 0, None) * interior
    del interior, Fu, Du
    # islas menores: cadenas sobre puntos calientes (Hawai/Polinesia) y arcos
    # insulares (Caribe/Marianas); el ruido decide CUALES montes emergen
    def _norm(q):
        return np.clip(q / (np.percentile(q, 99.5) + 1e-12), 0, 1).astype(f32)
    semillero = np.clip(r1 - f32(0.30), 0, None) / f32(0.70)
    elev2 += ((f32(0.10) * _norm(vh) + f32(0.06) * _norm(va))
              * semillero * (eu < f32(0.01)))
    del semillero, vh, va, r1, eu
    elev2 = np.clip(elev2, -1, 1)
    # casquetes polares: la fila hace de latitud; el borde lo rompe el ruido
    hielo_t = hielo_m = None
    if casquetes > 0:
        lat = np.abs(np.linspace(-1.0, 1.0, ny, dtype=f32))[:, None]
        frio = lat - f32(1.0 - min(float(casquetes), 0.6)) + f32(0.06) * baja
        hielo_t = np.clip(frio / f32(0.04), 0, 1) * (elev2 > 0)     # casquete
        hielo_m = np.clip((frio - f32(0.03)) / f32(0.05), 0, 1) * (elev2 <= 0)
        del lat, frio                                               # banquisa
    del baja
    # relieve: el fondo abisal no se muestra; bajo el mar solo queda la
    # plataforma continental y, pasado el talud, un azul oceanico uniforme
    prof = np.clip((f32(-0.06) - elev2) / f32(0.06), 0, 1)
    elev_vis = (elev2 * (f32(1.0) - prof) + f32(-0.55) * prof).astype(f32)
    del prof
    img = render(elev_vis, np.zeros_like(elev_vis))
    if hielo_t is not None:
        arr = np.asarray(img, dtype=np.float32)
        h = hielo_t[..., None]
        arr = arr * (1 - h) + np.array([242, 246, 250], np.float32) * h
        h = f32(0.85) * hielo_m[..., None]
        arr = arr * (1 - h) + np.array([214, 228, 240], np.float32) * h
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    png = f"{salida}.png"
    img.save(png)
    del img, elev_vis        # liberar el relieve antes del render climatico gigante
    # clima del cuadro detallado: segunda imagen, funcion PURA de la geografia
    # detallada (mismos diales de clima que la corrida; no toca el rng de la
    # simulacion). La FISICA se calcula sobre una malla capada (<=512): no solo
    # por costo, sino porque el clima es fenomeno de GRAN escala — sobre el fBm
    # fino el drenaje por percentil degenera en miles de rios/lagos de 1px
    # (tierra moteada de azul). El RENDER si va a plena resolucion: los biomas
    # se reclasifican pixel a pixel con la geografia fina y los rios/lagos/
    # corrientes se trazan como vectores escalados desde la malla gruesa
    kc = max(1, -(-ny // 512))
    if kc == 1:
        elev_c = elev2
    elif ny % kc == 0 and nx % kc == 0:
        elev_c = elev2.reshape(ny // kc, kc, nx // kc, kc).mean(axis=(1, 3))
    else:
        elev_c = elev2[::kc, ::kc]
    print(f"clima del detalle (fisica a {elev_c.shape[1]}x{elev_c.shape[0]}, "
          f"render a {nx}x{ny})...")
    campos = clima.simular_clima(elev_c, temperatura=TEMPERATURA,
                                 precipitaciones=PRECIPITACIONES)
    # Las corrientes NO se re-evaluan sobre la costa ruidosa del detalle (ahi
    # los giros salen deformados): se recalculan sobre el cuadro ORIGINAL —la
    # misma fisica que produjo el mapa pequeno de clima de la corrida, cuyos
    # circuitos si estan bien formados— y solo se re-escalan (bicubico
    # periodico) a la malla del detalle para renderizarlas con mas calidad.
    print(f"corrientes del cuadro original ({NX}x{NY}), re-escaladas al detalle...")
    cor = clima.simular_clima(elev_orig, temperatura=TEMPERATURA,
                              precipitaciones=PRECIPITACIONES,
                              solo_corrientes=True)
    mar_cd = elev_c <= 0.0
    for k in ("cu", "cv", "sst_anom", "psi"):
        campos[k] = (clima._upsample_bicubico_a(cor[k], *elev_c.shape)
                     * mar_cd)
    del cor, elev_orig
    png_c = f"{salida}_clima.png"
    clima.render_clima_detalle(campos, elev2, elev_c,
                               temperatura=TEMPERATURA).save(png_c)

    # ---- clima HD: hidrologia fina + overlays + capas vectoriales ----
    # la fisica se queda en la malla capada (gran escala); la HIDROLOGIA se
    # recalcula sobre la geografia FINA en una malla res_hidro=min(render,4096)
    # (downsample por media de bloques si render>4096, como el kc de arriba)
    th0 = time.time()
    nh = min(ny, 4096)
    if nh == ny:
        elev_h = elev2
    else:
        elev_h = clima._malla_bloques(elev2, nh, nh)
    precip_h = np.clip(clima._upsample_bicubico_a(campos["precip"], nh, nh), 0.0, 1.0)
    hielo_h = np.clip(clima._upsample_bicubico_a(campos["hielo"], nh, nh), 0.0, 1.0)
    hidro = clima.hidrologia_fina(elev_h, precip_h, hielo_h,
                                  sinuosidad=float(sinuosidad))
    del precip_h, hielo_h
    if elev_h is not elev2:
        del elev_h
    print(f"hidrologia fina a {nh}x{nh} ({hidro['iters']} iteraciones de "
          f"acumulacion, {int(hidro['rios'].sum())} celdas de rio, "
          f"{int(hidro['lagos'].sum())} de lago) en {time.time()-th0:.1f}s")
    tr0 = time.time()
    png_hd = f"{salida}_climahd.png"
    clima.render_clima_hd(campos, elev2, elev_c, hidro,
                          temperatura=TEMPERATURA).save(png_hd)
    print(f"render climahd a {nx}x{ny} en {time.time()-tr0:.1f}s")
    te0 = time.time()
    res_datos = (min(nx, 1024), min(ny, 1024))
    res_koppen = (min(nx, 2048), min(ny, 2048))
    rd, rk = clima.exportar_capas(salida, campos, elev2, elev_c, hidro, nx, ny,
                                  (res_datos[1], res_datos[0]),
                                  (res_koppen[1], res_koppen[0]),
                                  temperatura=TEMPERATURA,
                                  civ_dials={"semilla": int(semilla_civ),
                                             "asentamientos": int(asentamientos),
                                             "paises": int(paises),
                                             "tam": int(tam_paises)})
    print(f"capas (koppen/cuencas/datos/datos2/capas.json a "
          f"{res_datos[0]}x{res_datos[1]}) en {time.time()-te0:.1f}s")
    del hidro, campos, elev2
    meta = {"mundo": str(mundo), "paso": int(paso), "checkpoint": int(cp),
            "ma": round(paso * ANOS_POR_PASO, 3), "factor": int(factor),
            "semilla_detalle": int(semilla), "casquetes": float(casquetes),
            "relieve": float(relieve), "sinuosidad": float(sinuosidad),
            "resolucion": [int(nx), int(ny)],
            # diales de clima efectivos de este cuadro (los que se usaron)
            "temperatura": float(TEMPERATURA),
            "precipitaciones": float(PRECIPITACIONES),
            # el PNG climatico va ahora a plena resolucion (== resolucion); la
            # fisica se calculo sobre la malla capada (resolucion_fisica_clima)
            "resolucion_clima": [int(nx), int(ny)],
            "resolucion_fisica_clima": [int(elev_c.shape[1]), int(elev_c.shape[0])],
            "mar": round(float(crust.sea), 4),
            # capa climatica HD (aditivo): hidrologia fina + overlays + capas
            "climahd": True,
            "res_hidro": [int(nh), int(nh)],
            "res_datos": [int(rd[0]), int(rd[1])],
            # diales de civilizacion efectivos (0 = automatico)
            "civilizacion": {"semilla": int(semilla_civ),
                             "asentamientos": int(asentamientos),
                             "paises": int(paises),
                             "tam_paises": int(tam_paises)},
            "creado": datetime.now().isoformat(timespec="seconds")}
    Path(f"{salida}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"-> {png} ({nx}x{ny}), {png_c}, {png_hd}, "
          f"{salida}_koppen/cuencas/datos/datos2.png, {salida}_capas.json y "
          f"{salida}.json en {time.time()-t0:.1f}s; el mundo de origen queda intacto")
    return png

# ---------------- CLI ----------------
def main():
    import argparse, time
    global rng

    p = argparse.ArgumentParser(
        prog="tecto",
        description="Simulacion geologica ligera: conveccion 3D aproximada del "
                    "manto -> tectonica de placas -> mapa 2D animado (GIF).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-t", "--tiempo", type=int, default=800, metavar="PASOS",
                   help="tiempo de simulacion en pasos (mas pasos = mas deriva "
                        "continental y GIF mas largo)")
    p.add_argument("-c", "--cada", type=int, default=8, metavar="N",
                   help="guardar un frame cada N pasos")
    p.add_argument("--ms", type=int, default=60, metavar="MS",
                   help="milisegundos por frame en el GIF (mayor = mas lento)")
    p.add_argument("-s", "--semilla", type=int, default=7,
                   help="semilla aleatoria (cambia el mundo generado)")
    p.add_argument("-r", "--resolucion", type=int, default=256, metavar="PX",
                   help="lado del mapa en pixeles")
    p.add_argument("-d", "--detalle", type=float, default=0.6, metavar="X",
                   help="rugosidad fractal del render, 0=liso .. ~1.5=abrupto "
                        "(no cambia el costo de simulacion)")
    p.add_argument("-o", "--salida", default="tectonica", metavar="NOMBRE",
                   help="prefijo de salida: NOMBRE.gif y NOMBRE_final.png")
    p.add_argument("--sin-gif", action="store_true",
                   help="solo guardar el PNG del mapa final")
    g = p.add_argument_group("algoritmo", "diales de la simulacion geologica")
    g.add_argument("--velocidad", type=float, default=VEL_SCALE, metavar="V",
                   help="velocidad de la deriva continental (px/paso)")
    g.add_argument("--mar", type=float, default=SEA_LEVEL, metavar="H",
                   help="nivel del mar (mas alto = mas oceano)")
    g.add_argument("--continentes", type=float, default=CONT_UMBRAL, metavar="U",
                   help="umbral continental inicial (menor = mas tierra)")
    g.add_argument("--plumas", type=int, default=PLUME_EVERY, metavar="N",
                   help="pasos entre nacimientos de plumas (menor = manto "
                        "mas activo)")
    g.add_argument("--erosion", type=float, default=EROSION, metavar="E",
                   help="tasa de erosion del relieve")
    g.add_argument("--empuje", type=float, default=RIDGE_PUSH, metavar="R",
                   help="empuje de dorsal (motor de la deriva post-rift)")
    g.add_argument("--momento", type=float, default=MOMENTUM, metavar="M",
                   help="relajacion del rumbo de placa por paso (menor = "
                        "rumbo mas sostenido, colisiones mas decididas)")
    g.add_argument("--rigidez", type=float, default=RIGID, metavar="G",
                   help="rigidez de placa: 0=fluido, 1=balsa rigida")
    g.add_argument("--deriva", type=float, default=DERIVA, metavar="D",
                   help="ganancia de deriva continental: cuanto remolcan a "
                        "cada continente su margen oceanico y el manto "
                        "(1=solo la media del manto; con el valor por defecto "
                        "el continente viaja a la velocidad de su placa)")
    g.add_argument("--anos-paso", "--anos_paso", type=float,
                   default=ANOS_POR_PASO, metavar="MA", dest="anos_paso",
                   help="millones de anos (Ma) que representa cada paso: fija la "
                        "escala de tiempo que se rotula en los frames")
    # default None para distinguir "no dado" de "explicito": en generacion None
    # cae al default de modulo; en --detallar None conserva el clima del mundo,
    # un valor explicito lo sobreescribe
    g.add_argument("--temperatura", type=float, default=None, metavar="T",
                   help="clima: temperatura global del planeta, -1 (bola de "
                        "nieve) .. 0 (templado, Tierra) .. +1 (invernadero); "
                        "solo afecta al mapa de clima, no a la tectonica; en "
                        "--detallar sobreescribe la del mundo")
    g.add_argument("--precipitaciones", "--humedad", dest="precipitaciones",
                   type=float, default=None, metavar="P",
                   help="clima: precipitaciones globales, 0.2 (arido) .. 1 "
                        "(normal) .. 2 (muy humedo); escala la lluvia, los "
                        "rios y la selva; en --detallar sobreescribe la del "
                        "mundo (--humedad es un alias retrocompatible)")
    m = p.add_argument_group("mundos", "almacenamiento por frame para "
                             "reconstruir o retomar simulaciones")
    m.add_argument("--datos", action="store_true",
                   help="guardar el estado completo de cada frame en "
                        "mundos/<nombre>/ (config + frames reanudables)")
    m.add_argument("--reproductor", action="store_true",
                   help="guardar cuadros PNG por frame + repro.json (timeline) + "
                        "un mundo de checkpoints junto a la salida: habilita el "
                        "reproductor web (adelante/reversa/pausa) y extrapolar")
    m.add_argument("--cada-estado", type=int, default=10, metavar="F",
                   dest="cada_estado",
                   help="frames entre checkpoints de estado completo (1 = estado "
                        "de CADA cuadro; mas alto = menos disco)")
    m.add_argument("--reconstruir", metavar="CARPETA",
                   help="re-renderizar mapa.gif y placas.gif desde los datos "
                        "de un mundo guardado (ignora el resto de opciones)")
    m.add_argument("--continuar", metavar="CARPETA",
                   help="retomar la simulacion de un mundo guardado; -t son "
                        "los pasos adicionales")
    m.add_argument("--desde", type=int, metavar="PASO",
                   help="con --continuar: retomar desde ese frame guardado "
                        "(los frames posteriores se descartan)")
    m.add_argument("--extrapolar", metavar="MUNDO",
                   help="rama NO destructiva desde un cuadro de un mundo de "
                        "checkpoints; usa --desde-paso, -t (pasos) y -o (rama)")
    m.add_argument("--desde-paso", type=int, default=0, metavar="PASO",
                   dest="desde_paso",
                   help="con --extrapolar: paso (cuadro) del que partir")
    d = p.add_argument_group("detalle", "extrapolacion gigantesca de UN solo "
                             "cuadro: geografia menor por ruido (islas, mares "
                             "interiores, casquetes) sin tocar el mundo")
    d.add_argument("--detallar", metavar="MUNDO",
                   help="detalla el cuadro --desde-paso del mundo dado a "
                        "--factor veces la resolucion; rinde <SALIDA>.png y "
                        ".json (el mundo y su evolucion quedan intactos)")
    d.add_argument("--factor", type=int, default=8, metavar="N",
                   help="con --detallar: aumento (mapa de N*resolucion px)")
    d.add_argument("--semilla-detalle", "--semilla_detalle", type=int,
                   default=0, dest="semilla_detalle", metavar="S",
                   help="con --detallar: semilla del ruido; cambiarla da otra "
                        "geografia menor sobre la MISMA tectonica")
    d.add_argument("--casquetes", type=float, default=0.18, metavar="X",
                   help="con --detallar: extension de los casquetes polares "
                        "(0 = sin hielo, ~0.45 = edad de hielo)")
    d.add_argument("--relieve", type=float, default=1.0, metavar="R",
                   help="con --detallar: amplitud del ruido de detalle")
    d.add_argument("--sinuosidad", type=float, default=1.0, metavar="S",
                   help="con --detallar: cuanto serpentean los rios y cuantas "
                        "cuencas endorreicas/lagos siembra el drenaje "
                        "(0 = rios rectos por pendiente pura, 1 = normal, "
                        "3 = muy serpenteante)")
    d.add_argument("--semilla-civ", "--semilla_civ", type=int, default=0,
                   dest="semilla_civ", metavar="S",
                   help="con --detallar: semilla de la civilizacion; cambiarla "
                        "da otros asentamientos/paises sobre la MISMA geografia")
    d.add_argument("--asentamientos", type=int, default=0, metavar="N",
                   help="con --detallar: numero objetivo de asentamientos "
                        "(0 = automatico segun la fraccion de tierra)")
    d.add_argument("--paises", type=int, default=0, metavar="N",
                   help="con --detallar: numero objetivo de paises "
                        "(0 = automatico)")
    d.add_argument("--tam-paises", "--tam_paises", type=int, default=0,
                   dest="tam_paises", metavar="T",
                   help="con --detallar: tamano de los paises (0 = automatico, "
                        "1 = grandes/imperios que se reparten todo el suelo, "
                        "2 = chicos/reinos que dejan tierras libres)")
    args = p.parse_args()

    if args.reconstruir:
        return reconstruir(args.reconstruir)
    if args.continuar:
        return continuar(args.continuar, args.tiempo, args.desde)
    if args.extrapolar:
        Path(args.salida).resolve().parent.mkdir(parents=True, exist_ok=True)
        return extrapolar(args.extrapolar, args.desde_paso, args.tiempo,
                          args.salida, ms=args.ms, detalle=args.detalle,
                          cada=args.cada, cada_estado=args.cada_estado)
    if args.detallar:
        Path(args.salida).resolve().parent.mkdir(parents=True, exist_ok=True)
        return detallar(args.detallar, args.desde_paso, args.factor,
                        args.salida, semilla=args.semilla_detalle,
                        casquetes=args.casquetes, relieve=args.relieve,
                        temperatura=args.temperatura,
                        precipitaciones=args.precipitaciones,
                        sinuosidad=args.sinuosidad,
                        semilla_civ=args.semilla_civ,
                        asentamientos=args.asentamientos, paises=args.paises,
                        tam_paises=args.tam_paises)
    if args.tiempo < 1 or args.cada < 1 or args.resolucion < 32:
        p.error("tiempo y cada deben ser >= 1, resolucion >= 32")
    rng = np.random.default_rng(args.semilla)
    _aplicar_parametros(_parametros_de(args))
    # crear el directorio del prefijo de salida si hace falta
    Path(args.salida).resolve().parent.mkdir(parents=True, exist_ok=True)

    mantle, crust = Mantle(), Crust()
    # mundo de estado: --reproductor guarda checkpoints junto a la salida (para
    # el reproductor web y extrapolar); --datos guarda el mundo completo (cada
    # frame) en mundos/. El reproductor tiene prioridad si se piden ambos
    paso_estado = None
    mundo_repro = None
    if args.reproductor:
        mundo_repro = Path(f"{args.salida}_mundo")
        if mundo_repro.exists():
            shutil.rmtree(mundo_repro)
        carpeta = _crear_mundo_en(mundo_repro, _parametros_de(args),
                                  Path(args.salida).name, crust)
        paso_estado = args.cada * max(args.cada_estado, 1)
    elif args.datos:
        carpeta = _crear_mundo(args)
        np.savez_compressed(carpeta / "base.npz", D0=crust.D0,
                            F_total=crust.F_total)
    else:
        carpeta = None
    t0 = time.time()
    frames_m, frames_p, frames_ma, frames_c, boundary, meta_frames = _simular(
        mantle, crust, args.tiempo, args.cada, carpeta,
        None if args.sin_gif else args.detalle, paso_estado=paso_estado)
    dt = time.time() - t0
    print(f"{args.tiempo} pasos en {dt:.1f}s ({args.tiempo/dt:.0f} pasos/s)")

    png = f"{args.salida}_final.png"
    vol = ((crust.volcano_arc, 0.003, 3), (crust.volcano_hot, 0.012, 2))
    render(crust.elevation(args.detalle), boundary, vol).save(png)
    print(f"-> {png} ({(args.tiempo - 1) * ANOS_POR_PASO:,.0f} Ma)")
    if not args.sin_gif:
        gif = f"{args.salida}.gif"
        frames_m[0].save(gif, save_all=True, append_images=frames_m[1:],
                         duration=args.ms, loop=0)
        segs = len(frames_m) * args.ms / 1000
        print(f"-> {gif} ({len(frames_m)} frames, ~{segs:.1f}s)")
        gifp = f"{args.salida}_placas.gif"
        frames_p[0].save(gifp, save_all=True, append_images=frames_p[1:],
                         duration=args.ms, loop=0)
        print(f"-> {gifp} (placas, deriva y simbologia)")
        gifma = f"{args.salida}_manto.gif"
        frames_ma[0].save(gifma, save_all=True, append_images=frames_ma[1:],
                          duration=args.ms, loop=0)
        print(f"-> {gifma} (manto: plumas y anomalia termica)")
        gifc = f"{args.salida}_clima.gif"
        frames_c[0].save(gifc, save_all=True, append_images=frames_c[1:],
                         duration=args.ms, loop=0)
        print(f"-> {gifc} (clima: biomas, lluvia, rios y corrientes)")
    # reproductor web: cuadros PNG + repro.json (timeline) + mundo de checkpoints
    if args.reproductor and frames_m:
        n = _guardar_reproductor(args.salida, frames_m, frames_p, frames_ma,
                                 frames_c, meta_frames, args.cada, args.ms,
                                 mundo_nombre=mundo_repro.name)
        cps = sum(1 for f in meta_frames if f.get("checkpoint"))
        tam = sum(f.stat().st_size for f in mundo_repro.rglob("*")
                  if f.is_file()) / 1e6
        print(f"-> {args.salida}_cuadros/ ({n} cuadros) y {args.salida}_repro.json")
        print(f"-> {mundo_repro}/ ({cps} checkpoints, {tam:.0f} MB; extrapolable)")
    elif args.reproductor:
        print("aviso: --reproductor sin frames (¿--sin-gif?); no se guardaron cuadros")
    # mundo --datos: copia las salidas finales dentro del mundo completo
    if args.datos and carpeta and not args.reproductor:
        shutil.copy(png, carpeta / "mapa_final.png")
        if not args.sin_gif:
            shutil.copy(gif, carpeta / "mapa.gif")
            shutil.copy(gifp, carpeta / "placas.gif")
            shutil.copy(gifma, carpeta / "manto.gif")
            shutil.copy(gifc, carpeta / "clima.gif")
        tam = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file()) / 1e6
        print(f"-> {carpeta}/ (estado por frame, {tam:.0f} MB; "
              f"--reconstruir/--continuar para retomarlo)")


if __name__ == "__main__":
    main()
