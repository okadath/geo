"""Catch-all que delega en los modulos propietarios (juego_srv/fantasia_srv/
batalla_srv) via HandlerCompat, pasando por la cola de renders y aplicando el
gating de plan (PLATAFORMA §1.2).

Contrato de los _srv (sin cambios): manejar_get(handler, url) -> bool y
manejar_post(handler, ruta, datos) -> bool, donde True = peticion atendida.
`url` es un urlparse-result con `.path` y `.query`; `handler` es un
HandlerCompat que captura la respuesta. Aqui se convierte esa captura en una
Response de FastAPI (respeta Content-Type y Cache-Control no-store cuando
cache=False). Si ningun modulo atiende -> 404 {"error":"no existe"}.

Gating (fase 2), aplicado SOLO a los endpoints de render que devuelven PNG:
  1. ANTES de delegar: rate limit + tope diario (limites.permitir_render) -> 429
     si se excede, y CLAMPEO de calidad (fantasia) / px (battlemap) segun el
     plan reescribiendo la query que ve el _srv.
  2. DESPUES de delegar: si la respuesta es un PNG de render, se contabiliza
     (limites.incrementar) y, si el plan lleva marca_agua, se estampa el texto
     sobre los BYTES de salida (nunca en el PNG cacheado en disco por el _srv).
La prioridad en la cola la fija el plan (comercial primero).
"""
import importlib
import io
import json
from urllib.parse import SplitResult, parse_qsl, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from .compat import HandlerCompat
from .cola import COLA, PRIORIDAD_COMERCIAL, PRIORIDAD_NORMAL
from .rutas_cuentas import resolver_plan, identidad
from .planes import limites as limites_plan
from .limites import permitir_render, incrementar

router = APIRouter()

# modulos de backend enchufables (motor del juego, renders del lado servidor):
# cada uno expone manejar_get/manejar_post. La logica propietaria (motor,
# calculos, generacion) vive en estos modulos, NO en el navegador.
MODULOS = []
for _nombre in ("juego_srv", "fantasia_srv", "batalla_srv"):
    try:
        MODULOS.append(importlib.import_module(_nombre))
    except ImportError:
        pass

# endpoints _srv que producen un PNG de render: unicos sujetos a contador,
# rate limit, clampeo de calidad y marca de agua. El resto (JSON de juego,
# info/lugar/rotulos/vtt) no cuenta ni se toca.
RENDER_PATHS = {
    "/api/fantasia/render", "/api/fantasia/sector", "/api/fantasia/deco",
    "/api/batalla/mapa",
}

# calidad por defecto interna de fantasia (fantasia_srv._params_comunes): si el
# tope del plan queda por debajo hay que bajarla aunque el cliente no la mande
_FANTASIA_CALIDAD_DEFECTO = 2


def _url(request: Request, query=None):
    """Objeto tipo urlparse-result (con .path y .query) que esperan los _srv.
    `query` permite pasar una version ya clampeada."""
    return SplitResult(scheme="", netloc="", path=request.url.path,
                       query=request.url.query if query is None else query,
                       fragment="")


def _prioridad(plan):
    return PRIORIDAD_COMERCIAL if plan == "comercial" else PRIORIDAD_NORMAL


def _clampear_query(path, query, plan):
    """Acota calidad (fantasia) o px (battlemap) al tope del plan, reescribiendo
    la query string. Solo BAJA valores; nunca los sube (no cambia defaults de
    planes altos)."""
    lim = limites_plan(plan)
    pares = parse_qsl(query, keep_blank_values=True)

    if path.startswith("/api/fantasia/"):
        tope = lim["fantasia_calidad_max"]
        nuevos, visto = [], False
        for k, v in pares:
            if k == "calidad":
                visto = True
                try:
                    if int(v) > tope:
                        v = str(tope)
                except ValueError:
                    v = str(tope)
            nuevos.append((k, v))
        # sin calidad explicita, el default interno es 2: bajarlo si excede tope
        if not visto and _FANTASIA_CALIDAD_DEFECTO > tope:
            nuevos.append(("calidad", str(tope)))
        return urlencode(nuevos)

    if path == "/api/batalla/mapa":
        tope = lim["battlemap_px_max"]
        nuevos = []
        for k, v in pares:
            if k == "px":
                try:
                    if int(v) > tope:
                        v = str(tope)
                except ValueError:
                    pass
            nuevos.append((k, v))
        return urlencode(nuevos)

    return query


def estampar_marca(png, texto="tecto — beta gratis"):
    """Estampa un texto discreto semitransparente en la esquina inferior
    derecha del PNG (marca de agua del plan free). Convierte a RGBA para no
    romper PNGs con paleta y devuelve PNG. Ante cualquier fallo devuelve el PNG
    original sin marca."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(io.BytesIO(png)).convert("RGBA")
        W, H = img.size
        # tamano de fuente relativo al ancho, acotado
        px = max(11, min(28, W // 48))
        try:
            fnt = ImageFont.load_default(size=px)     # Pillow >= 10.1 escalable
        except TypeError:
            fnt = ImageFont.load_default()
        capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
        dr = ImageDraw.Draw(capa)
        try:
            x0, y0, x1, y1 = dr.textbbox((0, 0), texto, font=fnt)
            tw, th = x1 - x0, y1 - y0
        except AttributeError:
            tw, th = dr.textsize(texto, font=fnt)
        margen = max(6, px // 2)
        x = W - tw - margen
        y = H - th - margen
        # sombra tenue para legibilidad sobre fondos claros u oscuros
        dr.text((x + 1, y + 1), texto, font=fnt, fill=(0, 0, 0, 110))
        dr.text((x, y), texto, font=fnt, fill=(255, 255, 255, 150))
        img = Image.alpha_composite(img, capa)
        salida = io.BytesIO()
        img.save(salida, "PNG")
        return salida.getvalue()
    except Exception:
        return png


def _respuesta(h: HandlerCompat):
    """Convierte la captura de HandlerCompat en una Response de FastAPI."""
    if not h.atendido:
        return JSONResponse({"error": "no existe"}, status_code=404)
    cabeceras = {} if h.cache else {"Cache-Control": "no-store"}
    return Response(content=h.cuerpo, media_type=h.ctype,
                    status_code=h.status, headers=cabeceras)


def _es_png(h: HandlerCompat):
    return h.atendido and (h.ctype or "").startswith("image/png")


@router.get("/{ruta:path}")
def modulos_get(ruta: str, request: Request):
    usuario, plan = resolver_plan(request)
    es_render = request.url.path in RENDER_PATHS

    if es_render:
        ident = identidad(request, usuario)
        ok, motivo = permitir_render(ident, plan)
        if not ok:
            return JSONResponse(
                {"error": "limite de renders alcanzado", "detalle": motivo},
                status_code=429)
        query = _clampear_query(request.url.path, request.url.query, plan)
        url = _url(request, query)
    else:
        url = _url(request)

    h = HandlerCompat(usuario=usuario, plan=plan)

    def trabajo():
        for mod in MODULOS:
            if mod.manejar_get(h, url):
                return True
        return False

    # los renders frios pasan por la cola acotada (prioridad segun plan)
    COLA.ejecutar(trabajo, prioridad=_prioridad(plan))

    # contador + marca de agua solo sobre PNG de render efectivos
    if es_render and _es_png(h):
        incrementar(ident)
        if limites_plan(plan)["marca_agua"]:
            h.cuerpo = estampar_marca(h.cuerpo)
            h.cache = False   # la version con marca no se comparte via cache
    return _respuesta(h)


@router.post("/{ruta:path}")
async def modulos_post(ruta: str, request: Request):
    usuario, plan = resolver_plan(request)
    crudo = await request.body()
    if crudo:
        try:
            datos = json.loads(crudo)
        except ValueError:
            datos = {}
    else:
        datos = {}
    h = HandlerCompat(usuario=usuario, plan=plan)
    ruta_srv = request.url.path

    def trabajo():
        for mod in MODULOS:
            if mod.manejar_post(h, ruta_srv, datos):
                return True
        return False

    COLA.ejecutar(trabajo, prioridad=_prioridad(plan))
    return _respuesta(h)
