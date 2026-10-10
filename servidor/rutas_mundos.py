"""API de mundos para Explorar, la ficha y /yo (logica en mundos.py).

  GET  /api/w?orden=nuevos|azar&q=&n=24   lista publica resumida
  GET  /api/w/dia?desde=<sello>           mundo del dia (o el siguiente)
  GET  /api/w/<sello>[?d=<stem>]          ficha del mundo
  POST /api/w/<sello>/visibilidad         {publico: bool}; solo el dueno

`/api/w/dia` se declara antes que `/api/w/{sello}`; ademas `dia` no casa con
RE_SELLO, asi que nunca se confunde con un sello.
"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import mundos
from .rutas_cuentas import resolver_plan

router = APIRouter()


def _email(request: Request):
    usuario, _plan = resolver_plan(request)
    return (usuario or {}).get("email")


@router.get("/api/w")
def api_lista(request: Request):
    qp = request.query_params
    orden = qp.get("orden", "nuevos")
    if orden not in ("nuevos", "azar"):
        orden = "nuevos"
    try:
        n = int(qp.get("n", 24))
    except ValueError:
        n = 24
    return mundos.lista_publica(orden, qp.get("q", ""), n)


@router.get("/api/w/dia")
def api_dia(request: Request):
    m = mundos.mundo_del_dia(request.query_params.get("desde"), _email(request))
    if m is None:
        return JSONResponse({"error": "sin mundos"}, status_code=404)
    return m


@router.get("/api/w/{sello}")
def api_mundo(sello: str, request: Request):
    m = mundos.mundo(sello, request.query_params.get("d"), _email(request))
    if m is None:
        return JSONResponse({"error": "mundo no encontrado"}, status_code=404)
    return m


@router.post("/api/w/{sello}/visibilidad")
async def api_visibilidad(sello: str, request: Request):
    try:
        datos = json.loads(await request.body() or b"{}")
    except ValueError:
        datos = {}
    publico = datos.get("publico") if isinstance(datos, dict) else None
    if not isinstance(publico, bool):
        return JSONResponse({"error": "publico debe ser bool"}, status_code=400)
    res = mundos.cambiar_visibilidad(sello, publico, _email(request))
    if res == "no existe":
        return JSONResponse({"error": "mundo no encontrado"}, status_code=404)
    if res == "prohibido":
        return JSONResponse({"error": "solo el dueno"}, status_code=403)
    return {"sello": sello, "publico": publico}
