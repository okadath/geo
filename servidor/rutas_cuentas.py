"""Cuentas: registro, login/logout por cookie de sesion y estado de la cuenta.

La cookie "sesion" es HttpOnly + SameSite=Lax con max_age de 30 dias; su valor
es el token que persiste en cuentas.db. `resolver_plan(request)` es el punto de
enganche del gating (lo consumen rutas_modulos y rutas_lab): traduce la cookie a
(usuario_o_None, plan_vigente). Sin cookie -> anonimo tratado como free e
identificado por IP.
"""
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import cuentas
from .limites import uso_hoy
from .planes import PLANES, limites as limites_plan

router = APIRouter()

COOKIE = "sesion"
COOKIE_DIAS = 30


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


def _fijar_cookie(resp: JSONResponse, token: str):
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


@router.post("/api/cuenta/registro")
async def registro(request: Request):
    datos = await _cuerpo(request)
    email = str(datos.get("email", ""))
    clave = str(datos.get("clave", ""))
    ok, motivo = cuentas.registrar(email, clave)
    if not ok:
        return JSONResponse({"error": motivo}, status_code=400)
    email = email.strip().lower()
    token = cuentas.crear_sesion(email)
    resp = JSONResponse({"ok": True, "email": email, "plan": "free"})
    _fijar_cookie(resp, token)
    return resp


@router.post("/api/cuenta/entrar")
async def entrar(request: Request):
    datos = await _cuerpo(request)
    email = cuentas.verificar(datos.get("email", ""), datos.get("clave", ""))
    if not email:
        return JSONResponse({"error": "email o clave incorrectos"},
                            status_code=401)
    token = cuentas.crear_sesion(email)
    usuario = cuentas.obtener_usuario(email)
    resp = JSONResponse({"ok": True, "email": email,
                         "plan": cuentas.plan_vigente(usuario)})
    _fijar_cookie(resp, token)
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
    if usuario:
        salida["email"] = usuario["email"]
        salida["expira"] = _fecha(usuario.get("expira"))
        # plan contratado (aunque este vencido) vs. plan vigente ya resuelto
        salida["plan_contratado"] = usuario.get("plan")
    else:
        salida["anonimo"] = True
    return salida
