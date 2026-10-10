"""Cuentas: entrada por enlace magico, logout por cookie y estado de la cuenta.

Sin contrasenas: POST /api/cuenta/enlace manda el enlace (correo.py) y
GET /entrar/<token> lo consume y abre la sesion.

La cookie "sesion" es HttpOnly + SameSite=Lax con max_age de 30 dias; su valor
es el token que persiste en cuentas.db. `resolver_plan(request)` es el punto de
enganche del gating (lo consumen rutas_modulos y rutas_lab): traduce la cookie a
(usuario_o_None, plan_vigente). Sin cookie -> anonimo tratado como free e
identificado por IP.
"""
import logging
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import correo, cuentas
from .config import RE_SELLO
from .limites import uso_hoy
from .planes import PLANES, limites as limites_plan

router = APIRouter()

COOKIE = "sesion"
COOKIE_DIAS = 30
# destino de un enlace magico invalido, usado o caducado
ENLACE_INVALIDO = "/yo?enlace=invalido"

log = logging.getLogger("servidor.rutas_cuentas")


def _fecha(epoch):
    """Epoch (float, segundos) -> 'YYYY-MM-DD' legible para el front; None si no
    hay vencimiento (plan free). El front pinta este valor tal cual."""
    if not epoch:
        return None
    return time.strftime("%Y-%m-%d", time.localtime(epoch))


def resolver_plan(request: Request):
    """(usuario_o_None, plan_vigente) a partir de la cookie de sesion.

    Firma estable desde el stub de la fase 1: rutas_modulos no cambia."""
    token = request.cookies.get(COOKIE)
    usuario = cuentas.usuario_de_token(token) if token else None
    return usuario, cuentas.plan_vigente(usuario)


def identidad(request: Request, usuario):
    """Identidad para contadores/rate limit: email si hay sesion, si no la IP."""
    if usuario and usuario.get("email"):
        return usuario["email"]
    cli = request.client
    return "ip:" + (cli.host if cli else "desconocida")


def _fijar_cookie(resp, token: str):
    resp.set_cookie(COOKIE, token, max_age=COOKIE_DIAS * 86400,
                    httponly=True, samesite="lax", path="/")


async def _cuerpo(request: Request):
    import json
    crudo = await request.body()
    if not crudo:
        return {}
    try:
        return json.loads(crudo)
    except ValueError:
        return {}


@router.post("/api/cuenta/enlace")
async def pedir_enlace(request: Request):
    """Envia un enlace magico de entrada. Cuerpo {email, volver?}.

    200 {ok, modo: "smtp"|"dev"} si el correo tiene forma valida (crea el
    usuario free si no existia; no revela si ya existia); 400 email invalido;
    429 si ya se pidieron ENLACES_HORA en la ultima hora; 502 si el SMTP
    falla."""
    datos = await _cuerpo(request)
    if not isinstance(datos, dict):
        datos = {}
    email = cuentas.normalizar_email(datos.get("email"))
    if not email:
        return JSONResponse({"error": "email invalido"}, status_code=400)
    if cuentas.enlaces_ultima_hora(email) >= cuentas.ENLACES_HORA:
        return JSONResponse(
            {"error": "demasiados enlaces; prueba dentro de una hora"},
            status_code=429)
    cuentas.asegurar_usuario(email)
    token = cuentas.crear_enlace(email, datos.get("volver"))
    try:
        modo = correo.enviar_enlace(email, correo.url_entrar(token))
    except Exception:
        log.exception("fallo al enviar el enlace magico a %s", email)
        return JSONResponse({"error": "no se pudo enviar el correo"},
                            status_code=502)
    return {"ok": True, "modo": modo}


@router.get("/entrar/{token}")
def entrar_con_enlace(token: str):
    """Aterrizaje del enlace magico: consume el token (un solo uso, 15 min),
    fija la cookie de sesion y redirige (302) a `volver`. Token invalido,
    usado o caducado -> 302 a /yo?enlace=invalido."""
    enlace = cuentas.consumir_enlace(token)
    if not enlace:
        resp = RedirectResponse(ENLACE_INVALIDO, status_code=302)
    else:
        resp = RedirectResponse(enlace["volver"], status_code=302)
        _fijar_cookie(resp, cuentas.crear_sesion(enlace["email"]))
    # el token viaja en la URL: que no se cachee ni se filtre por Referer
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@router.post("/api/cuenta/salir")
def salir(request: Request):
    cuentas.cerrar_sesion(request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@router.get("/api/cuenta")
def cuenta(request: Request):
    usuario, plan = resolver_plan(request)
    lim = limites_plan(plan)
    ident = identidad(request, usuario)
    salida = {
        "plan": plan,
        "limites": {
            "generar_mundos": lim["generar_mundos"],
            "fantasia_calidad_max": lim["fantasia_calidad_max"],
            "battlemap_px_max": lim["battlemap_px_max"],
            "marca_agua": lim["marca_agua"],
            "renders_dia": lim["renders_dia"],
            "cola_prioritaria": lim["cola_prioritaria"],
            "licencia_comercial": lim["licencia_comercial"],
        },
        "uso": {"renders_hoy": uso_hoy(ident), "tope_dia": lim["renders_dia"]},
    }
    salida["guardados_n"] = 0
    salida["mundos_propios"] = []
    if usuario:
        # import diferido: mundos -> rutas_lab -> rutas_cuentas (ciclo)
        from .mundos import mundos_propios
        salida["guardados_n"] = cuentas.contar_guardados(usuario["email"])
        salida["mundos_propios"] = mundos_propios(usuario["email"])
        salida["email"] = usuario["email"]
        salida["expira"] = _fecha(usuario.get("expira"))
        # plan contratado (aunque este vencido) vs. plan vigente ya resuelto
        salida["plan_contratado"] = usuario.get("plan")
    else:
        salida["anonimo"] = True
    return salida


# ---------------------------------------------------------------------------
#  Guardados: /api/yo/guardados (requieren sesion)
# ---------------------------------------------------------------------------
def _sin_sesion():
    return JSONResponse({"error": "requiere sesion"}, status_code=401)


def _malo(motivo):
    return JSONResponse({"error": motivo}, status_code=400)


def _coord(v):
    """Coordenada de battlemap: entero >= 0 (no bool) o None si no vale."""
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None
    return v


def _guardado_de(datos):
    """Valida el cuerpo {tipo, sello, x?, y?, query?}. Devuelve
    (dict_limpio, None) o (None, respuesta_400)."""
    if not isinstance(datos, dict):
        return None, _malo("cuerpo invalido")
    tipo = datos.get("tipo")
    if tipo not in cuentas.TIPOS_GUARDADO:
        return None, _malo("tipo invalido")
    sello = datos.get("sello")
    if not isinstance(sello, str) or not re.fullmatch(RE_SELLO, sello):
        return None, _malo("sello invalido")
    g = {"tipo": tipo, "sello": sello, "x": None, "y": None,
         "query": cuentas.sanear_query(datos.get("query"))}
    if tipo == "battlemap":
        g["x"], g["y"] = _coord(datos.get("x")), _coord(datos.get("y"))
        if g["x"] is None or g["y"] is None:
            return None, _malo("x/y invalidos")
    return g, None


@router.get("/api/yo/guardados")
def listar_guardados(request: Request):
    usuario, _ = resolver_plan(request)
    if not usuario:
        return _sin_sesion()
    return {"guardados": cuentas.listar_guardados(usuario["email"])}


@router.post("/api/yo/guardados")
async def anadir_guardado(request: Request):
    """Anade {tipo, sello, x?, y?, query?}; un duplicado es idempotente
    (200 con nuevo=false)."""
    usuario, _ = resolver_plan(request)
    if not usuario:
        return _sin_sesion()
    g, err = _guardado_de(await _cuerpo(request))
    if err:
        return err
    guardado, nuevo = cuentas.anadir_guardado(
        usuario["email"], g["tipo"], g["sello"], g["x"], g["y"], g["query"])
    return {"ok": True, "nuevo": nuevo, "guardado": guardado}


@router.delete("/api/yo/guardados")
async def quitar_guardado(request: Request):
    """Quita {tipo, sello, x?, y?}; si no existia responde igual con
    borrado=false."""
    usuario, _ = resolver_plan(request)
    if not usuario:
        return _sin_sesion()
    g, err = _guardado_de(await _cuerpo(request))
    if err:
        return err
    borrado = cuentas.quitar_guardado(
        usuario["email"], g["tipo"], g["sello"], g["x"], g["y"])
    return {"ok": True, "borrado": borrado}
