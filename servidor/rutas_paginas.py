"""Rutas de paginas HTML y estaticos: mismas rutas y validaciones que el viejo
web.py (allowlists estrictas, regexes, sin traversal). Todo `def` normal
(threadpool de FastAPI): leer archivos del disco es bloqueante.
"""
import html
import os
import re
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import correo, mundos
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


# --- paginas nuevas (ESPECIFICACION_RUTAS.md, tabla de rutas) ---
# Mientras un HTML de destino no exista (T08-T10 los crean) se sirve
# frontend/_pendiente.html para que la ruta responda 200.
PENDIENTE = FRONTEND / "_pendiente.html"
RE_XY = r"[0-9]+,[0-9]+"
OG_MARCADORES = ("og_titulo", "og_imagen", "og_descripcion", "og_url")


def _pagina(nombre):
    ruta = FRONTEND / nombre
    return _html(ruta if ruta.is_file() else PENDIENTE)


def _sello_invalido(sello):
    return not re.fullmatch(RE_SELLO, sello)


def _no_existe():
    return JSONResponse({"error": "no existe"}, status_code=404)


def _con_d(ruta, d):
    """`ruta` con `?d=<d>` si llega d (url-encoded); sin query si no."""
    return f"{ruta}?{urlencode({'d': d})}" if d else ruta


def _og(sello, d, request=None):
    """Valores OG de la ficha (sin escapar). Mundo inexistente -> vacios."""
    m = mundos.mundo(sello, d)
    if m is None:
        return dict.fromkeys(OG_MARCADORES, "")
    base = correo.base_url(request)
    meta = m.get("meta") or {}
    partes = []
    if meta.get("semilla") is not None:
        partes.append(f"Semilla {meta['semilla']}")
    if meta.get("continentes") is not None:
        partes.append(f"{meta['continentes']} continentes")
    if meta.get("paises"):
        partes.append(f"{meta['paises']} países")
    desc = "Mundo generado en Mundaria"
    if partes:
        desc += ": " + " · ".join(partes)
    return {
        "og_titulo": m["nombre"],
        "og_imagen": base + m["imagen"],
        "og_descripcion": desc,
        # d solo si es el detalle resuelto (no reflejar basura de la query)
        "og_url": base + _con_d(f"/w/{sello}", d if d == m["d"] else None),
    }


@router.get("/")
def explorar():
    return _pagina("explorar.html")


@router.get("/nuevo")
def nuevo():
    return _pagina("nuevo.html")


@router.get("/yo")
def yo():
    return _pagina("yo.html")


# ficha compartible: la unica pagina con plantillado en servidor (metas OG,
# porque los bots de vista previa no ejecutan JS). Mundo inexistente -> ficha
# con marcadores vacios (el front muestra el error), no 404.
@router.get("/w/{sello}")
def ficha(request: Request, sello: str, d: str | None = None):
    if _sello_invalido(sello):
        return _no_existe()
    ruta = FRONTEND / "ficha.html"
    try:
        texto = (ruta if ruta.is_file() else PENDIENTE).read_text(encoding="utf-8")
    except OSError:
        return _no_existe()
    for clave, valor in _og(sello, d, request).items():
        texto = texto.replace("{{%s}}" % clave, html.escape(valor, quote=True))
    return Response(content=texto, media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


# literales (detail, mapa, jugar) antes del patron <x>,<y>
@router.get("/w/{sello}/detail")
def detail(sello: str):
    if _sello_invalido(sello):
        return _no_existe()
    return _pagina("mapa.html")


# ruta anterior del visor: 302 a /detail conservando la query
@router.get("/w/{sello}/mapa")
def mapa(request: Request, sello: str):
    if _sello_invalido(sello):
        return _no_existe()
    return RedirectResponse(_con_d(f"/w/{sello}/detail", request.query_params.get("d")),
                            status_code=302)


# juego de conquista por turnos: el juego.html de la raiz, sin cambios
@router.get("/w/{sello}/jugar")
def jugar(sello: str):
    if _sello_invalido(sello):
        return _no_existe()
    return _html(BASE / "juego.html")


@router.get("/w/{sello}/{xy}")
def battlemap(sello: str, xy: str):
    if _sello_invalido(sello) or not re.fullmatch(RE_XY, xy):
        return _no_existe()
    return _pagina("battlemap.html")


# --- redirecciones de rutas viejas (302, conservando d) ---
def _vieja(request, sufijo=""):
    """302 a /w/<sello><sufijo>?d= ; sin sello valido -> /."""
    q = request.query_params
    sello = q.get("sello") or ""
    if _sello_invalido(sello):
        return RedirectResponse("/", status_code=302)
    return RedirectResponse(_con_d(f"/w/{sello}{sufijo}", q.get("d")),
                            status_code=302)


@router.get("/estudio")
def estudio():
    return RedirectResponse("/", status_code=302)


@router.get("/estudio/mundo")
def estudio_mundo(request: Request):
    sufijo = {"battlemap": "/detail", "conquistar": "/jugar"}.get(
        request.query_params.get("modo"), "")
    return _vieja(request, sufijo)


@router.get("/fantasia")
def fantasia(request: Request):
    return _vieja(request, "/detail")


@router.get("/batalla")
def batalla(request: Request):
    return _vieja(request, "/detail")


@router.get("/juego")
def juego(request: Request):
    return _vieja(request, "/jugar")


@router.get("/cuenta")
def cuenta():
    return RedirectResponse("/yo", status_code=302)


# solo /entrar exacto: /entrar/<token> es de rutas_cuentas (enlace magico)
@router.get("/entrar")
def entrar():
    return RedirectResponse("/yo", status_code=302)


@router.get("/pro")
def pro():
    return RedirectResponse("/yo#pro", status_code=302)


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
