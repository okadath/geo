"""
Capa climatica (SNAPSHOT) sobre la geografia de un cuadro de tecto.py.

El clima es una FUNCION PURA de la elevacion: se calcula DESPUES de la geografia
de cada frame, no guarda estado entre frames, no retroalimenta la tectonica y no
toca el rng global de tecto.py (las continuaciones de mundos deben seguir siendo
bit-exactas). Es determinista: misma elevacion + mismos diales => mismo clima.

Convencion de latitud: la FILA hace de latitud (como `detallar` con los
casquetes). `lat_norm = linspace(1, -1, n)`: fila 0 = polo norte, fila n-1 = polo
sur, centro = ecuador. Geometria ESFERICA (equirrectangular): el eje X
(longitud) es periodico y el eje Y (latitud) termina en los polos — las
advecciones, suavizados y el drenaje NO envuelven de polo a polo.

Cadena fisica (todo vectorizado, sin bucles por celda):
  temperatura latitudinal + altitud + continentalidad + corrientes
  -> vientos por bandas de Hadley con desviacion orografica
  -> corrientes marinas por esfuerzo del viento (Ekman) tangentes a la costa
     + SST advectada (lenguas calidas/frias)
  -> humedad evaporada del mar advectada por el viento (con reciclaje
     continental: parte de la lluvia se re-evapora y sigue viento abajo)
     -> lluvia base + orografica (sombra de lluvia a sotavento) + conveccion
     ecuatorial
  -> glaciaciones (banquisa en el mar, casquetes/glaciares en tierra)
  -> rios por drenaje de descenso mas empinado con acumulacion de caudal y
     umbral ABSOLUTO (la cantidad de rios emerge de cuanto llueve), lagos
     endorreicos y estuarios
  -> realimentacion: la evapotranspiracion de rios/lagos/grandes cuencas se
     re-inyecta como vapor y la lluvia + el drenaje se recalculan (2do pase)
  -> biomas (Whittaker simplificado sobre temperatura x precipitacion).

Solo numpy + PIL. NO importa tecto.py (tecto importara clima; se evita el ciclo);
los helpers pequenos (`grad_periodic`, adveccion semi-lagrangiana, `upsample`)
estan copiados aqui localmente, con nota de su origen.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import civ

# ============================ diales por defecto ============================
TEMPERATURA = 0.0   # -1 = bola de nieve .. 0 = templado (Tierra) .. +1 = invernadero
PRECIPITACIONES = 1.0  # 0.2 = arido .. 1 = normal .. 2 = muy humedo (antes HUMEDAD)

# Bono de humedad riberena: cuanto suma la cercania a rios/lagos/grandes cuencas
# a la precipitacion USADA SOLO para clasificar biomas (no a la precip mostrada
# ni a la fisica de lluvia). Empuja la vegetacion hacia bosque a lo largo de los
# cauces, modulado por temperatura por los umbrales de Whittaker (taiga en frio,
# bosque templado/humedo en templado/calido). Compartido por todos los renders.
BONO_RIBERA = 0.25

# ============================ paleta de biomas ==============================
# CONTRATO: estos ids y colores son fijos (otros modulos y la web los replican).
BIOMAS = {
    0:  ("hielo",           (238, 244, 250)),
    1:  ("tundra",          (170, 180, 160)),
    2:  ("taiga",           (75, 115, 88)),
    3:  ("estepa",          (205, 185, 115)),
    4:  ("desierto",        (235, 205, 140)),
    5:  ("desierto frio",   (192, 176, 148)),
    6:  ("pradera",         (160, 185, 90)),
    7:  ("bosque templado", (85, 140, 70)),
    8:  ("bosque seco",     (152, 158, 62)),
    9:  ("sabana",          (196, 188, 80)),
    10: ("bosque humedo",   (26, 105, 46)),
}
# tabla RGB indexable por id (para vectorizar el pintado)
_BIOMA_RGB = np.zeros((len(BIOMAS), 3), np.float64)
for _k, (_n, _c) in BIOMAS.items():
    _BIOMA_RGB[_k] = _c

# ============================ helpers (de tecto.py) =========================
# Copiados localmente para no importar tecto.py (evita el import circular).

def rolly(f, s, axis=0):
    """np.roll SIN envolver en el eje de latitud (== tecto.rolly): las filas
    que saldrian por un polo se sustituyen por la fila del borde (replicada).
    El eje X (longitud) sigue usando np.roll periodico."""
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

def grad_periodic(f):
    """Gradiente centrado (== tecto.grad_periodic): periodico en X, unilateral
    (borde replicado) en Y."""
    fy = (rolly(f, -1) - rolly(f, 1)) * 0.5
    fx = (np.roll(f, -1, 1) - np.roll(f, 1, 1)) * 0.5
    return fx, fy

def upsample(f, ny, nx):
    """Bilineal (== tecto.upsample): periodico en X, recortado en Y. Aqui no se
    usa para el manto sino para difundir campos gruesos si hiciera falta; se
    conserva por compatibilidad."""
    y = np.arange(ny) * f.shape[0] / ny
    x = np.arange(nx) * f.shape[1] / nx
    y0 = np.floor(y).astype(int); x0 = np.floor(x).astype(int)
    fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
    y1 = np.minimum(y0 + 1, f.shape[0] - 1); x1 = (x0 + 1) % f.shape[1]
    return (f[np.ix_(y0, x0)] * (1 - fy) * (1 - fx) + f[np.ix_(y0, x1)] * (1 - fy) * fx
            + f[np.ix_(y1, x0)] * fy * (1 - fx) + f[np.ix_(y1, x1)] * fy * fx)

def _advect(f, u, v, yy, xx):
    """Adveccion semi-lagrangiana con backtrace bilineal (dt=1): periodica en X,
    recortada en Y (nada cruza los polos). Adaptada de tecto.advect: recibe las
    mallas base `yy,xx` YA calculadas para no rehacer meshgrid en cada una de
    las ~80 iteraciones del bucle de humedad (el meshgrid por-llamada dominaba
    el costo)."""
    ny, nx = f.shape
    sx = (xx - u) % nx
    sy = np.clip(yy - v, 0.0, ny - 1)
    x0 = np.floor(sx).astype(np.intp); y0 = np.floor(sy).astype(np.intp)
    fx = sx - x0; fy = sy - y0
    # (xx-u) % nx puede devolver exactamente nx por redondeo float -> envolver
    x0 %= nx
    x1 = (x0 + 1) % nx; y1 = np.minimum(y0 + 1, ny - 1)
    return (f[y0, x0] * (1 - fx) * (1 - fy) + f[y0, x1] * fx * (1 - fy)
            + f[y1, x0] * (1 - fx) * fy + f[y1, x1] * fx * fy)

def _suaviza(f, pasadas=1):
    """Difusion isotropa por promedio de 5 puntos (blur): periodica en X,
    Neumann (borde replicado) en Y."""
    for _ in range(pasadas):
        f = 0.2 * (f + rolly(f, 1) + rolly(f, -1)
                   + np.roll(f, 1, 1) + np.roll(f, -1, 1))
    return f

def _upsample_bicubico_a(f, ny, nx):
    """Bicubico periodico via PIL a una resolucion destino (ny,nx) ARBITRARIA
    (== tecto._upsample_bicubico, pero a shape en vez de factor entero: el clima
    se capa por slicing y el aumento campo->detalle puede no ser entero).
    Rellena un margen (periodico en X, replicado en Y), escala y recorta:
    continuo y sin los rombos que la bilineal deja a grandes aumentos. Es el
    helper que usa render_clima_detalle para llevar los campos continuos (tair,
    precip, sst...) a plena resolucion."""
    m = 4
    fh, fw = f.shape
    # el margen tambien se escala (aprox); recortarlo devuelve exactamente (ny,nx)
    my = max(1, int(round(m * ny / fh))); mx = max(1, int(round(m * nx / fw)))
    g = np.pad(np.asarray(f, np.float32), ((m, m), (0, 0)), mode="edge")
    g = np.pad(g, ((0, 0), (m, m)), mode="wrap")
    im = Image.fromarray(g, mode="F").resize(
        (nx + 2 * mx, ny + 2 * my), Image.BICUBIC)
    a = np.asarray(im, np.float32)
    return a[my:my + ny, mx:mx + nx]

# ============================ simulacion ====================================

def simular_clima(elev, temperatura=0.0, precipitaciones=1.0, humedad=None,
                  solo_corrientes=False):
    """Calcula el clima snapshot de una geografia.

    elev: array (n,n) float en -1..1 (0 = linea de costa, ya con eustasia).
    precipitaciones: dial 0.2 (arido) .. 1 (normal) .. 2 (muy humedo); escala
    la evaporacion/lluvia. `humedad` es el alias retrocompatible del mismo
    dial (nombre viejo): si se pasa, manda.
    solo_corrientes: corta tras la circulacion oceanica y devuelve solo
    {cu, cv, sst, sst_anom, psi} (lo usa `detallar` para reutilizar las
    corrientes del cuadro original sin pagar lluvia/drenaje/biomas).
    Devuelve dict de campos (n,n) segun el contrato del plan.
    """
    if humedad is not None:
        precipitaciones = humedad
    elev = np.asarray(elev, np.float64)
    n = elev.shape[0]
    tierra = elev > 0.0
    mar = ~tierra
    # rng LOCAL de semilla fija: solo para romper empates del drenaje. JAMAS el
    # rng global de tecto (la continuacion de mundos debe seguir bit-exacta).
    rng_local = np.random.default_rng(12345)

    # mallas base para la adveccion (una sola vez)
    yy, xx = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    yy = yy.astype(np.float64); xx = xx.astype(np.float64)

    # latitud por fila: 1 = polo N .. 0 = ecuador .. -1 = polo S
    lat_norm = np.linspace(1.0, -1.0, n)[:, None]      # (n,1)
    lat_abs = np.abs(lat_norm)
    lat_deg = lat_norm * 90.0                          # grados con signo
    alat = np.abs(lat_deg)

    # ---------------- 1. temperatura del aire (tair) ----------------
    # Base latitudinal: caliente en el ecuador, frio en los polos. El dial
    # `temperatura` desplaza TODA la curva (invernadero <-> glaciacion global).
    t_ecuador = 0.78 + 0.95 * temperatura
    tair = t_ecuador - 1.55 * lat_abs ** 2 * np.ones_like(elev)
    # Enfriamiento por altitud (lapse rate): solo cuenta la parte emergida.
    alt = np.clip(elev, 0.0, None)
    tair = tair - 1.30 * alt
    # Continentalidad: los interiores son mas extremos. `maritimidad` = mascara
    # de mar difundida tierra adentro (1 cerca del mar, 0 en el interior
    # profundo). Enfria un poco la media anual del interior (los inviernos
    # continentales pesan mas que los veranos) -> refuerza estepas frias.
    maritimidad = _suaviza(mar.astype(np.float64), 12)
    continentalidad = np.clip(1.0 - maritimidad, 0.0, 1.0) * tierra
    tair = tair - 0.12 * continentalidad

    # ---------------- 2. vientos (celulas de Hadley) ----------------
    # Perfil ZONAL u(lat) por bandas, suma de gaussianas (patron - + - de las
    # tres celulas): alisios del este (u<0) en el tropico, westerlies (u>0) en
    # latitudes medias, estes polares (u<0) debiles.
    uz = (-0.85 * np.exp(-((alat - 15.0) / 15.0) ** 2)      # alisios del este
          + 1.00 * np.exp(-((alat - 47.0) / 15.0) ** 2)     # westerlies
          - 0.40 * np.exp(-((alat - 78.0) / 12.0) ** 2))    # estes polares
    # Perfil MERIDIONAL relativo m(|lat|): + = hacia el ecuador. En los alisios
    # el aire converge al ecuador (ITCZ); en los westerlies deriva al polo.
    mmer = (0.35 * np.exp(-((alat - 15.0) / 15.0) ** 2)     # hacia el ecuador
            - 0.22 * np.exp(-((alat - 47.0) / 15.0) ** 2)   # hacia el polo
            - 0.08 * np.exp(-((alat - 78.0) / 12.0) ** 2))
    signo = np.sign(lat_norm)     # +1 hemisferio N, -1 hemisferio S
    vu = (uz * np.ones_like(elev)) * 1.0                    # componente x (este+)
    vv = (signo * mmer * np.ones_like(elev)) * 1.0          # componente y (sur+)
    # Desviacion orografica: el viento rodea las montanas (se desvia pendiente
    # abajo). Pequena, para no matar el ascenso orografico que genera la lluvia.
    gx_e, gy_e = grad_periodic(elev)
    vu = vu - 0.25 * gx_e * tierra
    vv = vv - 0.25 * gy_e * tierra
    vu = _suaviza(vu, 1); vv = _suaviza(vv, 1)

    # ---------------- 3. corrientes marinas + SST ----------------
    # Las corrientes emergen de sus GENERADORES fisicos (no de una rotacion fija):
    #   (a) deriva de Ekman del viento, desviada por Coriolis (a la DERECHA en el
    #       hemisferio N, a la IZQUIERDA en el S);
    #   (b) giros por el ROTACIONAL del esfuerzo del viento (funcion de corriente
    #       barotropica que cierra los giros contra los continentes);
    #   (c) tangencia a la costa (corrientes de borde occidental);
    #   (d) afloramiento (upwelling) que enfria los bordes orientales.

    # (a) DERIVA DE EKMAN con signo de Coriolis por hemisferio. Se rota el
    # esfuerzo del viento `signo*25` grados: +25 en el N (a la derecha), -25 en el
    # S (a la izquierda); en el ecuador signo=0 y no hay desviacion.
    ang = signo * np.deg2rad(25.0)                 # (n,1) por fila
    ce = np.cos(ang); se = np.sin(ang)
    eu = (ce * vu - se * vv) * 0.55 * mar
    ev = (se * vu + ce * vv) * 0.55 * mar

    # (b) GIROS POR ROTACIONAL DEL ESFUERZO DEL VIENTO. curl = dvv/dx - dvu/dy.
    # Se resuelve la funcion de corriente barotropica psi de la Poisson
    # ∇²psi = curl por relajacion de Jacobi (promedio de 4 vecinos - curl/4),
    # anclada a psi=0 en tierra (Dirichlet en las costas -> los giros cierran
    # contra los continentes). La velocidad geostrofica es (gu,gv)=(-dpsi/dy,
    # +dpsi/dx). El signo de la fuente esta elegido para que en los subtropicos
    # del N (entre alisios ~15 y westerlies ~47, donde con y=sur+ resulta curl>0)
    # psi sea un minimo y el giro salga ANTICICLONICO (horario): al oeste hacia el
    # polo, al este hacia el ecuador (que alimenta el afloramiento de borde este).
    dvv_dx, _ = grad_periodic(vv)
    _, dvu_dy = grad_periodic(vu)
    curl = (dvv_dx - dvu_dy) * mar
    # Efecto BETA (Stommel): Coriolis crece con la latitud, y ese gradiente
    # rompe la simetria este-oeste de los giros. Se anade el termino
    # beta*dpsi/dx a la Poisson (r∇²psi + beta*psi_x = curl): la solucion se
    # APRIETA contra el borde OESTE de cada cuenca -> corrientes de borde
    # occidental estrechas e intensas (Golfo/Kuroshio) y retorno oriental ancho
    # y lento, como en los oceanos terrestres. BETA < 2 mantiene positivos los
    # coeficientes del Jacobi (estable).
    # 400 iteraciones: con menos el Jacobi no converge y el sesgo beta ni
    # aparece (medido en cuenca sintetica: ratio oeste/este 0.8 con 60 iters,
    # 2.8 con 400).
    BETA = 1.2
    psi = np.zeros_like(elev)
    for _ in range(400):
        pe = np.roll(psi, -1, 1); pw = np.roll(psi, 1, 1)
        psi = 0.25 * (rolly(psi, 1) + rolly(psi, -1) + pe + pw
                      - curl + 0.5 * BETA * (pe - pw))
        psi *= mar                                 # Dirichlet: psi=0 en tierra
    gpx, gpy = grad_periodic(psi)
    gu = -gpy * mar
    gv = gpx * mar
    # Ganancia de los giros normalizada a la deriva de Ekman (robusta a la
    # resolucion): que su magnitud tipica sea ~0.7x la de Ekman -> giros visibles
    # sin desbordar el tope de estabilidad al sumarlos a la deriva.
    if mar.any():
        rms_ek = float(np.sqrt(np.mean(eu[mar] ** 2 + ev[mar] ** 2))) + 1e-9
        rms_gy = float(np.sqrt(np.mean(gu[mar] ** 2 + gv[mar] ** 2))) + 1e-9
    else:
        rms_ek = rms_gy = 1.0
    GYRE_RATIO = 0.70
    gan = GYRE_RATIO * rms_ek / rms_gy
    cu = (eu + gan * gu) * mar
    cv = (ev + gan * gv) * mar

    # (c) TANGENCIA A LA COSTA: la corriente debe ser TANGENTE a la costa. La
    # normal a la costa apunta de mar a tierra ~ gradiente de la mascara de tierra
    # difundida. Se resta la componente que entra en tierra -> el flujo bloqueado
    # DOBLA por la costa y se concentran las corrientes de borde occidental.
    tierra_soft = _suaviza(tierra.astype(np.float64), 3)
    nnx, nny = grad_periodic(tierra_soft)
    nrm = np.hypot(nnx, nny) + 1e-9
    nnx /= nrm; nny /= nrm
    for _ in range(6):
        dot = cu * nnx + cv * nny
        entra = np.clip(dot, 0.0, None)     # componente hacia tierra
        cu = cu - entra * nnx
        cv = cv - entra * nny
        cu = _suaviza(cu, 1) * mar
        cv = _suaviza(cv, 1) * mar
    # cap suave para que la adveccion de SST sea estable
    vel = np.hypot(cu, cv); tope = 0.9
    exceso = vel > tope
    cu[exceso] *= tope / vel[exceso]; cv[exceso] *= tope / vel[exceso]

    # (c2) COMPONENTE TERMICA (geostrofica): el agua calida abomba la
    # superficie (altura dinamica ~ SST) y la rotacion desvia el flujo A LO
    # LARGO de las isotermas: horario alrededor de lo calido en el hemisferio
    # N, antihorario en el S (en el ecuador signo=0 y no aporta). Se estima una
    # SST provisional advectada por deriva+giros y su gradiente suavizado da la
    # componente termica -> refuerza las lenguas calidas de borde occidental y
    # el flujo zonal de latitudes medias hacia el este.
    sst_perfil = t_ecuador - 1.55 * lat_abs ** 2 * np.ones_like(elev)
    sst_prov = sst_perfil.copy()
    for _ in range(12):
        sst_prov = _advect(sst_prov, cu, cv, yy, xx)
        sst_prov = sst_prov + 0.15 * (sst_perfil - sst_prov)
    h_din = _suaviza(np.where(mar, sst_prov, sst_perfil), 4)
    ghx, ghy = grad_periodic(h_din)
    tu = (signo * ghy) * mar          # con y=sur+: calor al sur (ecuador) en el
    tv = (-signo * ghx) * mar         # N -> flujo al este; giro horario en calido
    if mar.any():
        rms_t = float(np.sqrt(np.mean(tu[mar] ** 2 + tv[mar] ** 2))) + 1e-9
    else:
        rms_t = 1.0
    TERM_RATIO = 0.35                 # ganancia termica ~0.35x la deriva de Ekman
    cu = cu + (TERM_RATIO * rms_ek / rms_t) * tu
    cv = cv + (TERM_RATIO * rms_ek / rms_t) * tv
    # re-tangencia breve y nuevo cap tras sumar la componente termica
    for _ in range(3):
        dot = cu * nnx + cv * nny
        entra = np.clip(dot, 0.0, None)
        cu = cu - entra * nnx
        cv = cv - entra * nny
        cu = _suaviza(cu, 1) * mar
        cv = _suaviza(cv, 1) * mar
    vel = np.hypot(cu, cv)
    exceso = vel > tope
    cu[exceso] *= tope / vel[exceso]; cv[exceso] *= tope / vel[exceso]

    # Funcion de corriente del flujo TOTAL (rotacional de cu,cv con psi=0 en
    # tierra): sus extremos localizan los GIROS cerrados para dibujar los
    # circuitos de corriente en los renders y la web.
    dcv_dx, _ = grad_periodic(cv)
    _, dcu_dy = grad_periodic(cu)
    zeta = (dcv_dx - dcu_dy) * mar
    psi_tot = np.zeros_like(elev)
    for _ in range(300):
        psi_tot = 0.25 * (rolly(psi_tot, 1) + rolly(psi_tot, -1)
                          + np.roll(psi_tot, 1, 1) + np.roll(psi_tot, -1, 1)
                          - zeta)
        psi_tot *= mar

    # (d) AFLORAMIENTO (upwelling) + SST. Donde las corrientes DIVERGEN sobre el
    # mar (div>0: el agua superficial se va, tipico de bordes orientales y del
    # ecuador) aflora agua fria profunda. La SST advectada por (cu,cv) se relaja
    # hacia un perfil REDUCIDO por el afloramiento -> costas orientales frias
    # (Atacama/Namib) que despues suprimen la evaporacion.
    divx, _ = grad_periodic(cu)
    _, divy = grad_periodic(cv)
    upw = np.clip((divx + divy), 0.0, None) * mar
    if (upw > 0).any():
        esc_upw = np.percentile(upw[upw > 0], 90) + 1e-9
    else:
        esc_upw = 1.0
    upwn = np.clip(upw / esc_upw, 0.0, 1.0)
    UPW_COOL = 0.30                                 # enfriamiento max por afloramiento
    # SST: perfil latitudinal (como tair pero sin altitud, solo mar; `sst_perfil`
    # ya calculado en (c2)) advectado por (cu,cv) con relajacion debil al
    # OBJETIVO (perfil - afloramiento) -> lenguas calidas hacia los polos, frias
    # hacia el ecuador segun el lado de la cuenca, y bordes orientales frios.
    sst_obj = sst_perfil - UPW_COOL * upwn         # objetivo con agua fria aflorada
    sst = sst_perfil.copy()
    for _ in range(30):
        sst = _advect(sst, cu, cv, yy, xx)
        sst = sst + 0.12 * (sst_obj - sst)         # relajacion al objetivo
    sst[tierra] = sst_perfil[tierra]               # en tierra: valor de referencia
    sst_anom = (sst - sst_perfil) * mar            # anomalia (calida/fria)

    if solo_corrientes:
        return {"cu": cu, "cv": cv, "sst": np.where(mar, sst, 0.0),
                "sst_anom": sst_anom, "psi": psi_tot}

    # Influencia de corrientes en la temperatura del aire: la costa junto a
    # corriente calida se templa y junto a fria se enfria. Se difunde la anomalia
    # de SST bastantes celdas tierra adentro (acople reforzado: una corriente
    # calida debe notarse en el clima de toda la franja costera, no solo en la
    # orilla — piensa en la corriente del Golfo sobre Europa occidental).
    anom_costa = _suaviza(sst_anom, 9)
    tair = tair + 0.65 * anom_costa * maritimidad

    # ---------------- 4. humedad y lluvia (precip) ----------------
    # El vapor `q` nace sobre el mar: la evaporacion crece con la SST (mar frio
    # evapora poco -> costas junto a corriente fria = desierto costero tipo
    # Atacama/Namib). El dial `precipitaciones` escala la evaporacion.
    # (el dial NO multiplica aqui: el ciclo de lluvia es lineal en la
    # evaporacion y la normalizacion lo dividiria de vuelta —el dial viejo era
    # un no-op sobre la precip—; se aplica en _normaliza_precip, donde SI
    # cambia el nivel final de lluvia que ven biomas, Koppen y rios)
    evap = np.clip((sst + 0.15) * 0.6, 0.03, 1.2) * mar
    # Acoplamiento corriente->evaporacion REFORZADO: las corrientes calidas
    # (anom>0) humedecen la costa a sotavento y las frias/afloramiento (anom<0,
    # bordes orientales) la secan (desiertos costeros). Se mantienen las
    # invariantes (barlovento>sotavento, ecuador>lat25).
    evap = evap * np.clip(1.0 + 0.55 * sst_anom, 0.25, 1.8)
    # ITCZ: franja ecuatorial de conveccion profunda.
    itcz = np.exp(-((lat_deg / 9.0) ** 2)) * np.ones_like(elev)
    calidez = np.clip(tair, 0.0, 1.0)
    # Reciclaje continental (evapotranspiracion): una fraccion de la lluvia
    # caida vuelve al aire y sigue viento abajo. Sin esto el vapor marino se
    # agota a pocas celdas de la costa y TODO interior salia desierto.
    reciclaje = (0.20 + 0.30 * calidez) * tierra
    adv_asc = np.clip(vu * gx_e + vv * gy_e, 0.0, None)       # ascenso orografico
    K_HUM = 64
    K_BASE, K_OROG, K_CONV = 0.028, 0.85, 0.060

    def _ciclo_lluvia(fuente_rib=None):
        """Adveccion del vapor con lluvia base + orografica + convectiva.
        `fuente_rib`: aporte de vapor por evapotranspiracion riberena (rios,
        lagos y grandes cuencas del pase hidrologico previo), por iteracion."""
        q = evap.copy()
        pr = np.zeros_like(elev)
        for _ in range(K_HUM):
            q = _advect(q, vu, vv, yy, xx)
            # sobre el mar el aire se re-satura hacia la evaporacion local
            q = np.where(mar, np.maximum(q, evap), q)
            if fuente_rib is not None:
                q = q + fuente_rib
            # lluvia sobre tierra
            r = (K_BASE * q                                   # lluvia base
                 + K_OROG * q * adv_asc                       # orografica (barlovento)
                 + K_CONV * q * itcz * calidez)               # conveccion ITCZ
            r = r * tierra
            r = np.minimum(r, q)      # no puede llover mas vapor del que hay
            q = q - r * (1.0 - reciclaje)   # parte se re-evapora y sigue
            pr = pr + r
        return pr

    def _normaliza_precip(pr):
        # normalizar a 0..1 por un percentil MEDIO-ALTO con gamma < 1: el viejo
        # percentil 99 aplastaba casi toda la tierra hacia los tramos aridos de
        # Whittaker/Koppen y el mapa salia sesgado a desierto. El dial
        # `precipitaciones` escala AQUI el nivel final (con clip: un mundo muy
        # humedo satura amplias zonas en 1).
        if tierra.any():
            pref = np.percentile(pr[tierra], 92) + 1e-9
        else:
            pref = 1.0
        return np.clip(precipitaciones * pr / pref, 0.0, 1.0) ** 0.85

    # PASE 1: lluvia puramente marina (los rios aun no existen)
    precip = _normaliza_precip(_ciclo_lluvia())

    # ---------------- 5. glaciaciones (hielo) ----------------
    # Tierra: por debajo de un umbral de temperatura crece el casquete/glaciar
    # (rampa suave). Crece al bajar el dial `temperatura` porque tair baja con
    # el. Los glaciares de montana salen solos (la altitud enfrio tair).
    hielo_tierra = np.clip((-0.30 - tair) / 0.30, 0.0, 1.0) * tierra
    # Mar: banquisa donde la SST cae por debajo del punto de congelacion.
    umbral_mar = -0.55
    hielo_mar = np.clip((umbral_mar - sst) / 0.20, 0.0, 1.0) * mar
    hielo = np.clip(hielo_tierra + hielo_mar, 0.0, 1.0)

    # ---------------- 6. rios, lagos y estuarios ----------------
    # Se rompe la horizontalidad de las mesetas con ruido determinista minusculo
    # (rng LOCAL) para que el descenso mas empinado tenga siempre un ganador.
    elev_h = elev + rng_local.random(elev.shape) * 1e-4
    # Direccion de drenaje: descenso mas empinado a 8 vecinos (periodico en X,
    # sin cruzar los polos). Se apila la elevacion de los 8 vecinos y se toma
    # el minimo (vectorizado).
    offs = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
            (0, 1), (1, -1), (1, 0), (1, 1)]
    vecinos = np.stack([np.roll(rolly(elev_h, -dy), -dx, 1)
                        for dy, dx in offs], axis=0)          # (8,n,n)
    kmin = np.argmin(vecinos, axis=0)                         # dir del mas bajo
    vmin = np.take_along_axis(vecinos, kmin[None], 0)[0]      # su elevacion
    dyv = np.array([o[0] for o in offs]); dxv = np.array([o[1] for o in offs])
    ry = np.clip(yy.astype(np.intp) + dyv[kmin], 0, n - 1)    # Y no envuelve
    rx = (xx.astype(np.intp) + dxv[kmin]) % n
    receptor = ry * n + rx                                    # indice destino plano
    idx = (yy.astype(np.intp) * n + xx.astype(np.intp))
    # Pozo (minimo local) o celda de mar: el agua se detiene aqui (receptor=self).
    pozo = (vmin >= elev_h) | mar
    receptor = np.where(pozo, idx, receptor)
    receptor_f = receptor.ravel()
    pozo2d = pozo & tierra
    tierra_libre = tierra & (hielo_tierra < 0.5)
    vecino_mar = np.zeros_like(mar)
    for dy, dx in offs:
        vecino_mar |= np.roll(rolly(mar, dy), dx, 1)
    interior = tierra & ~vecino_mar
    N = elev.size
    # Umbral de rio ABSOLUTO por celda de tierra (no percentil ni fraccion del
    # agua real: ambos son invariantes a la escala de la lluvia). El viejo
    # percentil 95 fijaba SIEMPRE el mismo 5% de celdas como rio, lloviera lo
    # que lloviera; con umbral fijo la cantidad de rios EMERGE del calculo:
    # mundo humedo -> mas caudal -> mas celdas lo superan -> mas rios.
    UMBRAL_RIO = 4.5e-4 * float(tierra.sum())

    def _drenaje(pr):
        """Acumulacion de caudal (scatter-add via bincount) sembrando la precip
        dada y umbrales absolutos para rios/lagos. Devuelve tambien el umbral
        para construir `ribera` en la misma escala."""
        peso = ((pr + 0.02) * tierra * (1.0 - 0.9 * hielo_tierra)).ravel()
        total = peso.copy()
        contrib = peso.copy()
        for _ in range(96):
            contrib = np.bincount(receptor_f, weights=contrib, minlength=N)
            total = total + contrib
            if contrib.sum() < 1e-6:
                break
        cau = total.reshape(elev.shape)
        umb = UMBRAL_RIO
        rio = (cau > umb) & tierra_libre
        # Lagos: pozos interiores (endorreicos) donde el caudal se estanca.
        lag = pozo2d & interior & (cau > 0.6 * umb)
        # Estuarios: celda de rio con vecino de mar (desembocadura); se dilata
        # 1 px para que se vea.
        est = rio & vecino_mar
        est_dil = est.copy()
        for dy, dx in offs:
            est_dil |= np.roll(rolly(est, dy), dx, 1)
        return cau, rio, lag, est_dil & tierra, umb

    def _ribera_de(cau, rio, lag, umb):
        """Banda riberena (0..1): arranca en rios|lagos, suma el caudal alto
        (rampa relativa al umbral de rio) y se DILATA unas celdas para que la
        influencia abrace los cauces."""
        rib = (rio | lag).astype(np.float64)
        rib = np.maximum(rib, np.clip((cau - 0.5 * umb) / (4.0 * umb + 1e-9),
                                      0.0, 1.0))
        rib *= tierra
        for _ in range(2):
            dil = rib.copy()
            for dy, dx in offs:
                dil = np.maximum(dil, np.roll(rolly(rib, dy), dx, 1) * 0.85)
            rib = dil
        return np.clip(_suaviza(rib, 1), 0.0, 1.0) * tierra

    caudal, rios, lagos, estuarios, umb_rio = _drenaje(precip)
    ribera = _ribera_de(caudal, rios, lagos, umb_rio)

    # ---------------- 6b. realimentacion rios -> humedad -> clima ----------
    # PASE 2: los rios, lagos y grandes cuencas evapotranspiran; ese vapor
    # viaja viento abajo y vuelve a llover. La precip FINAL (la mostrada, la de
    # Koppen y la de biomas) ya siente la red fluvial, y el drenaje se recalcula
    # con ella (los rios se auto-refuerzan de forma verosimil: valles humedos).
    fuente_rib = 0.055 * ribera * (0.35 + 0.65 * calidez) * tierra
    precip = _normaliza_precip(_ciclo_lluvia(fuente_rib))
    caudal, rios, lagos, estuarios, umb_rio = _drenaje(precip)
    ribera = _ribera_de(caudal, rios, lagos, umb_rio)

    # ---------------- 7. biomas (Whittaker simplificado) ----------------
    # se clasifica con la precip + bono ribereno (no la precip real devuelta): en
    # frio -> taiga, templado -> bosque templado, calido -> bosque humedo, sin
    # forzar bosque sobre hielo ni desiertos genuinos lejos del agua.
    precip_bioma = np.clip(precip + BONO_RIBERA * ribera, 0.0, 1.0)
    bioma = _clasificar_biomas(tair, precip_bioma, hielo_tierra, tierra)

    return {
        "tair": tair,
        "sst": np.where(mar, sst, 0.0),
        "vu": vu, "vv": vv,
        "cu": cu, "cv": cv,
        "precip": precip,
        "hielo": hielo,
        "caudal": caudal,
        "rios": rios,
        "lagos": lagos,
        "estuarios": estuarios,
        "bioma": bioma,
        # extras utiles para el render (no rompen el contrato: son claves de mas)
        "sst_anom": sst_anom,
        "tierra": tierra,
        # funcion de corriente del flujo total: localiza los giros oceanicos
        # (circuitos cerrados de corriente) para los renders y la capa web
        "psi": psi_tot,
        # humedad riberena (0..1): reutilizable por los renders de detalle/HD para
        # empujar los biomas hacia bosque a lo largo de los cauces
        "ribera": ribera,
        # direccion de drenaje (indice plano ry*n+rx de la celda receptora aguas
        # abajo): la usa render_clima_detalle para trazar los rios como lineas
        # vectoriales celda->receptor en vez de bloques upsampleados
        "receptor": receptor,
    }


def _clasificar_biomas(tair, precip, hielo_tierra, tierra):
    """Clasificacion Whittaker simplificada sobre temperatura x precipitacion.
    Devuelve int8 con el id de bioma en tierra y -1 en el mar. Los umbrales
    estan calibrados para que con temperatura=0, precipitaciones=1 salga un reparto
    verosimil (selva ecuatorial, desiertos subtropicales, taiga/tundra polares)."""
    b = np.full(tair.shape, -1, np.int8)
    t = tair; p = precip
    # bandas de temperatura
    muy_frio = t < -0.50
    frio = (t >= -0.50) & (t < -0.12)
    templado = (t >= -0.12) & (t < 0.42)
    calido = t >= 0.42
    # --- muy frio: tundra (el hielo se pinta aparte) ---
    b = np.where(tierra & muy_frio, 1, b)
    # --- frio: taiga si humedo; estepa/desierto frio si seco ---
    b = np.where(tierra & frio & (p >= 0.28), 2, b)
    b = np.where(tierra & frio & (p >= 0.12) & (p < 0.28), 3, b)
    b = np.where(tierra & frio & (p < 0.12), 5, b)
    # --- templado: bosque / pradera / estepa / desierto frio ---
    b = np.where(tierra & templado & (p >= 0.45), 7, b)
    b = np.where(tierra & templado & (p >= 0.25) & (p < 0.45), 6, b)
    b = np.where(tierra & templado & (p >= 0.10) & (p < 0.25), 3, b)
    b = np.where(tierra & templado & (p < 0.10), 5, b)
    # --- calido: bosque humedo / bosque seco / sabana / desierto ---
    b = np.where(tierra & calido & (p >= 0.55), 10, b)
    b = np.where(tierra & calido & (p >= 0.32) & (p < 0.55), 8, b)
    b = np.where(tierra & calido & (p >= 0.14) & (p < 0.32), 9, b)
    b = np.where(tierra & calido & (p < 0.14), 4, b)
    # hielo permanente (casquete/glaciar) manda sobre todo
    b = np.where(tierra & (hielo_tierra >= 0.5), 0, b)
    return b


# ============================ render ========================================
# Gradiente de mar por SST: frio -> templado -> calido.
_PALETA_SST = np.array([
    (-1.0, 18, 38, 95), (0.0, 35, 90, 150), (1.0, 0, 140, 155),
], dtype=float)

def render_clima(campos, elev):
    """PIL.Image del mapa climatico (misma resolucion que elev): mar por SST,
    banquisa, biomas con sombreado por pendiente, rios/lagos/estuarios y flechas
    de corrientes tintadas calida/fria."""
    elev = np.asarray(elev, np.float64)
    n = elev.shape[0]
    tierra = elev > 0.0
    mar = ~tierra
    tair = campos["tair"]; precip = campos["precip"]
    sst = campos["sst"]; hielo = campos["hielo"]
    bioma = campos["bioma"]
    rios = campos["rios"]; lagos = campos["lagos"]; estuarios = campos["estuarios"]
    cu = campos["cu"]; cv = campos["cv"]
    sst_anom = campos.get("sst_anom", np.zeros_like(elev))

    img = np.empty(elev.shape + (3,))

    # --- mar: gradiente por SST + banquisa ---
    sea = np.empty(elev.shape + (3,))
    for ch in range(3):
        sea[..., ch] = np.interp(sst, _PALETA_SST[:, 0], _PALETA_SST[:, ch + 1])
    banquisa = np.clip(hielo * mar, 0.0, 1.0)[..., None]
    sea = sea * (1 - banquisa) + np.array([214, 228, 240]) * banquisa

    # --- tierra: color de bioma ---
    land = _BIOMA_RGB[np.clip(bioma, 0, None)]          # (-1 se recorta a 0; se
    land = np.where(tierra[..., None], land, 0.0)        # enmascara con `tierra`)

    img = np.where(tierra[..., None], land, sea)

    # sombreado por pendiente (mismas 3 lineas que tecto.render)
    gx, gy = grad_periodic(elev)
    shade = np.clip(1.0 + 2.2 * (gx - gy), 0.78, 1.22)
    img = img * shade[..., None]

    # hielo en tierra: mezclar hacia blanco glaciar
    hg = np.clip(hielo * tierra, 0.0, 1.0)[..., None]
    img = img * (1 - hg) + np.array([238, 244, 250]) * hg

    img = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im, "RGBA")

    # --- lagos, rios y estuarios ---
    # lagos primero (por debajo de los rios)
    ys, xs = np.nonzero(lagos)
    for y, x in zip(ys, xs):
        d.point((x, y), fill=(60, 130, 200, 255))
    # rios: alpha segun caudal (los caudalosos mas opacos)
    caudal = campos["caudal"]
    if rios.any():
        cmax = float(caudal[rios].max()) + 1e-9
        ys, xs = np.nonzero(rios)
        cv_r = caudal[ys, xs]
        for y, x, c in zip(ys, xs, cv_r):
            a = int(120 + 135 * min(c / cmax, 1.0))
            d.point((x, y), fill=(40, 90, 180, a))
    # estuarios: puntos turquesa
    ys, xs = np.nonzero(estuarios)
    for y, x in zip(ys, xs):
        d.point((x, y), fill=(70, 200, 220, 255))

    # --- flechas de corrientes sobre el mar, tintadas por anomalia de SST ---
    _flechas_corriente(d, cu, cv, sst_anom, mar, n)
    # --- circuitos cerrados (giros oceanicos) donde la corriente es marcada ---
    circ = circuitos_corriente(cu, cv, sst_anom, mar, campos.get("psi"))
    _dibuja_circuitos(d, circ, n, n)

    return im


def render_clima_detalle(campos, elev_detalle, elev_c, temperatura=0.0):
    """PIL.Image del mapa fisico-climatico a la resolucion COMPLETA de
    `elev_detalle` (ny,nx), a partir de los `campos` calculados a la resolucion
    capada de `elev_c` (nc_y,nc_x). Es el segundo mapa de tecto.detallar: como
    render_clima pero con el relieve y la geografia DETALLADOS.

    La fisica no cambia (los campos ya vienen calculados); esto es solo render.
    Diferencias con render_clima (que pinta a la resolucion de los campos):
      - los biomas se RECLASIFICAN pixel a pixel con la geografia fina, no se
        upsamplea el id de bioma (costas rotas, islitas, mares interiores finos y
        picos de montana enfriados por altitud salen nitidos);
      - los campos continuos (tair, precip, sst, hielo) se llevan a plena
        resolucion por bicubico periodico;
      - rios/lagos/estuarios/corrientes se dibujan como TRAZOS vectoriales
        escalados, no como mascaras upsampleadas (evita bloques de kc x kc).
    Todo float32 y con `del` agresivo: a 8192^2 el RGB solo ya pesa ~0.8 GB."""
    elev_detalle = np.asarray(elev_detalle, np.float32)
    elev_c = np.asarray(elev_c, np.float64)
    ny, nx = elev_detalle.shape
    nc_y, nc_x = elev_c.shape
    ky = ny / nc_y; kx = nx / nc_x            # factor de aumento campo->detalle

    # --- 1. campos continuos a plena resolucion (bicubico periodico) ---
    tair_up = _upsample_bicubico_a(campos["tair"], ny, nx)
    precip_up = np.clip(_upsample_bicubico_a(campos["precip"], ny, nx), 0.0, 1.0)
    hielo_up = np.clip(_upsample_bicubico_a(campos["hielo"], ny, nx), 0.0, 1.0)
    # altitud capada upsampleada: la usamos para "des-correjir" el lapse rate
    # grueso y volver a aplicarlo con la altitud FINA (ver abajo)
    alt_up = _upsample_bicubico_a(np.clip(elev_c, 0.0, None), ny, nx)

    # --- 2. reclasificacion de biomas a plena resolucion (la clave del detalle) ---
    # la geografia fina define la tierra: costas, islitas y mares interiores finos
    # salen solos de elev_detalle>0 sin arrastrar los bloques de la malla capada
    tierra_det = elev_detalle > np.float32(0.0)
    mar_det = ~tierra_det
    # correccion de temperatura por la altitud FINA: se resta el lapse rate (1.30,
    # el mismo de simular_clima) evaluado sobre (altitud_fina - altitud_capada), de
    # modo que los picos que el promedio grueso no resolvia ahora se enfrian y
    # ganan glaciares/tundra de montana
    alt_det = np.clip(elev_detalle, 0.0, None)
    tair_det = tair_up - np.float32(1.30) * (alt_det - alt_up)
    del alt_up, alt_det
    # hielo en tierra fino: misma rampa que simular_clima, ya con la tair fina
    hielo_tierra_det = (np.clip((np.float32(-0.30) - tair_det) / np.float32(0.30),
                                0.0, 1.0) * tierra_det).astype(np.float32)
    # bono de humedad riberena upsampleado (empuja los biomas hacia bosque a lo
    # largo de los cauces; solo afecta a la clasificacion, no a la precip mostrada)
    ribera_c = campos.get("ribera")
    if ribera_c is None:
        ribera_c = np.zeros_like(campos["precip"])
    ribera_up = np.clip(_upsample_bicubico_a(ribera_c, ny, nx), 0.0, 1.0)
    precip_bioma = np.clip(precip_up + np.float32(BONO_RIBERA) * ribera_up, 0.0, 1.0)
    del ribera_up
    bioma_det = _clasificar_biomas(tair_det, precip_bioma, hielo_tierra_det, tierra_det)
    del tair_det, tair_up, precip_up, precip_bioma

    # --- 3+4. ensamblado del color por canal (memoria: RGB float32 gigante) ---
    img = np.empty((ny, nx, 3), np.float32)
    # mar: gradiente por SST upsampleada
    sst_up = _upsample_bicubico_a(campos["sst"], ny, nx)
    for ch in range(3):
        img[..., ch] = np.interp(sst_up, _PALETA_SST[:, 0], _PALETA_SST[:, ch + 1])
    del sst_up
    # banquisa sobre el mar (hielo del mar)
    banq = (hielo_up * mar_det).astype(np.float32)
    hielo_mar = np.array([214, 228, 240], np.float32)
    for ch in range(3):
        img[..., ch] += banq * (hielo_mar[ch] - img[..., ch])
    del banq
    # plataforma continental: aclarar sutilmente donde -0.06<elev<0 para que se
    # lean las costas, coherente con el mapa de relieve que oculta el fondo abisal
    plat = (np.clip((elev_detalle + np.float32(0.06)) / np.float32(0.06), 0.0, 1.0)
            * mar_det).astype(np.float32) * np.float32(0.16)
    for ch in range(3):
        img[..., ch] += plat * np.minimum(np.float32(44.0), np.float32(255.0) - img[..., ch])
    del plat
    # tierra: color de bioma + sombreado de relieve FINO (mismo esquema que
    # render_clima/tecto.render, algo mas suave para no saturar a esta resolucion)
    gx, gy = grad_periodic(elev_detalle)
    shade = np.clip(1.0 + 1.7 * (gx - gy), 0.82, 1.18).astype(np.float32)
    del gx, gy
    glaciar = np.array([238, 244, 250], np.float32)
    bioma_seguro = np.clip(bioma_det, 0, None)   # -1 (mar) -> 0; se enmascara luego
    for ch in range(3):
        # color de tierra: bioma * sombreado, mezclado hacia blanco glaciar
        col = _BIOMA_RGB[bioma_seguro, ch].astype(np.float32) * shade
        col += hielo_tierra_det * (glaciar[ch] - col)
        img[..., ch] = np.where(tierra_det, col, img[..., ch])
        del col
    del shade, bioma_seguro, bioma_det

    img = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(img)
    del img
    d = ImageDraw.Draw(im, "RGBA")

    # --- 5. rios, lagos y estuarios como TRAZOS vectoriales escalados ---
    # (las mascaras vienen a resolucion capada; upsamplearlas daria bloques feos
    #  de kc x kc, asi que se dibujan como geometria escalada al lienzo grande)
    rios = campos["rios"]; caudal = campos["caudal"]
    lagos = campos["lagos"]; estuarios = campos["estuarios"]
    receptor = campos.get("receptor")
    # bajo el hielo permanente no se dibuja hidrografia (el glaciar la sepulta
    # y el casquete ya va pintado de blanco): tair < -0.45 ~ mas de medio hielo
    helado = campos["tair"] < -0.45
    rios = rios & ~helado
    estuarios = estuarios & ~helado
    # y solo los lagos MUY caudalosos: cada pozo del terreno recolecta todo su
    # drenaje aguas arriba, asi que casi todos superan el caudal minimo de un
    # rio y la tierra saldria moteada de elipses; se exige el percentil 95 del
    # caudal de los rios para quedarse solo con las cuencas endorreicas grandes
    # (percentil calculado ANTES de quitar los pozos: son los rios mas caudalosos)
    umb_lago = float(np.percentile(caudal[rios], 95)) if rios.any() else np.inf
    lagos = lagos & ~helado & (caudal >= umb_lago)
    # tampoco se trazan rios en los pozos (receptor = si mismos): una linea de
    # longitud cero deja un punto suelto de 1 px (confeti); si el pozo es una
    # cuenca endorreica de verdad ya salio como lago arriba
    if receptor is not None:
        propio = np.arange(receptor.size, dtype=receptor.dtype).reshape(receptor.shape)
        rios = rios & (receptor != propio)
    ancho = max(1, int(round(min(kx, ky) / 3.0)))
    rlx = max(1.0, kx * 0.5); rly = max(1.0, ky * 0.5)
    # lagos primero (por debajo de los rios): elipse del tamano de la celda
    ys, xs = np.nonzero(lagos)
    for i, j in zip(ys, xs):
        cx = (j + 0.5) * kx; cy = (i + 0.5) * ky
        d.ellipse([cx - rlx, cy - rly, cx + rlx, cy + rly], fill=(60, 130, 200, 255))
    # rios: linea del centro de la celda al centro de su receptor aguas abajo,
    # con alpha por caudal (los caudalosos mas opacos)
    if rios.any() and receptor is not None:
        cmax = float(caudal[rios].max()) + 1e-9
        ys, xs = np.nonzero(rios)
        for i, j in zip(ys, xs):
            r = int(receptor[i, j])
            ri, rj = divmod(r, nc_x)
            a = int(120 + 135 * min(float(caudal[i, j]) / cmax, 1.0))
            x0 = (j + 0.5) * kx; y0 = (i + 0.5) * ky
            x1 = (rj + 0.5) * kx; y1 = (ri + 0.5) * ky
            # si el receptor envuelve el borde Este-Oeste (salto enorme) no cruces el lienzo:
            # traza un tramo corto en el sentido local para no rayar el mapa
            if abs(rj - j) > 1 or abs(ri - i) > 1:
                d.line([(x0, y0), (x0, y0)], fill=(40, 90, 180, a), width=ancho)
            else:
                d.line([(x0, y0), (x1, y1)], fill=(40, 90, 180, a), width=ancho)
    # estuarios: puntos turquesa escalados
    ys, xs = np.nonzero(estuarios)
    for i, j in zip(ys, xs):
        cx = (j + 0.5) * kx; cy = (i + 0.5) * ky
        d.ellipse([cx - ancho, cy - ancho, cx + ancho, cy + ancho],
                  fill=(70, 200, 220, 255))

    # --- 6. flechas de corrientes escaladas al lienzo grande ---
    cu = campos["cu"]; cv = campos["cv"]
    sst_anom = campos.get("sst_anom", np.zeros_like(elev_c))
    mar_c = ~(elev_c > 0.0)
    _flechas_corriente(d, cu, cv, sst_anom, mar_c, nc_x, escala=(kx + ky) * 0.5)
    # circuitos cerrados (giros) escalados al lienzo grande
    circ = circuitos_corriente(cu, cv, sst_anom, mar_c, campos.get("psi"))
    _dibuja_circuitos(d, circ, nc_y, nc_x, escala=(kx + ky) * 0.5)

    return im


def _flechas_corriente(d, cu, cv, sst_anom, mar, n, escala=1.0):
    """Flechas de corriente en malla gruesa sobre el mar, tintadas por la
    anomalia de SST: calida (rojo) / fria (azul). Adaptado de tecto._flechas.

    Los campos (cu,cv,sst_anom,mar) se muestrean en la malla de resolucion `n`,
    pero el DIBUJO se escala x`escala` al lienzo final: con escala=1 (default)
    pinta a la resolucion de los campos (render_clima clasico) y con escala=k
    posiciona las mismas flechas sobre el mapa detallado a plena resolucion, con
    grosor y punta proporcionales para que se lean igual de nitidas."""
    calida = np.array([230, 80, 60]); fria = np.array([90, 150, 235])
    paso = max(16, n // 12)
    s = float(escala)
    w = max(2, int(round(1.8 * s)))           # trazo grueso escalado (legible)
    for y in range(paso // 2, n - 2, paso):
        for x in range(paso // 2, n - 2, paso):
            sub = mar[y - 2:y + 3, x - 2:x + 3]
            if sub.mean() < 0.75:            # celda gruesa mayormente tierra
                continue
            du = float(cu[y - 2:y + 3, x - 2:x + 3].mean()) * 22
            dv = float(cv[y - 2:y + 3, x - 2:x + 3].mean()) * 22
            L = (du * du + dv * dv) ** 0.5
            if L < 2.0:                       # corriente casi nula
                continue
            if L > paso * 0.85:
                du *= paso * 0.85 / L; dv *= paso * 0.85 / L
            an = float(sst_anom[y - 2:y + 3, x - 2:x + 3].mean())
            t = np.clip(an / 0.25, -1, 1)     # -1 fria .. +1 calida
            col = fria + (calida - fria) * (t * 0.5 + 0.5)
            col = tuple(int(c) for c in col) + (220,)
            # posiciones y longitudes escaladas al lienzo (centro de celda gruesa)
            X, Y = x * s, y * s
            X1, Y1 = X + du * s, Y + dv * s
            ang = np.arctan2(dv, du)
            pa = (X1 - 4 * s * np.cos(ang - 0.5), Y1 - 4 * s * np.sin(ang - 0.5))
            pb = (X1 - 4 * s * np.cos(ang + 0.5), Y1 - 4 * s * np.sin(ang + 0.5))
            # trazo blanco fino debajo para legibilidad, color encima
            d.line([(X, Y), (X1, Y1)], fill=(255, 255, 255, 150), width=w + 2)
            d.line([(X, Y), (X1, Y1)], fill=col, width=w)
            d.line([pa, (X1, Y1), pb], fill=col, width=w)


# ---------------- circuitos de corriente (giros oceanicos) -----------------
# Los giros terrestres (subtropicales/subpolares) son CIRCUITOS cerrados de
# corriente. Aqui se detectan sobre la funcion de corriente psi del flujo
# total: cada extremo local de |psi| en mar abierto es un candidato a centro de
# giro y su circuito es el CONTORNO de psi a media altura entre el centro y la
# costa (psi=0). Solo se aceptan los circuitos que CIERRAN sobre si mismos y
# cuya rapidez media supera con margen a la mediana del oceano: los lazos se
# dibujan unicamente donde las corrientes son marcadas.

def _bilin_esf(F, y, x):
    """Muestreo bilineal del campo F en el punto real (y, x): periodico en X,
    recortado en Y (los polos no envuelven)."""
    ny, nx = F.shape
    y = min(max(y, 0.0), ny - 1.0)
    y0 = int(np.floor(y)); x0 = int(np.floor(x))
    fy = y - y0; fx = x - x0
    x0 %= nx
    y1 = min(y0 + 1, ny - 1); x1 = (x0 + 1) % nx
    return float(F[y0, x0] * (1 - fy) * (1 - fx) + F[y0, x1] * (1 - fy) * fx
                 + F[y1, x0] * fy * (1 - fx) + F[y1, x1] * fy * fx)


def _dist_esf(y0, x0, y1, x1, ny, nx):
    """Distancia en la malla esferica: envuelve solo en X (longitud)."""
    dy = abs(y1 - y0)
    dx = abs(x1 - x0); dx = min(dx, nx - dx)
    return (dx * dx + dy * dy) ** 0.5


def _traza_circuito(ps, gpx, gpy, cu, cv, marf, cy, cx, vmed):
    """Sigue el contorno de psi al nivel 0.55*psi(centro) partiendo del anillo
    del giro (cy,cx): paso tangente (el rotacional de psi apunta a lo largo del
    contorno, en el sentido REAL de la corriente) + correccion de Newton hacia
    el nivel. Devuelve (puntos [(x,y)...], rapidez_media) si el lazo cierra sin
    tocar tierra y es rapido; None si no."""
    ny, nx = marf.shape
    nivel = 0.55 * _bilin_esf(ps, cy, cx)
    # semilla: caminar desde el centro hacia +x y hacia -x hasta cruzar el
    # nivel del contorno (con beta el giro es asimetrico: al oeste el gradiente
    # es abrupto y cruza cerca; al este decae lento). Vale el primer cruce en
    # mar de cualquiera de los dos lados.
    seed = None
    for r in np.arange(1.0, max(ny, nx) * 0.6, 0.5):
        for lado in (1.0, -1.0):
            xs = (cx + lado * r) % nx
            if _bilin_esf(marf, cy, xs) < 0.7:
                continue                      # ese lado topo tierra: probar el otro
            if abs(_bilin_esf(ps, cy, xs)) <= abs(nivel):
                seed = (float(cy), float(xs)); break
        if seed is not None:
            break
    if seed is None:
        return None
    y, x = seed
    paso = 0.6
    puntos = [(x, y)]; raps = []
    for i in range(int(6 * max(ny, nx))):
        up = -_bilin_esf(gpy, y, x)          # rotacional de psi: tangente al
        vp = _bilin_esf(gpx, y, x)           # contorno, sentido de la corriente
        Lp = (up * up + vp * vp) ** 0.5
        if Lp < 1e-9 or _bilin_esf(marf, y, x) < 0.6:
            return None                       # contorno degenerado o toca tierra
        x += paso * up / Lp; y += paso * vp / Lp
        # correccion de Newton: reengancha el punto al nivel del contorno
        e = _bilin_esf(ps, y, x) - nivel
        gx = _bilin_esf(gpx, y, x); gy = _bilin_esf(gpy, y, x)
        g2 = gx * gx + gy * gy + 1e-12
        x = (x - e * gx / g2) % nx
        y = min(max(y - e * gy / g2, 0.0), ny - 1.0)   # Y no envuelve
        raps.append((_bilin_esf(cu, y, x) ** 2 + _bilin_esf(cv, y, x) ** 2) ** 0.5)
        puntos.append((x, y))
        if i > 15 and _dist_esf(y, x, seed[0], seed[1], ny, nx) < paso * 1.4:
            rap = float(np.mean(raps))
            if rap >= vmed * 1.15 and len(puntos) >= 20:
                return puntos, rap            # cierra y es marcadamente rapido
            return None
    return None


def circuitos_corriente(cu, cv, sst_anom, mar, psi, max_giros=6):
    """Detecta los giros oceanicos y devuelve [{'puntos': [[x,y]...], 'anom':
    anomalia SST media, 'fuerza': rapidez relativa 0..1}] con los circuitos
    cerrados de corriente mas marcados (analogos a los giros terrestres)."""
    if psi is None or not mar.any():
        return []
    ny, nx = mar.shape
    marf = _suaviza(mar.astype(np.float64), 1)
    vel = np.hypot(cu, cv)
    vmed = float(np.median(vel[mar])) + 1e-9
    vmax = float(vel[mar].max()) + 1e-9
    ps = _suaviza(psi, 2) * mar
    gpx, gpy = grad_periodic(ps)
    aps = np.abs(ps)
    # extremos locales de |psi| en ventana 5x5 con nivel alto -> centros de giro
    vecmax = aps.copy()
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            if dy or dx:
                vecmax = np.maximum(vecmax, np.roll(rolly(aps, dy), dx, 1))
    umbral = float(np.percentile(aps[mar], 82))
    cand = np.argwhere((aps >= vecmax) & mar & (aps >= umbral) & (aps > 0))
    cand = sorted(cand.tolist(), key=lambda p: -aps[p[0], p[1]])
    sep = max(6, min(ny, nx) // 10)
    circuitos = []; centros = []
    for cy, cx in cand:
        if len(circuitos) >= max_giros:
            break
        if any(_dist_esf(cy, cx, y0, x0, ny, nx) < sep for y0, x0 in centros):
            continue
        tr = _traza_circuito(ps, gpx, gpy, cu, cv, marf, cy, cx, vmed)
        centros.append((cy, cx))              # aunque falle: no reintentar al lado
        if tr is None:
            continue
        puntos, rap = tr
        anom = float(np.mean([_bilin_esf(sst_anom, p[1], p[0])
                              for p in puntos[::4]]))
        circuitos.append({"puntos": puntos, "anom": anom,
                          "fuerza": min(1.0, rap / vmax)})
    return circuitos


def _dibuja_circuitos(d, circuitos, ny, nx, escala=1.0):
    """Dibuja los circuitos (giros) como lazos gruesos cerrados con puntas de
    flecha en el sentido de la corriente, tintados calida/fria por su anomalia.
    Los lazos que envuelven el borde Este-Oeste se trocean en el salto para no rayar el
    lienzo. `escala` posiciona sobre el lienzo final (como _flechas_corriente)."""
    calida = np.array([230, 80, 60]); fria = np.array([90, 150, 235])
    s = float(escala)
    w = max(3, int(round(2.6 * s)))
    for c in circuitos:
        pts = c["puntos"]
        if len(pts) < 8:
            continue
        t = float(np.clip(c["anom"] / 0.25, -1, 1))
        col = tuple(int(v) for v in (fria + (calida - fria) * (t * 0.5 + 0.5)))
        # trocear el lazo cerrado donde salta por el borde Este-Oeste
        cerr = pts + [pts[0]]
        tramos = [[cerr[0]]]
        for p0, p1 in zip(cerr, cerr[1:]):
            if abs(p1[0] - p0[0]) > nx / 2 or abs(p1[1] - p0[1]) > ny / 2:
                tramos.append([])
            tramos[-1].append(p1)
        for tramo in tramos:
            if len(tramo) < 2:
                continue
            xy = [(p[0] * s, p[1] * s) for p in tramo]
            d.line(xy, fill=(255, 255, 255, 140), width=w + 3, joint="curve")
            d.line(xy, fill=col + (235,), width=w, joint="curve")
        # tres puntas de flecha equiespaciadas marcan el sentido del giro
        m = len(pts)
        for k in range(3):
            i = (k * m) // 3; j = (i + 2) % m
            if abs(pts[j][0] - pts[i][0]) > nx / 2 or abs(pts[j][1] - pts[i][1]) > ny / 2:
                continue                       # el tramo cruza el borde E-O: saltar
            ang = np.arctan2(pts[j][1] - pts[i][1], pts[j][0] - pts[i][0])
            X, Y = pts[j][0] * s, pts[j][1] * s
            cab = 5.0 * s
            pa = (X - cab * np.cos(ang - 0.45), Y - cab * np.sin(ang - 0.45))
            pb = (X - cab * np.cos(ang + 0.45), Y - cab * np.sin(ang + 0.45))
            d.line([pa, (X, Y), pb], fill=col + (255,), width=w)


# ============================ hidrologia fina (HD) =========================
# La fisica (vientos/SST/precip/hielo/tair) se queda en la malla capada de
# simular_clima: es fenomeno de gran escala. La HIDROLOGIA, en cambio, se
# recalcula aqui sobre la elevacion DETALLADA (malla `res_hidro` <= 4096) para
# que los rios sigan el terreno fino. Topologia ESFERICA en todo: X (longitud)
# periodica, Y (latitud) sin envolver (los polos son borde). Sin rng global:
# un generador local de semilla fija (12345, como simular_clima) rompe los
# empates del drenaje sin tocar la continuacion bit-exacta de los mundos.

_OFFS8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
          (0, 1), (1, -1), (1, 0), (1, 1)]


def _min_vecinos8(W):
    """Minimo sobre los 8 vecinos (EXCLUIDO el centro): periodico en X, con
    +inf mas alla de los polos (esos vecinos no existen). Se rellena UN borde
    y se recorren VISTAS (sin copiar el array 8 veces con np.roll, que a
    4096^2 domina el costo)."""
    ny, nx = W.shape
    Wp = np.pad(W, ((1, 1), (0, 0)), mode="constant",
                constant_values=np.float32(np.inf))
    Wp = np.pad(Wp, ((0, 0), (1, 1)), mode="wrap")
    m = None
    for dy, dx in _OFFS8:
        nb = Wp[1 + dy:1 + dy + ny, 1 + dx:1 + dx + nx]
        m = nb.copy() if m is None else np.minimum(m, nb)
    return m


def _rellenar_depresiones(elev, tierra, niter):
    """Relleno de depresiones ACOTADO (Planchon-Darboux ascendente; X periodico,
    los polos no envuelven).
    Cada pasada sube los pozos de tierra a `min(vecino)+eps` (drenaje definido
    hacia el vecino mas bajo). El mar es el nivel de base fijo: no se sube. Tras
    `niter` pasadas, las depresiones grandes que no se llenaron quedan como
    pozos residuales -> lagos endorreicos. Numpy puro, sin scipy."""
    W = np.array(elev, np.float32)
    eps = np.float32(1e-6)
    for _ in range(niter):
        mv = _min_vecinos8(W)
        pit = tierra & (W < mv)          # sin vecino mas bajo o igual
        if not pit.any():
            break
        W = np.where(pit, mv + eps, W)
    return W


def _receptor_d8(W, mar):
    """Indice plano (fila*nx+col) del vecino MAS BAJO a 8 direcciones
    (periodico en X; mas alla de los polos no hay vecino: +inf). Pozo (minimo
    local) o mar -> receptor = si mismo (nodo terminal). argmin incremental
    para no apilar los 8 vecinos."""
    ny, nx = W.shape
    Wp = np.pad(W, ((1, 1), (0, 0)), mode="constant",
                constant_values=np.float32(np.inf))
    Wp = np.pad(Wp, ((0, 0), (1, 1)), mode="wrap")
    best = np.full(W.shape, np.float32(np.inf), np.float32)
    kbest = np.zeros(W.shape, np.int8)
    for k, (dy, dx) in enumerate(_OFFS8):
        nb = Wp[1 + dy:1 + dy + ny, 1 + dx:1 + dx + nx]
        mej = nb < best
        best = np.where(mej, nb, best)
        kbest = np.where(mej, np.int8(k), kbest)
    yy, xx = np.meshgrid(np.arange(ny, dtype=np.int32),
                         np.arange(nx, dtype=np.int32), indexing="ij")
    dyv = np.array([o[0] for o in _OFFS8], np.int32)
    dxv = np.array([o[1] for o in _OFFS8], np.int32)
    ry = np.clip(yy + dyv[kbest], 0, ny - 1)   # Y no envuelve (nunca elegido:
    rx = (xx + dxv[kbest]) % nx                # el pad es +inf; clip por si acaso)
    recv = (ry * nx + rx).astype(np.int32)
    self_idx = (yy * nx + xx).astype(np.int32)
    pozo = (best >= W) | mar
    recv = np.where(pozo, self_idx, recv)
    del best, kbest, ry, rx, yy, xx
    return recv, self_idx


def _acumular_caudal(recv_flat, self_flat, peso, maxit=200000):
    """Acumulacion de caudal EXACTA sobre el bosque de drenaje (cada celda ->
    su receptor; los nodos terminales apuntan a si mismos). Empuje iterado con
    NODO MUERTO: los terminales vierten a un indice ficticio N para que su peso
    no se re-propague (el self-loop del metodo clasico lo contaba muchas veces)
    y el corte temprano dispare cuando TODO el peso ha llegado a un terminal.
    Con suficientes iteraciones (== longitud del rio mas largo) es exacto; el
    test sintetico lo verifica contra fuerza bruta."""
    N = recv_flat.size
    sink = recv_flat == self_flat
    recv2 = np.where(sink, N, recv_flat).astype(np.intp)   # terminales -> muerto
    acc = peso.astype(np.float64).copy()
    contrib = peso.astype(np.float64).copy()
    tol = 1e-9 * (float(peso.sum()) + 1e-12)
    it = 0
    while it < maxit:
        pushed = np.bincount(recv2, weights=contrib, minlength=N + 1)
        contrib = pushed[:N]
        acc += contrib
        it += 1
        if float(contrib.sum()) <= tol:
            break
    return acc, it


def _raices(recv_flat):
    """Raiz (nodo terminal) del arbol de cada celda por pointer jumping: O(log
    altura) saltos `root = root[root]`. Define las cuencas (celdas con la misma
    raiz)."""
    root = recv_flat.astype(np.intp).copy()
    for _ in range(int(np.ceil(np.log2(max(root.size, 2)))) + 1):
        nr = root[root]
        if np.array_equal(nr, root):
            break
        root = nr
    return root


def _meandro_visual(ny, nx, sinuosidad, tierra, rng):
    """Campo de desplazamiento suave (dx, dy) en CELDAS de la malla hidro para
    ondular las polilineas de los rios al dibujarlas/exportarlas. El drenaje D8
    con relleno de depresiones tiende a rectas aunque se perturbe la elevacion
    (el relleno aplana las cubetas del ruido y el flujo cruza el llano en linea
    recta al desague), asi que el serpenteo VISIBLE se anade al TRAZO: un mismo
    campo continuo desplaza cada vertice, con lo que los rios se ondulan
    coherentes entre si y ningun tramo se rompe. Se atenua hacia la costa
    (mascara de tierra difundida) para que las desembocaduras no bailen sobre
    el mar. Determinista (comparte el rng local de la hidrologia)."""
    amp = np.float32(1.8 * sinuosidad)
    campos = []
    for _ in range(2):
        g = rng.standard_normal((max(6, ny // 20), max(6, nx // 20))).astype(np.float32)
        o = _upsample_bicubico_a(g, ny, nx)
        campos.append(amp * o / (float(np.abs(o).max()) + 1e-12))
    borde = _suaviza(tierra.astype(np.float32), 3).astype(np.float32)
    return ((campos[0] * borde).astype(np.float32),
            (campos[1] * borde).astype(np.float32))


def hidrologia_fina(elev_h, precip_h, hielo_h, umbral_frac=1.4e-4,
                    niter_fill=None, sinuosidad=1.0):
    """Hidrologia de detalle sobre la elevacion FINA (malla `res_hidro`,
    esferica: X periodica, polos sin envolver): D8 con relleno de depresiones
    acotado, acumulacion de caudal
    exacta, rios por AREA DE DRENAJE ABSOLUTA (fraccion del peso total de la
    tierra, no percentil: el percentil sobre fBm fino motea el mapa), lagos,
    estuarios y cuencas.

    elev_h: elevacion detallada (nhy,nhx) en -1..1 (0 = costa).
    precip_h, hielo_h: campos gruesos ya upsampleados a la malla hidro (0..1).
    sinuosidad: amplitud del ruido de MEANDRO (0 = drenaje puro por pendiente,
    rios rectos; 1 = normal; >1 muy serpenteante). El ruido dobla los cauces
    sin cambiar de cuenca y ademas siembra depresiones suaves -> cuencas
    endorreicas y lagos donde el terreno y la lluvia lo permiten.
    Devuelve dict con caudal, receptor(2d int32), rios/lagos/estuarios(bool),
    root(2d) de cuenca, tierra, y metadatos."""
    elev_h = np.asarray(elev_h, np.float32)
    ny, nx = elev_h.shape
    tierra = elev_h > np.float32(0.0)
    mar = ~tierra
    # ruido local minusculo para desempatar el drenaje (rng LOCAL, jamas global)
    rng_local = np.random.default_rng(12345)
    elev_j = elev_h + rng_local.random(elev_h.shape, dtype=np.float32) * np.float32(1e-4)
    # el drenaje se calcula sobre una elevacion SUAVIZADA proporcionalmente a la
    # resolucion: el fBm de detalle es rugosidad sub-malla (no cauces reales) y a
    # alta resolucion fragmenta la red en miles de micro-pozos -> los rios troncales
    # no se forman. Suavizar normaliza la escala de los cauces entre resoluciones
    # (red comparable al mapa clasico) y ademas acelera el relleno (menos pozos).
    pas = int(round(max(1, nx / 512)))
    elev_dren = _suaviza(elev_j, pas)
    # ruido de MEANDRO: un campo suave de grano ANCHO (~12 granos por mapa)
    # sumado SOLO en tierra, con amplitud pequena frente a las pendientes
    # regionales pero muy por encima del desempate de 1e-4: los cauces lo
    # rodean en detours largos en vez de bajar en rectas D8. La longitud de
    # onda manda mucho mas que la amplitud, y el grano FINO es
    # contraproducente (medido en un plano inclinado sintetico: ~12 granos
    # triplica la sinuosidad L/D; ~21 granos o mezclar una octava fina la
    # devuelve a ~1.5, porque el gradiente de alta frecuencia domina la
    # direccion local y corta los detours). Ademas siembra depresiones suaves
    # que el relleno acotado no siempre vacia -> cuencas endorreicas y lagos.
    # Determinista (rng local de semilla fija).
    if sinuosidad > 0.0:
        ngr = 12
        g = rng_local.standard_normal(
            (max(6, ngr * ny // max(nx, 1)), ngr)).astype(np.float32)
        # _upsample_bicubico_a devuelve una vista de solo-lectura (np.asarray
        # sobre el buffer de PIL): normalizar SIN operar en sitio
        meandro = _upsample_bicubico_a(g, ny, nx)
        meandro = meandro / (float(np.abs(meandro).max()) + 1e-12)
        elev_dren = elev_dren + (np.float32(0.008 * sinuosidad)
                                 * meandro * tierra)
        del g, meandro
    # el mar conserva su cota baja real: la tierra debe drenar a la costa fina
    elev_dren = np.where(mar, elev_j, elev_dren).astype(np.float32)
    del elev_j
    if niter_fill is None:
        niter_fill = int(max(24, min(96, nx // 24)))
    W = _rellenar_depresiones(elev_dren, tierra, niter_fill)
    # agua embalsada: donde el relleno subio el terreno hay una depresion real
    # (el "nivel de agua" W queda por encima del suelo del drenaje). Es la
    # huella de los lagos EXTENDIDOS: tanto los que rebosan por un emisario
    # (relleno completo) como los endorreicos (pozos residuales sin salida).
    prof = (W - elev_dren) * tierra
    del elev_dren
    recv, self_idx = _receptor_d8(W, mar)
    del W
    recv_flat = recv.ravel()
    self_flat = self_idx.ravel()
    # peso = area de drenaje ponderada por la precipitacion; el hielo apenas
    # aporta. El suelo (0.12) pesa poco frente a la lluvia (0.88): la densidad
    # de la red fluvial responde de verdad a cuanto llueve en cada cuenca
    # (antes el suelo aportaba 0.3 y los desiertos criaban rios como si nada).
    hielo_t = np.clip(hielo_h, 0.0, 1.0) * tierra
    peso = ((np.float32(0.12) + np.float32(0.88) * np.clip(precip_h, 0.0, 1.0))
            * tierra * (np.float32(1.0) - np.float32(0.9) * hielo_t)).astype(np.float64).ravel()
    caudal_flat, iters = _acumular_caudal(recv_flat, self_flat, peso)
    caudal = caudal_flat.reshape(ny, nx).astype(np.float32)
    del caudal_flat
    total = float(peso.sum()) + 1e-12
    # umbral por REFERENCIA fija (0.5 = peso medio de un mundo normal), no por
    # fraccion del agua real: asi la densidad de rios crece en un mundo humedo
    # y baja en uno arido, en vez de salir siempre la misma
    umb = np.float32(umbral_frac * 0.5 * (float(tierra.sum()) + 1e-9))
    tierra_libre = tierra & (hielo_t < 0.5)
    rios = (caudal > umb) & tierra_libre
    root = _raices(recv_flat)
    # lagos EXTENDIDOS: la cubeta embalsada entera (prof = cuanto subio el
    # relleno el suelo), no solo la celda del pozo. Cuentan tanto los lagos
    # con emisario (la depresion se lleno y rebosa) como los ENDORREICOS
    # (pozos residuales sin salida al mar). El lago solo se moja si su cuenca
    # recoge agua de verdad (caudal en la raiz > 3x umbral de rio): en zonas
    # aridas la cubeta queda seca — cuenca endorreica sin lago.
    sink2d = (recv_flat == self_flat).reshape(ny, nx)
    caudal_raiz = caudal.reshape(-1)[root].reshape(ny, nx)
    lagos = (tierra_libre & (prof > np.float32(2e-4))
             & (caudal_raiz > umb * np.float32(3.0)))
    # el pozo terminal caudaloso siempre cuenta (lago minimo de 1 celda)
    lagos |= sink2d & tierra_libre & (caudal > umb * np.float32(3.0))
    del caudal_raiz, prof
    # estuarios: celda de rio junto al mar (desembocadura)
    vecino_mar = np.zeros((ny, nx), bool)
    for dy, dx in _OFFS8:
        vecino_mar |= np.roll(rolly(mar, dy), dx, 1)
    estuarios = rios & vecino_mar
    root = root.reshape(ny, nx)
    # desplazamiento de meandro para el TRAZO (render y JSON): ver helper
    meandro = (_meandro_visual(ny, nx, sinuosidad, tierra, rng_local)
               if sinuosidad > 0.0 else None)
    return {
        "caudal": caudal,
        "receptor": recv,
        "self_idx": self_idx,
        "rios": rios,
        "lagos": lagos,
        "estuarios": estuarios,
        "root": root,
        "tierra": tierra,
        "mar": mar,
        "vecino_mar": vecino_mar,
        "umbral": float(umb),
        "peso_total": total,
        "iters": int(iters),
        "res": (int(ny), int(nx)),
        # (dx, dy) en celdas para ondular las polilineas al trazar, o None
        "meandro": meandro,
    }


# ============================ Koppen simplificado ==========================
# Sin estacionalidad: el modelo solo da MEDIAS ANUALES (tair, precip). El mapeo
# clasico A/B/C/D/E usa el mes mas frio/calido/seco; aqui se aproxima con la
# temperatura media anual (bandas E<D<C<A) y la precipitacion media anual
# (aridez B, humedad f/monzon m/seco w). Las clases que exigen estacion (Cs
# mediterraneo, Dw/Ds) se colapsan en su variante seca. Paleta ~ Koppen-Geiger.
# tabla: id -> (cod, nombre, rgb)
KOPPEN = {
    0:  ("Af", "Ecuatorial lluvioso",   (0, 0, 254)),
    1:  ("Am", "Monzonico tropical",    (0, 120, 255)),
    2:  ("Aw", "Sabana tropical",       (70, 170, 250)),
    3:  ("BW", "Desierto (arido)",      (250, 0, 0)),
    4:  ("BS", "Estepa (semiarido)",    (245, 165, 60)),
    5:  ("Cf", "Templado humedo",       (0, 150, 0)),
    6:  ("Cw", "Templado seco",         (150, 220, 100)),
    7:  ("Df", "Continental humedo",    (0, 130, 130)),
    8:  ("Dw", "Continental seco",      (90, 120, 170)),
    9:  ("Dc", "Boreal (taiga)",        (150, 120, 190)),
    10: ("ET", "Tundra",                (178, 180, 180)),
    11: ("EF", "Hielo perpetuo",        (105, 105, 110)),
}
_KOPPEN_RGB = np.zeros((len(KOPPEN), 3), np.uint8)
for _k, (_c, _n, _rgb) in KOPPEN.items():
    _KOPPEN_RGB[_k] = _rgb


def clasificar_koppen(tair, precip, hielo_tierra, tierra):
    """Koppen simplificado (~12 clases) desde medias anuales. Devuelve int16 con
    el id de clase en tierra y 255 en el mar. Ver la nota de KOPPEN sobre el
    colapso de las clases estacionales."""
    t = tair
    p = precip
    k = np.full(tair.shape, 255, np.int16)
    # bandas de temperatura media anual (sin estaciones)
    muy_frio = t < np.float32(-0.50)
    frio = (t >= np.float32(-0.50)) & (t < np.float32(-0.12))
    templado = (t >= np.float32(-0.12)) & (t < np.float32(0.42))
    calido = t >= np.float32(0.42)
    # umbral de aridez B: crece con la temperatura (mas calor evapora mas, hace
    # falta mas lluvia para no ser desierto). El desierto pleno (BW, rojo) se
    # reserva a la tierra CALIDA/templada muy seca; el frio arido cae en estepa
    # (BS) o boreal, no en el rojo desertico, para no monocromar los mundos frios.
    aridoc = np.float32(0.06) + np.float32(0.14) * np.clip((t + 0.2), 0.0, 1.0)
    semic = aridoc + np.float32(0.12)
    # E (polar)
    k = np.where(tierra & muy_frio, 10, k)          # ET tundra
    # frio continental (D): estepa fria si muy seco, boreal seco, taiga humedo
    k = np.where(tierra & frio & (p < np.float32(0.10)), 4, k)   # BS estepa fria
    k = np.where(tierra & frio & (p >= np.float32(0.10)) & (p < np.float32(0.30)), 8, k)  # Dw
    k = np.where(tierra & frio & (p >= np.float32(0.30)), 7, k)  # Df taiga
    # templado (C) + arido
    k = np.where(tierra & templado & (p < aridoc), 3, k)          # BW desierto
    k = np.where(tierra & templado & (p >= aridoc) & (p < semic), 4, k)  # BS estepa
    k = np.where(tierra & templado & (p >= semic) & (p < np.float32(0.45)), 6, k)  # Cw
    k = np.where(tierra & templado & (p >= np.float32(0.45)), 5, k)      # Cf
    # calido (A/B)
    k = np.where(tierra & calido & (p < aridoc), 3, k)           # BW desierto
    k = np.where(tierra & calido & (p >= aridoc) & (p < semic), 4, k)   # BS estepa
    k = np.where(tierra & calido & (p >= semic) & (p < np.float32(0.42)), 2, k)  # Aw
    k = np.where(tierra & calido & (p >= np.float32(0.42)) & (p < np.float32(0.60)), 1, k)  # Am
    k = np.where(tierra & calido & (p >= np.float32(0.60)), 0, k)        # Af
    # hielo perpetuo (casquete/glaciar) manda sobre todo
    k = np.where(tierra & (hielo_tierra >= 0.5), 11, k)
    return k


# ============================ render HD ====================================

def _malla_bloques(a, ny2, nx2):
    """Reduce (ny,nx)->(ny2,nx2) por media de bloques si divide exacto, si no por
    submuestreo. Para llevar la elevacion fina a mallas menores (datos/koppen)."""
    ny, nx = a.shape
    if (ny2, nx2) == (ny, nx):
        return np.asarray(a, np.float32)
    if ny % ny2 == 0 and nx % nx2 == 0 and ny2 <= ny and nx2 <= nx:
        ky, kx = ny // ny2, nx // nx2
        return np.asarray(a, np.float32).reshape(ny2, ky, nx2, kx).mean(axis=(1, 3)).astype(np.float32)
    yi = (np.arange(ny2) * ny / ny2).astype(np.intp)
    xi = (np.arange(nx2) * nx / nx2).astype(np.intp)
    return np.asarray(a, np.float32)[np.ix_(yi, xi)]


def _campos_en_malla(campos, elev2, elev_c, ny2, nx2):
    """Campos derivados a la malla (ny2,nx2): tierra/altitud de la geografia
    FINA (elev2 reducida), tair corregida por altitud fina, precip/hielo gruesos
    upsampleados, y bioma + Koppen reclasificados. Base comun de datos/koppen."""
    elev2d = _malla_bloques(elev2, ny2, nx2)
    tierra = elev2d > np.float32(0.0)
    tair_up = _upsample_bicubico_a(campos["tair"], ny2, nx2)
    alt_c_up = _upsample_bicubico_a(np.clip(elev_c, 0.0, None), ny2, nx2)
    alt_f = np.clip(elev2d, 0.0, None)
    tair = tair_up - np.float32(1.30) * (alt_f - alt_c_up)
    precip = np.clip(_upsample_bicubico_a(campos["precip"], ny2, nx2), 0.0, 1.0)
    hielo = np.clip(_upsample_bicubico_a(campos["hielo"], ny2, nx2), 0.0, 1.0)
    hielo_t = np.clip((np.float32(-0.30) - tair) / np.float32(0.30), 0.0, 1.0) * tierra
    # bono ribereno solo para biomas (koppen conserva la precip real)
    ribera_c = campos.get("ribera")
    if ribera_c is None:
        ribera_c = np.zeros_like(campos["precip"])
    ribera = np.clip(_upsample_bicubico_a(ribera_c, ny2, nx2), 0.0, 1.0)
    precip_bioma = np.clip(precip + BONO_RIBERA * ribera, 0.0, 1.0)
    bioma = _clasificar_biomas(tair, precip_bioma, hielo_t, tierra)
    koppen = clasificar_koppen(tair, precip, hielo_t, tierra)
    return {"tierra": tierra, "alt": np.clip(elev2d, 0.0, 1.0), "tair": tair,
            "precip": precip, "hielo": hielo, "bioma": bioma, "koppen": koppen}


def _dibujar_hidro_fina(d, hidro, nx, ny):
    """Traza rios/lagos/estuarios de la hidrologia FINA como polilineas continuas
    celda->receptor sobre el lienzo (nx,ny), escaladas desde la malla hidro. El
    ancho y el alpha crecen con el caudal. Se omiten los tramos que envuelven el
    borde Este-Oeste (saltos de mas de una celda) para no rayar el mapa. Si `hidro` trae el
    campo de meandro, cada vertice se desplaza con el (mismo campo continuo para
    todos los tramos: los cauces se ondulan coherentes sin romperse)."""
    recv = hidro["receptor"]
    caudal = hidro["caudal"]
    rios = hidro["rios"]
    lagos = hidro["lagos"]
    estuarios = hidro["estuarios"]
    meandro = hidro.get("meandro")
    mdx, mdy = meandro if meandro is not None else (None, None)
    nhy, nhx = recv.shape
    kx = nx / nhx
    ky = ny / nhy
    rlx = max(1.0, kx * 0.6)
    rly = max(1.0, ky * 0.6)
    # lagos primero (por debajo de los rios)
    ys, xs = np.nonzero(lagos)
    for i, j in zip(ys, xs):
        cx = (j + 0.5) * kx
        cy = (i + 0.5) * ky
        d.ellipse([cx - rlx, cy - rly, cx + rlx, cy + rly], fill=(60, 130, 200, 255))
    if rios.any():
        ys, xs = np.nonzero(rios)
        cval = caudal[ys, xs]
        cmax = float(cval.max()) + 1e-9
        umb = hidro["umbral"] + 1e-9
        orden = np.argsort(cval)          # los caudalosos al final (encima)
        ys = ys[orden]; xs = xs[orden]; cval = cval[orden]
        base_w = max(1.0, min(kx, ky))
        for i, j, c in zip(ys, xs, cval):
            r = int(recv[i, j])
            ri, rj = divmod(r, nhx)
            if r == i * nhx + j:
                continue
            dj = rj - j
            di = ri - i
            if abs(dj) > 1 or abs(di) > 1:   # envuelve el borde E-O: no cruzar
                continue
            frac = (np.log1p(c / umb) / np.log1p(cmax / umb)) if cmax > umb else 0.0
            w = max(1, int(round(base_w * (0.5 + 1.9 * frac))))
            a = int(110 + 140 * frac)
            ox0 = oy0 = ox1 = oy1 = 0.0
            if mdx is not None:              # meandro: desplazar los vertices
                ox0 = float(mdx[i, j]); oy0 = float(mdy[i, j])
                ox1 = float(mdx[ri, rj]); oy1 = float(mdy[ri, rj])
            x0 = (j + 0.5 + ox0) * kx; y0 = (i + 0.5 + oy0) * ky
            x1 = (rj + 0.5 + ox1) * kx; y1 = (ri + 0.5 + oy1) * ky
            d.line([(x0, y0), (x1, y1)], fill=(38, 96, 180, a), width=w)
    # estuarios: puntos turquesa
    ys, xs = np.nonzero(estuarios)
    aw = max(1.0, min(kx, ky))
    for i, j in zip(ys, xs):
        cx = (j + 0.5) * kx; cy = (i + 0.5) * ky
        d.ellipse([cx - aw, cy - aw, cx + aw, cy + aw], fill=(70, 200, 220, 255))


def render_clima_hd(campos, elev_detalle, elev_c, hidro, temperatura=0.0):
    """Mapa climatico HD a plena resolucion (== render_clima_detalle en el color:
    biomas reclasificados pixel a pixel con la geografia fina, tair corregida por
    altitud fina, relieve sombreado, hielo, mar por SST, plataforma) PERO con la
    hidrografia trazada desde la HIDROLOGIA FINA (rios continuos que siguen el
    terreno) y SIN flechas de corrientes (van a las capas HTML)."""
    elev_detalle = np.asarray(elev_detalle, np.float32)
    elev_c = np.asarray(elev_c, np.float64)
    ny, nx = elev_detalle.shape

    tair_up = _upsample_bicubico_a(campos["tair"], ny, nx)
    precip_up = np.clip(_upsample_bicubico_a(campos["precip"], ny, nx), 0.0, 1.0)
    hielo_up = np.clip(_upsample_bicubico_a(campos["hielo"], ny, nx), 0.0, 1.0)
    alt_up = _upsample_bicubico_a(np.clip(elev_c, 0.0, None), ny, nx)

    tierra_det = elev_detalle > np.float32(0.0)
    mar_det = ~tierra_det
    alt_det = np.clip(elev_detalle, 0.0, None)
    tair_det = tair_up - np.float32(1.30) * (alt_det - alt_up)
    del alt_up, alt_det, tair_up
    hielo_tierra_det = (np.clip((np.float32(-0.30) - tair_det) / np.float32(0.30),
                                0.0, 1.0) * tierra_det).astype(np.float32)
    # bono de humedad riberena: el grueso upsampleado REFORZADO con los rios/lagos
    # FINOS de `hidro` (dilatados unos px) para que el bosque abrace los cauces
    # nitidos del render HD. Solo afecta a la clasificacion de biomas.
    ribera_c = campos.get("ribera")
    if ribera_c is None:
        ribera_c = np.zeros_like(campos["precip"])
    ribera_up = np.clip(_upsample_bicubico_a(ribera_c, ny, nx), 0.0, 1.0).astype(np.float32)
    hr = (hidro["rios"] | hidro["lagos"])
    hrd = hr.copy()
    for dy, dx in _OFFS8:
        hrd |= np.roll(rolly(hr, dy), dx, 1)
    nhy, nhx = hrd.shape
    yi = (np.arange(ny) * nhy / ny).astype(np.intp)
    xi = (np.arange(nx) * nhx / nx).astype(np.intp)
    ribera_up = np.maximum(ribera_up, hrd[np.ix_(yi, xi)].astype(np.float32))
    del hr, hrd, yi, xi
    precip_bioma = np.clip(precip_up + np.float32(BONO_RIBERA) * ribera_up, 0.0, 1.0)
    del ribera_up
    bioma_det = _clasificar_biomas(tair_det, precip_bioma, hielo_tierra_det, tierra_det)
    del tair_det, precip_up, precip_bioma

    img = np.empty((ny, nx, 3), np.float32)
    sst_up = _upsample_bicubico_a(campos["sst"], ny, nx)
    for ch in range(3):
        img[..., ch] = np.interp(sst_up, _PALETA_SST[:, 0], _PALETA_SST[:, ch + 1])
    del sst_up
    banq = (hielo_up * mar_det).astype(np.float32)
    hielo_mar = np.array([214, 228, 240], np.float32)
    for ch in range(3):
        img[..., ch] += banq * (hielo_mar[ch] - img[..., ch])
    del banq, hielo_up
    plat = (np.clip((elev_detalle + np.float32(0.06)) / np.float32(0.06), 0.0, 1.0)
            * mar_det).astype(np.float32) * np.float32(0.16)
    for ch in range(3):
        img[..., ch] += plat * np.minimum(np.float32(44.0), np.float32(255.0) - img[..., ch])
    del plat
    gx, gy = grad_periodic(elev_detalle)
    shade = np.clip(1.0 + 1.7 * (gx - gy), 0.82, 1.18).astype(np.float32)
    del gx, gy
    glaciar = np.array([238, 244, 250], np.float32)
    bioma_seguro = np.clip(bioma_det, 0, None)
    for ch in range(3):
        col = _BIOMA_RGB[bioma_seguro, ch].astype(np.float32) * shade
        col += hielo_tierra_det * (glaciar[ch] - col)
        img[..., ch] = np.where(tierra_det, col, img[..., ch])
        del col
    del shade, bioma_seguro, bioma_det, hielo_tierra_det, tierra_det, mar_det

    img = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(img)
    del img
    d = ImageDraw.Draw(im, "RGBA")
    _dibujar_hidro_fina(d, hidro, nx, ny)
    return im


# ============================ exportacion de capas =========================

def _marching_squares(campo, niveles, escx, escy):
    """Isolineas por marching squares sobre `campo` (malla pequena, NO envolvente:
    la ultima fila/columna no se procesa para no rayar el borde envolvente).
    Devuelve por nivel una lista de segmentos [[x0,y0],[x1,y1]] en pixeles del
    render (escalados por escx,escy). Segmentos cortos, ya recortados al borde."""
    ny, nx = campo.shape
    out = []
    f = campo
    for lv in niveles:
        segs = []
        a = f[:-1, :-1]; b = f[:-1, 1:]; c = f[1:, 1:]; dd = f[1:, :-1]
        # interpolacion lineal de los cruces en cada arista
        def cruce(p, q):
            den = (q - p)
            t = np.where(np.abs(den) > 1e-9, (lv - p) / den, 0.5)
            return np.clip(t, 0.0, 1.0)
        ca = (a > lv).astype(np.int8)
        cb = (b > lv).astype(np.int8)
        cc = (c > lv).astype(np.int8)
        cd = (dd > lv).astype(np.int8)
        code = ca + cb * 2 + cc * 4 + cd * 8
        yy, xx = np.nonzero((code > 0) & (code < 15))
        for i, j in zip(yy.tolist(), xx.tolist()):
            v = int(code[i, j])
            p00 = float(f[i, j]); p01 = float(f[i, j + 1])
            p11 = float(f[i + 1, j + 1]); p10 = float(f[i + 1, j])
            # puntos de cruce en las 4 aristas (coords de celda -> render)
            def pt_top():
                t = (lv - p00) / (p01 - p00) if p01 != p00 else 0.5
                return [(j + t) * escx, i * escy]
            def pt_bot():
                t = (lv - p10) / (p11 - p10) if p11 != p10 else 0.5
                return [(j + t) * escx, (i + 1) * escy]
            def pt_left():
                t = (lv - p00) / (p10 - p00) if p10 != p00 else 0.5
                return [j * escx, (i + t) * escy]
            def pt_right():
                t = (lv - p01) / (p11 - p01) if p11 != p01 else 0.5
                return [(j + 1) * escx, (i + t) * escy]
            E = {"T": pt_top, "B": pt_bot, "L": pt_left, "R": pt_right}
            # tabla marching squares (aristas conectadas por caso)
            tabla = {
                1: [("L", "T")], 2: [("T", "R")], 3: [("L", "R")],
                4: [("R", "B")], 5: [("L", "T"), ("R", "B")], 6: [("T", "B")],
                7: [("L", "B")], 8: [("L", "B")], 9: [("T", "B")],
                10: [("L", "T"), ("R", "B")], 11: [("R", "B")], 12: [("L", "R")],
                13: [("T", "R")], 14: [("L", "T")],
            }
            for e0, e1 in tabla.get(v, []):
                segs.append([E[e0](), E[e1]()])
        out.append({"nivel": round(float(lv), 3), "segmentos": segs})
    return out


def _cuencas_top(hidro, n=12):
    """Ids 0..n-1 de las n cuencas de mayor area (solo tierra), -1 el resto. La
    cuenca de una celda = su raiz del grafo D8. Trabaja sobre la malla hidro."""
    root = hidro["root"].ravel()
    tierra = hidro["tierra"].ravel()
    rt = root[tierra]
    if rt.size == 0:
        return np.full(hidro["root"].shape, -1, np.int16), []
    uniq, cnt = np.unique(rt, return_counts=True)
    orden = np.argsort(cnt)[::-1][:n]
    top_roots = uniq[orden]
    idmap = {int(r): k for k, r in enumerate(top_roots.tolist())}
    bid = np.full(root.shape, -1, np.int16)
    for r, k in idmap.items():
        bid[root == r] = k
    bid[~tierra] = -1
    return bid.reshape(hidro["root"].shape), top_roots.tolist()


# paleta de cuencas (12 tonos distinguibles)
_CUENCA_RGB = np.array([
    (228, 26, 28), (55, 126, 184), (77, 175, 74), (152, 78, 163),
    (255, 127, 0), (255, 210, 40), (166, 86, 40), (247, 129, 191),
    (102, 194, 165), (141, 160, 203), (231, 138, 195), (166, 216, 84),
], np.uint8)


def _rios_json(hidro, nx, ny, n=12, cada=4):
    """Los n rios mas caudalosos: se parte de las desembocaduras (celda de rio
    cuyo receptor es mar), se ordenan por caudal, se deduplican por cuenca y se
    trazan aguas ARRIBA siguiendo el afluente de mayor caudal. Se decima 1 punto
    cada `cada` celdas, se escala a pixeles de render y se parte en el borde
    Este-Oeste. Devuelve la lista lista para el JSON (aguas arriba -> abajo)."""
    recv = hidro["receptor"]
    caudal = hidro["caudal"]
    rios = hidro["rios"]
    mar = hidro["mar"]
    root = hidro["root"]
    meandro = hidro.get("meandro")
    mdx, mdy = meandro if meandro is not None else (None, None)
    nhy, nhx = recv.shape
    kx = nx / nhx
    ky = ny / nhy
    marf = mar.ravel()
    # desembocaduras: rio cuyo receptor cae en mar
    ys, xs = np.nonzero(rios)
    if ys.size == 0:
        return []
    rf = recv[ys, xs]
    es_boca = marf[rf]
    by = ys[es_boca]; bx = xs[es_boca]
    if by.size == 0:
        # sin bocas (mundo endorreico): usar los rios de mayor caudal
        cval = caudal[ys, xs]
        top = np.argsort(cval)[::-1][:n * 4]
        by = ys[top]; bx = xs[top]
    cbo = caudal[by, bx]
    orden = np.argsort(cbo)[::-1]
    by = by[orden]; bx = bx[orden]
    cmax = float(caudal[rios].max()) + 1e-9
    umb = hidro["umbral"]
    salida = []
    usadas = set()
    rid = 0
    for i0, j0 in zip(by.tolist(), bx.tolist()):
        cuenca = int(root[i0, j0])
        if cuenca in usadas:
            continue
        usadas.add(cuenca)
        # trazar aguas arriba desde la boca por el afluente mayor
        camino = [(i0, j0)]
        ci, cj = i0, j0
        guard = 0
        limite = 4 * (nhx + nhy)
        while guard < limite:
            guard += 1
            # donantes: vecinos cuyo receptor es la celda actual y son rio
            mejor = None; mejor_c = -1.0
            here = ci * nhx + cj
            for dy, dx in _OFFS8:
                ni = ci + dy
                if ni < 0 or ni >= nhy:          # no cruzar el polo
                    continue
                nj = (cj + dx) % nhx
                if not rios[ni, nj]:
                    continue
                if int(recv[ni, nj]) != here:
                    continue
                cc = float(caudal[ni, nj])
                if cc > mejor_c:
                    mejor_c = cc; mejor = (ni, nj)
            if mejor is None:
                break
            camino.append(mejor)
            ci, cj = mejor
        # aguas arriba -> abajo
        camino = camino[::-1]
        # decimar
        dec = camino[::cada]
        if dec[-1] != camino[-1]:
            dec.append(camino[-1])
        # a pixeles + partir en el borde E-O
        polis = []
        actual = []
        prev = None
        for (pi, pj) in dec:
            if prev is not None:
                if abs(pj - prev[1]) > nhx * 0.5 or abs(pi - prev[0]) > nhy * 0.5:
                    if len(actual) >= 2:
                        polis.append(actual)
                    actual = []
            # meandro: mismo desplazamiento que el trazo del render HD, para
            # que la capa web y el PNG dibujen exactamente el mismo cauce
            ox = float(mdx[pi, pj]) if mdx is not None else 0.0
            oy = float(mdy[pi, pj]) if mdy is not None else 0.0
            actual.append([round((pj + 0.5 + ox) * kx, 1),
                           round((pi + 0.5 + oy) * ky, 1)])
            prev = (pi, pj)
        if len(actual) >= 2:
            polis.append(actual)
        cau_norm = round(float(caudal[i0, j0]) / cmax, 3)
        for poli in polis:
            salida.append({"id": rid + 1, "nombre": f"Rio {rid + 1}",
                           "caudal": cau_norm, "puntos": poli})
        rid += 1
        if rid >= n:
            break
    return salida


def _quant(v, lo, hi):
    return np.clip(np.round(255.0 * (np.asarray(v, np.float64) - lo) / (hi - lo + 1e-12)),
                   0, 255).astype(np.uint8)


def _bloque_max(a, ny2, nx2):
    """Reduce (ny,nx)->(ny2,nx2) por MAXIMO de bloque (preserva rasgos finos como
    los cauces, que la media borraria). Submuestreo si no divide exacto."""
    ny, nx = a.shape
    if (ny2, nx2) == (ny, nx):
        return np.asarray(a)
    if ny % ny2 == 0 and nx % nx2 == 0 and ny2 <= ny and nx2 <= nx:
        ky, kx = ny // ny2, nx // nx2
        return np.asarray(a).reshape(ny2, ky, nx2, kx).max(axis=(1, 3))
    yi = (np.arange(ny2) * ny / ny2).astype(np.intp)
    xi = (np.arange(nx2) * nx / nx2).astype(np.intp)
    return np.asarray(a)[np.ix_(yi, xi)]


def _capa_civilizacion(campos, elev2, elev_c, hidro, nx, ny, res_koppen, salida,
                       civ_dials=None):
    """Construye el `campo` de civ a una malla reducida a partir de los campos ya
    calculados (Koppen + hidrologia fina), invoca civ.generar y escala el
    resultado a pixeles de render. Ademas escribe {salida}_paises.png (overlay de
    paises con fronteras) y {salida}_civ.png (mapa politico renderizado sobre el
    clima HD, con asentamientos rotulados). Devuelve (dict JSON-listo, nombre_png).
    civ_dials: {"semilla": int, "asentamientos": int, "paises": int,
    "tam": int 0 auto | 1 grandes | 2 chicos} (0 = auto)."""
    import zlib
    civ_dials = civ_dials or {}
    # malla de civilizacion: acotada para que el A*/Dijkstra en Python sea barato
    ncw = int(min(nx, 200))
    m = _campos_en_malla(campos, elev2, elev_c, ncw, ncw)
    elev_w = _malla_bloques(elev2, ncw, ncw)
    # rios/caudal/cuenca desde la hidrologia fina (max/any/nearest -> no se borran)
    caudal_w = _bloque_max(hidro["caudal"], ncw, ncw).astype(np.float32)
    cmax = float(caudal_w.max()) + 1e-9
    caudal_w = np.clip(caudal_w / cmax, 0.0, 1.0)
    rio_w = _bloque_max((hidro["rios"] | hidro["lagos"]).astype(np.uint8), ncw, ncw) > 0
    hy, hx = hidro["root"].shape
    yi = (np.arange(ncw) * hy / ncw).astype(np.intp)
    xi = (np.arange(ncw) * hx / ncw).astype(np.intp)
    cuenca_w = hidro["root"][np.ix_(yi, xi)]

    campo = {
        "tierra": m["tierra"], "mar": ~m["tierra"],
        "elev": elev_w.astype(np.float32), "alt": m["alt"].astype(np.float32),
        "koppen": m["koppen"].astype(np.int16), "caudal": caudal_w,
        "rio": rio_w & m["tierra"], "cuenca": cuenca_w,
    }
    # semilla reproducible derivada de la geografia (no toca el rng de la sim);
    # la semilla de civilizacion del usuario se MEZCLA: otra semilla civ = otros
    # asentamientos/nombres/paises sobre la MISMA geografia
    seed = zlib.crc32(np.ascontiguousarray(elev_c, np.float32).tobytes()) & 0x7FFFFFFF
    seed ^= (int(civ_dials.get("semilla", 0)) * 0x9E3779B1) & 0x7FFFFFFF
    civd = civ.generar(campo, seed,
                       n_asent=int(civ_dials.get("asentamientos", 0)),
                       n_paises=int(civ_dials.get("paises", 0)),
                       tam_paises=int(civ_dials.get("tam", 0)))

    kx = nx / ncw; ky = ny / ncw
    tierra_f = elev2 > 0.0                     # costa FINA (la malla civ es gruesa)

    def esc_polis(polis):
        return [[round(p[0] * kx, 1), round(p[1] * ky, 1)] for p in polis]

    def a_tierra(px, py):
        """Ajusta un punto (px,py) render al pixel de TIERRA fina mas cercano si
        cayo en mar por el desajuste malla-gruesa vs costa-fina (busca en espiral
        acotada); asi los asentamientos costeros no quedan flotando en el agua."""
        xi = int(min(nx - 1, max(0, round(px)))); yi = int(min(ny - 1, max(0, round(py))))
        if tierra_f[yi, xi]:
            return px, py
        for r in range(1, int(max(kx, ky)) + 3):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    ny2 = yi + dy
                    if ny2 < 0 or ny2 >= ny:     # no cruzar el polo
                        continue
                    nx2 = (xi + dx) % nx
                    if tierra_f[ny2, nx2]:
                        return float(nx2), float(ny2)
        return px, py

    asent_j = []
    for a in civd["asentamientos"]:
        px = (a["j"] + 0.5) * kx; py = (a["i"] + 0.5) * ky
        px, py = a_tierra(px, py)
        asent_j.append({
            "x": round(px, 1), "y": round(py, 1),
            "nombre": a["nombre"], "rango": a["rango"], "poblacion": a["poblacion"],
            "costa": a["costa"], "rio": a["rio"], "pais": a["pais"]})
    caminos_j = [{"puntos": esc_polis(c["puntos"]), "clase": c["clase"]}
                 for c in civd["caminos"]]
    rutas_j = [{"puntos": esc_polis(r["puntos"]), "mar": r["mar"],
                "a": r["a"], "b": r["b"]} for r in civd["rutas"]]

    # ---- overlay de paises (RGBA) a res_koppen, con fronteras remarcadas ----
    idmap = civd["paises"]["idmap"]           # (ncw,ncw) int, -1 mar/inalcanzable
    lista = civd["paises"]["lista"]
    nky, nkx = res_koppen
    yk = (np.arange(nky) * ncw / nky).astype(np.intp)
    xk = (np.arange(nkx) * ncw / nkx).astype(np.intp)
    pmap = idmap[np.ix_(yk, xk)]
    pal = np.zeros((max(1, len(lista)), 3), np.uint8)
    for p in lista:
        pal[p["id"]] = p["rgb"]
    pa = np.zeros((nky, nkx, 4), np.uint8)
    val = pmap >= 0
    ids = np.clip(pmap, 0, max(0, len(lista) - 1))
    for ch in range(3):
        pa[..., ch] = np.where(val, pal[ids, ch], 0)
    # interior casi opaco (235): con el opacity .6 del CSS queda ~55 % efectivo,
    # igual que el overlay Koppen — antes iba a 120 y la capa apenas se veia
    pa[..., 3] = np.where(val, 235, 0).astype(np.uint8)
    # frontera: celda cuyo pais difiere de algun vecino (linea opaca oscura)
    borde = np.zeros((nky, nkx), bool)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        borde |= (np.roll(rolly(pmap, dy), dx, 1) != pmap)
    borde &= val
    for ch in range(3):
        pa[..., ch] = np.where(borde, (pal[ids, ch] * 0.35).astype(np.uint8), pa[..., ch])
    pa[..., 3] = np.where(borde, 255, pa[..., 3]).astype(np.uint8)
    png_name = Path(salida).name + "_paises.png"
    img_paises = Image.fromarray(pa, "RGBA")
    img_paises.save(f"{salida}_paises.png")

    paises_j = {"png": png_name,
                "tierra": int(civd["paises"].get("tierra_total", 0)),
                "lista": [{"id": p["id"], "nombre": p["nombre"], "rgb": p["rgb"],
                           "area": p["area"],
                           "poblacion": int(p.get("poblacion", 0))}
                          for p in lista]}

    # ---- raster de SUBREGIONES (provincias + cuencas marinas) a res_koppen ----
    # id combinado 1-based en el PNG: R = byte bajo, G = byte alto, 0 = nada.
    # ids 1..Nt provincias (tierra), Nt+1.. regiones marinas. La costa se toma
    # de elev2 (fina), asi el raster respeta el litoral del render pleno y la
    # pagina de regiones puede hacer hit-testing por pixel.
    subr = civd.get("subregiones") or {}
    lt = (subr.get("tierra") or {}).get("lista", [])
    lm = (subr.get("mar") or {}).get("lista", [])
    subregiones_j = None
    if lt or lm:
        it = (subr.get("tierra") or {}).get("idmap")
        im2 = (subr.get("mar") or {}).get("idmap")
        vacio = np.full((ncw, ncw), -1, np.int32)
        it_k = (it if it is not None else vacio)[np.ix_(yk, xk)]
        im_k = (im2 if im2 is not None else vacio)[np.ix_(yk, xk)]
        ty = (np.arange(nky) * elev2.shape[0] / nky).astype(np.intp)
        tx = (np.arange(nkx) * elev2.shape[1] / nkx).astype(np.intp)
        tierra_k = elev2[np.ix_(ty, tx)] > 0.0
        nt = len(lt)
        comb = np.where(tierra_k,
                        np.where(it_k >= 0, it_k + 1, 0),
                        np.where(im_k >= 0, im_k + 1 + nt, 0)).astype(np.int32)
        rid = np.zeros((nky, nkx, 3), np.uint8)
        rid[..., 0] = (comb & 255).astype(np.uint8)
        rid[..., 1] = ((comb >> 8) & 255).astype(np.uint8)
        Image.fromarray(rid).save(f"{salida}_regiones.png")
        subregiones_j = {
            "png": Path(salida).name + "_regiones.png",
            "res": [int(nkx), int(nky)],
            "res_civ": [int(ncw), int(ncw)],
            "tierra": [{"id": r["id"] + 1, "nombre": r["nombre"],
                        "pais": r["pais"], "asentamiento": r["asent"],
                        "rgb": r["rgb"], "area": r["area"]} for r in lt],
            "mar": [{"id": r["id"] + 1 + nt, "nombre": r["nombre"],
                     "rgb": r["rgb"], "area": r["area"]} for r in lm],
        }

    civ_json = {"asentamientos": asent_j, "caminos": caminos_j, "rutas": rutas_j,
                "paises": paises_j, "subregiones": subregiones_j}
    _render_civ_png(salida, civ_json, img_paises, nx, ny)
    return (civ_json, png_name)


def _render_civ_png(salida, civ_json, img_paises, nx, ny):
    """Mapa POLITICO renderizado: el clima HD de fondo + tinte de paises +
    caminos, rutas comerciales y asentamientos ROTULADOS (capitales y ciudades
    siempre; pueblos y aldeas solo con el punto). Se guarda como
    {salida}_civ.png; si el clima HD aun no existe, el fondo es plano."""
    try:
        base = Image.open(f"{salida}_climahd.png").convert("RGBA")
        if base.size != (nx, ny):
            base = base.resize((nx, ny), Image.BILINEAR)
    except OSError:
        base = Image.new("RGBA", (nx, ny), (24, 46, 74, 255))
    tinte = img_paises.resize((nx, ny), Image.NEAREST)
    # el overlay trae alpha 235 (interior, pensado para el visor) / 255
    # (frontera): aqui el interior se atenua a ~120 para que el relieve
    # respire debajo del tinte; la frontera queda opaca
    ta = np.asarray(tinte).copy()
    ta[..., 3] = np.where(ta[..., 3] >= 250, 255,
                          ta[..., 3] // 2).astype(np.uint8)
    img = Image.alpha_composite(base, Image.fromarray(ta, "RGBA"))
    d = ImageDraw.Draw(img)
    esc = max(1.0, nx / 1024.0)               # grosores/radios ~constantes en px vistos

    for r in civ_json["caminos"]:
        p = [tuple(q) for q in r["puntos"]]
        if len(p) >= 2:
            d.line(p, fill=(120, 88, 55, 230), width=max(1, int(round(1.5 * esc))))
    for r in civ_json["rutas"]:
        p = [tuple(q) for q in r["puntos"]]
        if len(p) < 2:
            continue
        if r["mar"]:
            # discontinua manual (PIL no trae dash): tramos alternos por segmento
            on = True
            for a, b in zip(p[:-1], p[1:]):
                if on:
                    d.line([a, b], fill=(45, 190, 200, 235),
                           width=max(1, int(round(2.0 * esc))))
                on = not on
        else:
            d.line(p, fill=(225, 178, 48, 245), width=max(2, int(round(2.5 * esc))))

    radios = (2.2, 3.2, 4.6, 6.0)             # aldea, pueblo, ciudad, capital
    for a in sorted(civ_json["asentamientos"], key=lambda q: q["rango"]):
        x, y = a["x"], a["y"]
        rr = radios[min(a["rango"], 3)] * esc
        relleno = (246, 242, 232, 255) if a["rango"] >= 2 else (218, 212, 196, 255)
        borde = (176, 42, 42, 255) if a["rango"] == 3 else (74, 58, 40, 255)
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=relleno, outline=borde,
                  width=max(1, int(round((1.6 if a["rango"] == 3 else 1.0) * esc))))
        if a["rango"] == 3:
            r2 = rr + 2.5 * esc
            d.ellipse([x - r2, y - r2, x + r2, y + r2], outline=(176, 42, 42, 220),
                      width=max(1, int(round(1.2 * esc))))
        if a["rango"] >= 2:                    # rotulo con halo oscuro (legible)
            tx, ty = x + rr + 3 * esc, y
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                d.text((tx + dx, ty + dy), a["nombre"], fill=(15, 14, 10, 220),
                       anchor="lm")
            d.text((tx, ty), a["nombre"], fill=(248, 245, 236, 255), anchor="lm")
    img.convert("RGB").save(f"{salida}_civ.png")


def exportar_capas(salida, campos, elev2, elev_c, hidro, nx, ny,
                   res_datos, res_koppen, temperatura=0.0, civ_dials=None):
    """Escribe los artefactos de inspeccion/overlays del contrato:
    {salida}_koppen.png, _cuencas.png, _datos.png, _datos2.png y _capas.json.
    Coordenadas vectoriales en PIXELES DEL RENDER PLENO. Devuelve
    (res_datos, res_koppen) efectivos usados."""
    import json as _json
    ncy, ncx = elev_c.shape
    ndy, ndx = res_datos
    nky, nkx = res_koppen

    # ---- rasters de datos (inspector, RGB OPACO) ----
    md = _campos_en_malla(campos, elev2, elev_c, ndy, ndx)
    tair_d = md["tair"]
    tmin = float(np.nanmin(tair_d)); tmax = float(np.nanmax(tair_d))
    if not np.isfinite(tmin) or tmax - tmin < 1e-3:
        tmin, tmax = -1.0, 1.0
    datos = np.zeros((ndy, ndx, 3), np.uint8)
    datos[..., 0] = _quant(tair_d, tmin, tmax)
    datos[..., 1] = _quant(md["precip"], 0.0, 1.0)
    datos[..., 2] = _quant(md["alt"], 0.0, 1.0)
    Image.fromarray(datos).save(f"{salida}_datos.png")
    del datos
    datos2 = np.zeros((ndy, ndx, 3), np.uint8)
    bid = md["bioma"].astype(np.int16)
    kid = md["koppen"].astype(np.int16)
    datos2[..., 0] = np.where(md["tierra"], np.clip(bid, 0, 254), 255).astype(np.uint8)
    datos2[..., 1] = np.where(md["tierra"], np.clip(kid, 0, 254), 255).astype(np.uint8)
    datos2[..., 2] = _quant(md["hielo"], 0.0, 1.0)
    Image.fromarray(datos2).save(f"{salida}_datos2.png")
    del datos2

    # ---- overlay Koppen (RGBA, mar transparente) ----
    mk = _campos_en_malla(campos, elev2, elev_c, nky, nkx)
    kmap = mk["koppen"]
    kop = np.zeros((nky, nkx, 4), np.uint8)
    idx = np.clip(kmap, 0, len(KOPPEN) - 1)
    for ch in range(3):
        kop[..., ch] = _KOPPEN_RGB[idx, ch]
    kop[..., 3] = np.where(mk["tierra"] & (kmap != 255), 255, 0).astype(np.uint8)
    Image.fromarray(kop, "RGBA").save(f"{salida}_koppen.png")
    del kop, mk

    # ---- overlay de cuencas (RGBA) sobre res_cuencas (== res_koppen) ----
    bid_hidro, top_roots = _cuencas_top(hidro, n=12)
    ncy2, ncx2 = res_koppen
    bmap = _malla_bloques(bid_hidro.astype(np.float32) + 1.0, ncy2, ncx2)  # nearest via slicing si no divide
    # _malla_bloques promedia; para ids usar submuestreo nearest explicito
    hy, hx = bid_hidro.shape
    yi = (np.arange(ncy2) * hy / ncy2).astype(np.intp)
    xi = (np.arange(ncx2) * hx / ncx2).astype(np.intp)
    bmap = bid_hidro[np.ix_(yi, xi)]
    cue = np.zeros((ncy2, ncx2, 4), np.uint8)
    val = bmap >= 0
    ids = np.clip(bmap, 0, len(_CUENCA_RGB) - 1)
    for ch in range(3):
        cue[..., ch] = np.where(val, _CUENCA_RGB[ids, ch], 0)
    cue[..., 3] = np.where(val, 140, 0).astype(np.uint8)
    # frontera de cuenca: celda cuyo id difiere de algun vecino
    borde = np.zeros((ncy2, ncx2), bool)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        borde |= (np.roll(rolly(bmap, dy), dx, 1) != bmap)
    borde &= val
    for ch in range(3):
        cue[..., ch] = np.where(borde, (_CUENCA_RGB[ids, ch] * 0.45).astype(np.uint8), cue[..., ch])
    cue[..., 3] = np.where(borde, 255, cue[..., 3]).astype(np.uint8)
    Image.fromarray(cue, "RGBA").save(f"{salida}_cuencas.png")
    del cue

    # ---- vectores del JSON ----
    vu = campos["vu"]; vv = campos["vv"]
    cu = campos["cu"]; cv = campos["cv"]
    sst_anom = campos.get("sst_anom", np.zeros_like(elev_c))
    tierra_c = elev_c > 0.0
    mar_c = ~tierra_c
    kx_c = nx / ncx; ky_c = ny / ncy
    paso = max(1, int(np.ceil(max(ncx, ncy) / 24.0)))
    vientos = []
    corrientes = []
    for yy in range(paso // 2, ncy, paso):
        for xx in range(paso // 2, ncx, paso):
            px = round((xx + 0.5) * kx_c, 1); py = round((yy + 0.5) * ky_c, 1)
            if tierra_c[yy, xx]:
                vientos.append({"x": px, "y": py,
                                "u": round(float(vu[yy, xx]), 4),
                                "v": round(float(vv[yy, xx]), 4)})
            elif mar_c[yy, xx]:
                corrientes.append({"x": px, "y": py,
                                   "u": round(float(cu[yy, xx]), 4),
                                   "v": round(float(cv[yy, xx]), 4),
                                   "anom": round(float(sst_anom[yy, xx]), 4)})

    # ---- circuitos (giros oceanicos) escalados a px del lienzo ----
    circuitos_j = []
    for c in circuitos_corriente(cu, cv, sst_anom, mar_c, campos.get("psi")):
        pts = c["puntos"][::2]                 # decimado suave: lazos redondos
                                               # al hacer zoom sin inflar el JSON
        circuitos_j.append({
            "puntos": [[round(p[0] * kx_c, 1), round(p[1] * ky_c, 1)] for p in pts],
            "anom": round(c["anom"], 4),
            "fuerza": round(c["fuerza"], 3)})

    # ---- isoyetas (precip gruesa, decimada) ----
    niso = min(ncx, 160)
    niso_y = min(ncy, 160)
    precip_iso = _malla_bloques(campos["precip"], niso_y, niso)
    esc_ix = nx / niso; esc_iy = ny / niso_y
    niveles = [0.2, 0.4, 0.6, 0.8]
    ms = _marching_squares(precip_iso, niveles, esc_ix, esc_iy)
    lineas = []
    for entry in ms:
        for seg in entry["segmentos"]:
            lineas.append({"nivel": entry["nivel"],
                           "puntos": [[round(seg[0][0], 1), round(seg[0][1], 1)],
                                      [round(seg[1][0], 1), round(seg[1][1], 1)]]})

    # ---- rios ----
    rios_j = _rios_json(hidro, nx, ny, n=20, cada=4)

    # ---- capa de civilizacion (asentamientos, caminos, rutas, paises) ----
    # se calcula sobre una malla de civ reducida a partir de los mismos campos
    # (Koppen + cuencas/rios), en formato vectorial legible; escala a px de render
    civ_j, paises_png = _capa_civilizacion(campos, elev2, elev_c, hidro,
                                           nx, ny, res_koppen, salida,
                                           civ_dials=civ_dials)

    capas = {
        "version": 1,
        "resolucion": [int(nx), int(ny)],
        "res_fisica": [int(ncx), int(ncy)],
        "res_hidro": [int(hidro["res"][1]), int(hidro["res"][0])],
        "res_datos": [int(ndx), int(ndy)],
        "escalas": {"tair": [round(tmin, 3), round(tmax, 3)],
                    "precip": [0, 1], "alt": [0, 1], "hielo": [0, 1]},
        "koppen": {"png": Path(salida).name + "_koppen.png",
                   "clases": [{"id": k, "cod": v[0], "nombre": v[1],
                               "rgb": list(v[2])} for k, v in KOPPEN.items()]},
        "biomas": [{"id": k, "nombre": v[0], "rgb": list(v[1])}
                   for k, v in BIOMAS.items()],
        "cuencas": {"png": Path(salida).name + "_cuencas.png", "n": int(len(top_roots))},
        "vientos": vientos,
        "corrientes": corrientes,
        "circuitos": circuitos_j,
        "isoyetas": {"niveles": niveles, "lineas": lineas},
        "rios": rios_j,
        "asentamientos": civ_j["asentamientos"],
        "caminos": civ_j["caminos"],
        "rutas": civ_j["rutas"],
        "paises": civ_j["paises"],
        "subregiones": civ_j.get("subregiones"),
    }
    Path(f"{salida}_capas.json").write_text(
        _json.dumps(capas, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8")
    return (int(ndx), int(ndy)), (int(nkx), int(nky))


# ============================ autoprueba ====================================
if __name__ == "__main__":
    import time

    SALIDA = str(Path(__file__).resolve().parent / "salidas" / "autoprueba")
    Path(SALIDA).mkdir(parents=True, exist_ok=True)

    def _elev_sintetico(n):
        """Un continente central (oceano al este y al oeste) con una CORDILLERA
        MERIDIANA (norte-sur) en su eje: sirve para ver la sombra de lluvia a
        sotavento de los westerlies. El continente baja en pendiente suave hacia
        ambas costas para que los rios drenen al mar (estuarios). Casquetes
        implicitos por latitud."""
        xs = np.linspace(0, 1, n)[None, :] * np.ones((n, 1))
        elev = np.full((n, n), -0.5)                 # oceano de fondo
        lo, hi = 0.30, 0.72
        cont = (xs >= lo) & (xs <= hi)
        # pendiente regional: alta en el interior, ~0 en la costa -> los rios
        # corren al mar en vez de estancarse (distancia normalizada a la costa)
        dcosta = np.minimum(xs - lo, hi - xs) / ((hi - lo) / 2.0)   # 0 costa..1 centro
        base = 0.02 + 0.20 * np.clip(dcosta, 0, 1)
        # cordillera meridiana centrada en col ~0.51, gaussiana en x
        cx = 0.51
        ridge = 0.72 * np.exp(-((xs - cx) / 0.05) ** 2)
        elev = np.where(cont, base + ridge, elev)
        # una peninsula/isla secundaria para variedad de costas
        yy2, xx2 = np.mgrid[0:n, 0:n] / n
        isla = 0.35 * np.exp(-(((xx2 - 0.85) / 0.06) ** 2 + ((yy2 - 0.4) / 0.10) ** 2))
        elev = elev + np.where(isla > 0.12, isla, 0.0)
        return np.clip(elev, -1, 1)

    def _fila_de_lat(n, lat):
        """Fila mas cercana a la latitud dada (lat en -1..1, +1 = polo N)."""
        return int(round((1.0 - lat) / 2.0 * (n - 1)))

    n = 200
    elev = _elev_sintetico(n)
    xs = np.linspace(0, 1, n)
    col_cresta = int(np.argmin(np.abs(xs - 0.51)))

    escenarios = [
        ("templado",  0.0, 1.0),
        ("frio",     -0.7, 1.0),
        ("calido_arido", 0.6, 0.35),
        ("humedo",    0.0, 1.8),
    ]
    resultados = {}
    for nombre, temp, prec in escenarios:
        c = simular_clima(elev, temp, prec)
        render_clima(c, elev).save(f"{SALIDA}/prueba_clima_{nombre}.png")
        resultados[nombre] = c
        b = c["bioma"]; nt = float((elev > 0).sum())
        desierto = float(((b == 4) | (b == 5)).sum()) / nt
        print(f"[{nombre:14s}] tmedia_tierra={c['tair'][elev>0].mean():+.3f}  "
              f"hielo={float((c['hielo']>0.5).mean()):.4f}  "
              f"rios={int(c['rios'].sum())}  estuarios={int(c['estuarios'].sum())}  "
              f"desierto={desierto:.3f}")

    # ---- invariantes ----
    tmpl = resultados["templado"]
    tierra = elev > 0

    # (a) sombra de lluvia: en una banda de westerlies (|lat|~45), el lado
    #     BARLOVENTO (oeste de la cresta) llueve mas que el SOTAVENTO (este).
    banda = np.zeros(n, bool)
    for lat in (0.45, 0.50, 0.55, -0.45, -0.50, -0.55):
        banda[_fila_de_lat(n, lat)] = True
    oeste = slice(col_cresta - 12, col_cresta - 3)
    este = slice(col_cresta + 3, col_cresta + 12)
    p = tmpl["precip"]
    barlovento = p[banda][:, oeste].mean()
    sotavento = p[banda][:, este].mean()
    print(f"barlovento(O)={barlovento:.3f}  sotavento(E)={sotavento:.3f}")
    assert barlovento > sotavento * 1.10, "el sotavento deberia ser mas seco"

    # (b) conveccion ecuatorial: precip en el ecuador > precip en el interior a
    #     lat ~25 (desiertos subtropicales).
    filas_ec = [_fila_de_lat(n, l) for l in (-0.05, 0.0, 0.05)]
    filas_25 = [_fila_de_lat(n, l) for l in (0.25, -0.25)]
    interior = slice(int(0.34 * n), int(0.68 * n))
    p_ec = p[filas_ec][:, interior]
    p_25 = p[filas_25][:, interior]
    m_ec = p_ec[tierra[filas_ec][:, interior]].mean()
    m_25 = p_25[tierra[filas_25][:, interior]].mean()
    print(f"precip ecuador={m_ec:.3f}  precip lat25={m_25:.3f}")
    assert m_ec > m_25, "el ecuador deberia llover mas que los subtropicos"

    # (c) el hielo crece al enfriar el planeta.
    h_tmpl = float((resultados["templado"]["hielo"] > 0.5).mean())
    h_frio = float((resultados["frio"]["hielo"] > 0.5).mean())
    print(f"hielo templado={h_tmpl:.4f}  hielo frio={h_frio:.4f}")
    assert h_frio > h_tmpl, "con frio deberia haber mas hielo"

    # (d) hay rios y estuarios.
    assert tmpl["rios"].sum() > 0, "no hay rios"
    assert tmpl["estuarios"].sum() > 0, "no hay estuarios"

    # (e) la red fluvial responde al dial de precipitaciones (umbral absoluto,
    #     no percentil): mundo humedo -> mas celdas de rio que mundo arido.
    r_hum = int(resultados["humedo"]["rios"].sum())
    r_ari = int(resultados["calido_arido"]["rios"].sum())
    r_tmp = int(tmpl["rios"].sum())
    print(f"rios humedo={r_hum}  templado={r_tmp}  arido={r_ari}")
    assert r_hum > r_tmp > r_ari, "los rios deberian crecer con la lluvia"

    # (f) sin sesgo desertico: en el mundo templado el desierto (calido+frio)
    #     no domina la tierra.
    b = tmpl["bioma"]
    frac_des = float(((b == 4) | (b == 5)).sum()) / float(tierra.sum())
    print(f"fraccion de desierto (templado) = {frac_des:.3f}")
    assert frac_des < 0.35, "demasiado desierto en un mundo templado"

    # ---- rendimiento a 256^2 ----
    elev256 = _elev_sintetico(256)
    simular_clima(elev256, 0.0, 1.0)          # calentar (compilar rutas numpy)
    t0 = time.perf_counter()
    NREP = 5
    for _ in range(NREP):
        simular_clima(elev256, 0.0, 1.0)
    dt = (time.perf_counter() - t0) / NREP
    print(f"\nOK: todas las invariantes pasan. "
          f"simular_clima a 256^2: {dt*1000:.1f} ms/llamada")
