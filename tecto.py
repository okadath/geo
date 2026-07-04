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

Todo toroidal (mapa periodico). Costo por paso: unas cuantas FFTs 48x48 y
operaciones vectorizadas 256x256 -> corre cientos de pasos por segundo.
"""
import numpy as np
from PIL import Image

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

# ---------------- utilidades ----------------
def grad_periodic(f):
    fy = (np.roll(f, -1, 0) - np.roll(f, 1, 0)) * 0.5
    fx = (np.roll(f, -1, 1) - np.roll(f, 1, 1)) * 0.5
    return fx, fy

def lap_periodic(f, axes=(0, 1)):
    out = -2 * len(axes) * f
    for a in axes:
        out += np.roll(f, 1, a) + np.roll(f, -1, a)
    return out

def poisson_fft(rhs):
    """Resuelve lap(phi) = rhs en malla periodica via FFT.

    Amortigua los modos de escala mas grande: sin esto 1/k^2 hace que
    domine una sola celda de conveccion global; fisicamente las celdas
    miden ~la profundidad del manto, no todo el dominio.
    """
    ky = np.fft.fftfreq(rhs.shape[0]) * 2 * np.pi
    kx = np.fft.fftfreq(rhs.shape[1]) * 2 * np.pi
    k2 = ky[:, None] ** 2 + kx[None, :] ** 2
    k2[0, 0] = 1.0
    k0 = 2 * np.pi * 2.5 / rhs.shape[0]          # ~2.5 celdas por dominio
    damp = 1.0 - np.exp(-k2 / k0 ** 2)
    phi = np.fft.ifft2(np.fft.fft2(rhs) * damp / -k2).real
    return phi

def advect(f, u, v, dt):
    """Adveccion semi-lagrangiana periodica (backtrace bilineal)."""
    ny, nx = f.shape
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    sx = (xx - u * dt) % nx
    sy = (yy - v * dt) % ny
    x0 = np.floor(sx).astype(int); y0 = np.floor(sy).astype(int)
    fx = sx - x0; fy = sy - y0
    x1 = (x0 + 1) % nx; y1 = (y0 + 1) % ny
    return (f[y0, x0] * (1 - fx) * (1 - fy) + f[y0, x1] * fx * (1 - fy)
            + f[y1, x0] * (1 - fx) * fy + f[y1, x1] * fx * fy)

def upsample(f, ny, nx):
    """Bilineal periodico de la malla del manto a la del mapa."""
    y = np.arange(ny) * f.shape[0] / ny
    x = np.arange(nx) * f.shape[1] / nx
    y0 = np.floor(y).astype(int); x0 = np.floor(x).astype(int)
    fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
    y1 = (y0 + 1) % f.shape[0]; x1 = (x0 + 1) % f.shape[1]
    return (f[np.ix_(y0, x0)] * (1 - fy) * (1 - fx) + f[np.ix_(y0, x1)] * (1 - fy) * fx
            + f[np.ix_(y1, x0)] * fy * (1 - fx) + f[np.ix_(y1, x1)] * fy * fx)

def sample_nearest(f, ny, nx):
    """Remuestreo por vecino mas cercano (para mascaras y etiquetas)."""
    y = np.arange(ny) * f.shape[0] // ny
    x = np.arange(nx) * f.shape[1] // nx
    return f[np.ix_(y, x)]

def label_components(mask):
    """Componentes conexas en malla periodica por propagacion de maximos.

    Puro numpy: cada celda toma el id maximo de sus vecinas hasta converger.
    Sobre la malla reducida LGRID x LGRID el costo es despreciable.
    """
    lab = np.where(mask, np.arange(mask.size, dtype=np.int64).reshape(mask.shape), -1)
    for _ in range(2 * mask.shape[0]):
        nxt = lab
        for ax in (0, 1):
            for sh in (1, -1):
                nxt = np.maximum(nxt, np.roll(lab, sh, ax))
        nxt = np.where(mask, nxt, -1)
        if np.array_equal(nxt, lab):
            break
        lab = nxt
    return lab

# ---------------- 1. manto 3D ----------------
class Mantle:
    def __init__(self):
        # T[z, y, x]; z=0 fondo caliente, z=MZ-1 tope frio
        self.profile = np.linspace(1.0, 0.0, MZ)[:, None, None]
        self.T = self.profile + 0.15 * rng.standard_normal((MZ, MY, MX))
        self.t = 0
        self.plumes = []   # plumas activas: derivan lento y tienen vida finita

    def _blob(self, cy, cx, r):
        """Gaussiana periodica centrada en (cy,cx)."""
        dy = np.abs(np.arange(MY)[:, None] - cy); dy = np.minimum(dy, MY - dy)
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
            p["y"] = (p["y"] + p["dy"]) % MY
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
        self.F = np.where(n > 0.55, 1.0, 0.0)  # fraccion continental (conservada)
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
        us = sample_nearest(self.Pu, LGRID, LGRID).ravel()
        vs = sample_nearest(self.Pv, LGRID, LGRID).ravel()
        cnt = np.bincount(self.lab_inv).astype(float)
        mu = np.bincount(self.lab_inv, us) / cnt
        mv = np.bincount(self.lab_inv, vs) / cnt
        u_r = mu[self.lab_inv].reshape(LGRID, LGRID)
        v_r = mv[self.lab_inv].reshape(LGRID, LGRID)
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
            u_raft = 0.2 * (u_raft + np.roll(u_raft, sh, 0) + np.roll(u_raft, -sh, 0)
                            + np.roll(u_raft, sh, 1) + np.roll(u_raft, -sh, 1))
            v_raft = 0.2 * (v_raft + np.roll(v_raft, sh, 0) + np.roll(v_raft, -sh, 0)
                            + np.roll(v_raft, sh, 1) + np.roll(v_raft, -sh, 1))
        # peso: continente firme, pero un rift activo lo ablanda para
        # que las plumas nuevas aun puedan desgarrarlo
        ux0, _ = grad_periodic(u); _, vy0 = grad_periodic(v)
        open_m = np.clip(ux0 + vy0, 0, None)
        w = RIGID * np.clip(self.F, 0, 1) * np.clip(1 - open_m * 25, 0, 1)
        u = u * (1 - w) + u_raft * w
        v = v * (1 - w) + v_raft * w

        C = advect(self.C, u, v, DT)
        F = np.clip(advect(self.F, u, v, DT), 0, 1)
        ux, uy = grad_periodic(u); vx, vy = grad_periodic(v)
        div = ux + vy
        shear = np.sqrt((ux - vy) ** 2 + (uy + vx) ** 2)
        conv = np.clip(-div, 0, None)
        opening = np.clip(div, 0, None)
        # falla transformante: cizalla alta con divergencia baja -> las placas
        # solo se rozan; no hay orogenia ni fosa, apenas un valle de falla
        transform = np.clip(shear - 2.5 * np.abs(div), 0, None)
        C -= 0.3 * transform * DT
        # convergencia: oceano subduce (se consume), continente se apila
        # (orogenia: la colision continental levanta cordilleras)
        C = np.where(F < 0.4, C - conv * C * DT * 1.5, C + conv * C * DT * 1.8)
        # arco de subduccion: la placa oceanica que se hunde bajo el margen
        # continental levanta una cordillera costera en la placa que cabalga
        # (tipo Andes): la fosa difuminada, aplicada solo sobre continente
        arc = conv * (F < 0.4)
        for sh in (1, 2, 3):   # desplazamientos crecientes: blur sin peine
            arc = 0.2 * (arc + np.roll(arc, sh, 0) + np.roll(arc, -sh, 0)
                         + np.roll(arc, sh, 1) + np.roll(arc, -sh, 1))
        C += 1.8 * arc * F * DT
        # cuenca de antepais: la corteza se flexiona hacia abajo frente al
        # orogeno en crecimiento -> depresion que puede inundarse (mar
        # interior, como el que habia frente a los Andes). Flexion = carga
        # orogenica difuminada ancha menos el nucleo del orogeno
        G = (conv + arc) * F
        basin = G
        for sh in (1, 2, 3, 4):   # desplazamientos crecientes = blur suave sin peine
            basin = 0.2 * (basin + np.roll(basin, sh, 0) + np.roll(basin, -sh, 0)
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
        # edad del fondo oceanico: se advecta, envejece, y renace en los rifts
        A = advect(self.A, u, v, DT) + DT
        A *= np.clip(1.0 - opening * 12, 0, 1)   # rift => corteza recien nacida
        self.A = np.clip(A, 0, 10 * AGE_TAU)
        # fosa de subduccion: convergencia sobre corteza oceanica
        self.trench = conv * (F < 0.4)
        # --- volcanismo ---
        # puntos calientes: donde una cabeza de pluma toca la litosfera
        hs = np.zeros((NY, NX))
        if hot is not None:
            hs = np.clip(upsample(hot, NY, NX), 0, None) * 0.25
        # en el mar el punto caliente construye un edificio volcanico (islas
        # tipo Hawai; la placa que deriva encima deja una cadena) y el domo
        # termico rejuvenece el fondo (queda somero)
        isl = hs * (F < 0.4)
        # el edificio crece apenas sobre el nivel del mar: islas volcanicas
        # pequenas (el volcanismo domina sobre la creacion de tierra)
        C += 0.12 * isl * np.clip(0.9 - C, 0, 1) * DT
        self.A *= np.clip(1 - 3 * isl, 0.2, 1)
        # arco de islas: la subduccion intraoceanica (tipo Marianas) tambien
        # construye un arco volcanico de islas junto a su fosa
        iarc = self.trench
        for sh in (1, 2):
            iarc = 0.2 * (iarc + np.roll(iarc, sh, 0) + np.roll(iarc, -sh, 0)
                          + np.roll(iarc, sh, 1) + np.roll(iarc, -sh, 1))
        # el arco emerge junto a la fosa, no encima (ahi la subduccion se lo
        # comeria): se excluye el nucleo de la fosa
        halo = np.clip(1 - self.trench * 50, 0, 1)
        C += 2.0 * iarc * halo * (F < 0.4) * np.clip(1.1 - C, 0, 1) * DT
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
        land = C > SEA_LEVEL
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
        return boundary

    def elevation(self, detail=0.6):
        elev = (self.C - SEA_LEVEL) * 1.1
        # en tierra la escala es cuadratica: llanuras verdes cerca del mar,
        # solo las zonas de colision llegan a cordillera/nieve
        elev = np.where(elev > 0, 0.5 * elev ** 2 + 0.03, elev)
        ocean = self.F < 0.5
        # subsidencia termica: el fondo joven (dorsal) queda somero y el
        # viejo se hunde -> cordilleras submarinas donde diverge el manto
        elev -= SUBSIDENCE * (1 - np.exp(-self.A / AGE_TAU)) * ocean
        # fosa de subduccion: depresion batimetrica en la convergencia
        elev -= TRENCH * self.trench
        # cuenca de antepais: depresion flexural frente a la cordillera en
        # crecimiento; si baja del nivel del mar se inunda (mar interior)
        elev -= 14.0 * self.foreland
        # rugosidad fractal: mas fuerte en montana, sutil en el mar; corta
        # las costas de forma irregular sin costo de simulacion
        elev += detail * self.D * (0.04 + 0.11 * np.clip(elev, 0, 1))
        return np.clip(elev, -1, 1)

# ---------------- 3. render ----------------
HYPSO = np.array([  # (nivel, r,g,b) elevacion normalizada -1..1
    (-1.0, 10, 20, 60), (-0.4, 15, 60, 120), (-0.05, 60, 130, 180),
    (0.0, 90, 160, 170), (0.02, 190, 180, 120), (0.15, 110, 150, 70),
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
        boundary = 0.2 * (boundary + np.roll(boundary, 1, 0) + np.roll(boundary, -1, 0)
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
                    m = np.maximum(m, np.roll(np.roll(vol, dy, 0), dx, 1))
            dots |= (vol >= m) & (vol > max(vmin, 0.35 * vol.max()))
        dots = (dots | np.roll(dots, 1, 0) | np.roll(dots, -1, 0)
                | np.roll(dots, 1, 1) | np.roll(dots, -1, 1))
        img[dots] = (235, 45, 25)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))

# ---------------- CLI ----------------
def main():
    import argparse, time
    global rng, NX, NY

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
    args = p.parse_args()

    if args.tiempo < 1 or args.cada < 1 or args.resolucion < 32:
        p.error("tiempo y cada deben ser >= 1, resolucion >= 32")
    rng = np.random.default_rng(args.semilla)
    NX = NY = args.resolucion

    mantle, crust = Mantle(), Crust()
    frames, sink = [], None
    t0 = time.time()
    for i in range(args.tiempo):
        u, v = mantle.step(sink)
        boundary = crust.step(u, v, mantle.hot)
        sink = upsample(crust.trench, MY, MX)  # la losa fria ancla la bajada
        if not args.sin_gif and i % args.cada == 0:
            vol = ((crust.volcano_arc, 0.003, 3), (crust.volcano_hot, 0.012, 2))
            frames.append(render(crust.elevation(args.detalle), boundary, vol))
        if i % 200 == 0 and i:
            print(f"  paso {i}/{args.tiempo}...")
    dt = time.time() - t0
    print(f"{args.tiempo} pasos en {dt:.1f}s ({args.tiempo/dt:.0f} pasos/s)")

    png = f"{args.salida}_final.png"
    vol = ((crust.volcano_arc, 0.003, 3), (crust.volcano_hot, 0.012, 2))
    render(crust.elevation(args.detalle), boundary, vol).save(png)
    print(f"-> {png}")
    if not args.sin_gif:
        gif = f"{args.salida}.gif"
        frames[0].save(gif, save_all=True, append_images=frames[1:],
                       duration=args.ms, loop=0)
        segs = len(frames) * args.ms / 1000
        print(f"-> {gif} ({len(frames)} frames, ~{segs:.1f}s)")


if __name__ == "__main__":
    main()
