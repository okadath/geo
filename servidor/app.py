"""Aplicacion FastAPI: monta todos los routers y el catch-all de modulos.

Orden de montaje = orden de resolucion en FastAPI: primero las rutas concretas
(paginas, lab, cuentas, pagos) y AL FINAL el catch-all `/{ruta:path}` de los
modulos _srv, que ademas cae en 404 si nadie atiende. Asi se replica el viejo
web.py: rutas propias -> modulos -> 404.

Los routers de cuentas y pagos se importan desde el dia 1 (fase 1 = stubs; la
fase 2 los rellena sin tocar este archivo).
"""
import sys

from fastapi import FastAPI

from .config import BASE, SALIDAS

# los modulos _srv viven en la raiz del proyecto (import juego_srv, etc.):
# garantizar que BASE este en sys.path aunque uvicorn se lance desde otro lado
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# salidas/ debe existir antes de atender peticiones (igual que el viejo main)
SALIDAS.mkdir(exist_ok=True)

from . import rutas_paginas, rutas_lab, rutas_cuentas, rutas_pagos, rutas_modulos

app = FastAPI(title="tecto web", docs_url=None, redoc_url=None,
              openapi_url=None)


@app.middleware("http")
async def _no_cache_json(request, call_next):
    """El viejo _json siempre mandaba Cache-Control: no-store. Las rutas nativas
    de FastAPI (lab/cuentas/pagos) devuelven dicts sin ese header, asi que se lo
    ponemos a toda respuesta JSON que no lo traiga (las de modulos/archivos ya
    gestionan su cache y no se tocan)."""
    resp = await call_next(request)
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("application/json") and "cache-control" not in resp.headers:
        resp.headers["Cache-Control"] = "no-store"
    return resp

# rutas concretas primero
app.include_router(rutas_paginas.router)
app.include_router(rutas_lab.router)
app.include_router(rutas_cuentas.router)
app.include_router(rutas_pagos.router)
# catch-all de modulos _srv AL FINAL (tambien produce el 404 por defecto)
app.include_router(rutas_modulos.router)
