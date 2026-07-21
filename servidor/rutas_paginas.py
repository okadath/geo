"""Rutas de paginas HTML y estaticos: mismas rutas y validaciones que el viejo
web.py (allowlists estrictas, regexes, sin traversal). Todo `def` normal
(threadpool de FastAPI): leer archivos del disco es bloqueante.
"""
import os
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .config import (ASSETS, BASE, CTYPE_APP, FRONTEND, RE_APP_REL, RE_ARCHIVO,
                     RE_SELLO, SALIDAS)

router = APIRouter()


def _archivo(ruta, ctype, cache=True):
    """Sirve un archivo del disco como Response, replicando el viejo _archivo:
    404 {"error":"no existe"} si no se puede leer; Cache-Control no-store
    cuando cache=False."""
    try:
        datos = ruta.read_bytes()
    except OSError:
        return JSONResponse({"error": "no existe"}, status_code=404)
    cabeceras = {} if cache else {"Cache-Control": "no-store"}
    return Response(content=datos, media_type=ctype, headers=cabeceras)


def _html(ruta):
    return _archivo(ruta, "text/html; charset=utf-8", cache=False)


# --- front comercial (ADR-004): paginas de frontend/ + estaticos ---
@router.get("/")
def landing():
    return _html(FRONTEND / "index.html")


@router.get("/estudio")
def estudio():
    return _html(FRONTEND / "estudio.html")


@router.get("/estudio/mundo")
def estudio_mundo():
    return _html(FRONTEND / "mundo.html")


# mi cuenta: sesion, plan, uso del dia y tabla de upgrade (mismo patron que /estudio)
@router.get("/cuenta")
def cuenta():
    return _html(FRONTEND / "cuenta.html")


# laboratorio: el panel cientifico completo, antes en "/"
@router.get("/lab")
def lab():
    return _html(BASE / "web.html")


# estaticos del front: allowlist estricta (sin traversal ni ".."), extensiones
# y content-type de CTYPE_APP; cache como los demas estaticos
@router.get("/app/{rel:path}")
def app_estatico(rel: str):
    ext = rel.rsplit(".", 1)[-1] if "." in rel else ""
    if (not RE_APP_REL.fullmatch(rel) or ".." in rel or ext not in CTYPE_APP):
        return JSONResponse({"error": "nombre invalido"}, status_code=400)
    destino = (ASSETS / rel).resolve()
    if not str(destino).startswith(str(ASSETS.resolve()) + os.sep):
        return JSONResponse({"error": "nombre invalido"}, status_code=400)
    # .css/.js sin cache para ver los cambios al recargar; binarios con cache
    return _archivo(destino, CTYPE_APP[ext], cache=(ext not in ("css", "js")))


# pagina de subregiones: mapa interactivo (query: ?sello=...&d=<stem>)
@router.get("/regiones")
def regiones():
    return _html(BASE / "regiones.html")


# juego de conquista por turnos sobre las provincias de UN detalle
@router.get("/juego")
def juego():
    return _html(BASE / "juego.html")


# rutas viejas desactivadas (ADR-009): fantasia y batalla son ahora modos del
# workspace; redirigen conservando la query (?sello&d). status 302.
@router.get("/fantasia")
def fantasia(request: Request):
    q = request.url.query
    extra = f"?{q}" if q else ""
    return RedirectResponse(f"/estudio/mundo{extra}", status_code=302)


@router.get("/batalla")
def batalla(request: Request):
    q = request.url.query
    extra = f"{q}&" if q else ""
    return RedirectResponse(f"/estudio/mundo?{extra}modo=battlemap", status_code=302)


# modulo del detallado: allowlist estricta (sin traversal), solo estos dos
# archivos; sin cache, igual que la pagina, para ver los cambios al recargar
@router.get("/detallar/{nombre}")
def detallar(nombre: str):
    if nombre not in ("detallar.js", "detallar.css"):
        return JSONResponse({"error": "no existe"}, status_code=404)
    ctype = ("application/javascript; charset=utf-8"
             if nombre.endswith(".js") else "text/css; charset=utf-8")
    return _archivo(BASE / "detallar" / nombre, ctype, cache=False)


# archivos de una corrida: GIF/PNG finales, JSON del reproductor, cuadros PNG
# por frame y los detalles. Regexes estrictas -> sin traversal.
@router.get("/salidas/{resto:path}")
def salidas(resto: str):
    barra = resto.find("/")
    if barra < 0 or not re.fullmatch(RE_SELLO, resto[:barra]):
        return JSONResponse({"error": "nombre invalido"}, status_code=400)
    sello, rel = resto[:barra], resto[barra + 1:]
    if re.fullmatch(RE_ARCHIVO, rel):
        ctype = "image/gif" if rel.endswith(".gif") else "image/png"
    elif rel == "mapa_repro.json":
        ctype = "application/json; charset=utf-8"
    elif re.fullmatch(r"mapa_cuadros/(mapa|placas|manto|clima)_[0-9]{4}\.png", rel):
        ctype = "image/png"
    elif re.fullmatch(r"detalles/d[0-9]{6}_f[0-9]+_[0-9a-f]{6}"
                      r"(?:_clima|_climahd|_koppen|_cuencas|_paises|_civ"
                      r"|_regiones|_datos|_datos2)?"
                      r"\.png", rel):
        ctype = "image/png"      # cuadros detallados (un frame gigante)
    elif re.fullmatch(r"detalles/d[0-9]{6}_f[0-9]+_[0-9a-f]{6}_capas\.json", rel):
        ctype = "application/json; charset=utf-8"   # vectores/leyendas HD
    else:
        return JSONResponse({"error": "nombre invalido"}, status_code=400)
    return _archivo(SALIDAS / sello / rel, ctype, cache=(rel != "mapa_repro.json"))
