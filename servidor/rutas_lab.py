"""API del laboratorio: listado/estado de corridas y disparo de jobs.

Mismo shape JSON exacto que el viejo web.py. Los endpoints POST arrancan hilos
daemon (igual que antes) y devuelven de inmediato; el front hace polling a
/api/estado. Todo `def` normal: el cuerpo es bloqueante (lee params.json,
lanza hilos) y FastAPI lo corre en su threadpool.
"""
import json
import re
import shutil
import threading
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .config import BASE, DETALLE, RE_SELLO, SALIDAS
from .corridas import (cargar_corridas, correr, correr_detalle,
                       correr_extrapolacion, jobs, limpiar, lock, nuevo_sello,
                       procs)
from .rutas_cuentas import resolver_plan, identidad
from .limites import permitir_render, incrementar

router = APIRouter()

# lista de corridas publicas (visibles para free/anonimo). Si el archivo NO
# existe -> todas publicas (modo desarrollo).
PUBLICOS = BASE / "publicos.json"


def _sellos_publicos():
    """Conjunto de sellos publicos, o None si no hay lista (todo publico)."""
    if not PUBLICOS.exists():
        return None
    try:
        datos = json.loads(PUBLICOS.read_text())
    except (OSError, ValueError):
        return None
    if isinstance(datos, dict):
        datos = datos.get("publicos", [])
    if not isinstance(datos, list):
        return set()
    return {str(s) for s in datos}


def _requiere_pro(request: Request):
    """Gate de generacion: (usuario, plan, ident) si tiene plan de pago, o una
    JSONResponse 403 si es free/anonimo."""
    usuario, plan = resolver_plan(request)
    if plan == "free":
        return None, JSONResponse({"error": "requiere plan Pro", "plan": "free"},
                                  status_code=403)
    return (usuario, plan, identidad(request, usuario)), None


async def _cuerpo(request: Request):
    """Lee el cuerpo JSON de la peticion; {} si no hay o esta mal formado
    (replica del viejo _cuerpo)."""
    crudo = await request.body()
    if not crudo:
        return {}
    try:
        return json.loads(crudo)
    except ValueError:
        return {}


@router.get("/api/corridas")
def api_corridas(request: Request):
    corridas = cargar_corridas()
    _usuario, plan = resolver_plan(request)
    # pro/comercial ven todo; free/anonimo solo las corridas publicas
    if plan == "free":
        pub = _sellos_publicos()
        if pub is not None:
            corridas = [c for c in corridas if c.get("sello") in pub]
    return corridas


@router.get("/api/estado")
def api_estado(request: Request):
    job_id = request.query_params.get("id", "")
    with lock:
        job = dict(jobs.get(job_id) or {})
    if not job:
        return JSONResponse({"error": "trabajo desconocido"}, status_code=404)
    return job


@router.post("/api/generar")
async def api_generar(request: Request):
    ctx, err = _requiere_pro(request)
    if err:
        return err
    _usuario, plan, ident = ctx
    ok, motivo = permitir_render(ident, plan)
    if not ok:
        return JSONResponse(
            {"error": "limite de renders alcanzado", "detalle": motivo},
            status_code=429)
    datos = await _cuerpo(request)
    p = limpiar(datos)
    incrementar(ident)
    job_id = uuid.uuid4().hex[:8]
    with lock:
        sello = nuevo_sello()
        jobs[job_id] = {"estado": "corriendo", "progreso": 0.0, "params": p,
                        "sello": sello, "mapa": None, "placas": None,
                        "manto": None, "clima": None, "png": None}
    threading.Thread(target=correr, args=(job_id, p, sello),
                     daemon=True).start()
    return {"id": job_id, "params": p, "sello": sello}


@router.post("/api/extrapolar")
async def api_extrapolar(request: Request):
    _ctx, err = _requiere_pro(request)
    if err:
        return err
    datos = await _cuerpo(request)
    origen = str(datos.get("sello", ""))
    paso = int(datos.get("paso", 0))
    pasos = max(1, int(datos.get("pasos", 400)))
    if not re.fullmatch(RE_SELLO, origen) or \
       not (SALIDAS / origen / "mapa_mundo" / "frames").is_dir():
        return JSONResponse({"error": "origen no extrapolable"}, status_code=400)
    job_id = uuid.uuid4().hex[:8]
    with lock:
        sello = nuevo_sello()
        jobs[job_id] = {"estado": "corriendo", "progreso": 0.0,
                        "params": {}, "sello": sello, "mapa": None}
    threading.Thread(target=correr_extrapolacion,
                     args=(job_id, origen, paso, pasos, sello),
                     daemon=True).start()
    return {"id": job_id, "sello": sello}


@router.post("/api/detallar")
async def api_detallar(request: Request):
    ctx, err = _requiere_pro(request)
    if err:
        return err
    _usuario, plan, ident = ctx
    ok, motivo = permitir_render(ident, plan)
    if not ok:
        return JSONResponse(
            {"error": "limite de renders alcanzado", "detalle": motivo},
            status_code=429)
    datos = await _cuerpo(request)
    origen = str(datos.get("sello", ""))
    try:
        paso = max(0, int(datos.get("paso", 0)))
    except (TypeError, ValueError):
        paso = 0
    if not re.fullmatch(RE_SELLO, origen) or \
       not (SALIDAS / origen / "mapa_mundo" / "frames").is_dir():
        return JSONResponse(
            {"error": "la corrida no tiene mundo de checkpoints"}, status_code=400)
    pd = limpiar(datos, DETALLE)
    # tope de pixeles del PNG gigante: resolucion*factor <= 4096
    try:
        res = int(json.loads((SALIDAS / origen / "params.json")
                             .read_text())["params"].get("resolucion", 256))
    except (OSError, ValueError, KeyError, TypeError):
        res = 256
    pd["factor"] = max(2, min(pd["factor"], max(2, 4096 // max(res, 64))))
    job_id = uuid.uuid4().hex[:8]
    with lock:
        jobs[job_id] = {"estado": "corriendo", "progreso": 0.0,
                        "sello": origen, "detalle": None}
    incrementar(ident)
    threading.Thread(target=correr_detalle,
                     args=(job_id, origen, paso, pd),
                     daemon=True).start()
    return {"id": job_id, "params": pd}


@router.post("/api/cancelar")
async def api_cancelar(request: Request):
    datos = await _cuerpo(request)
    job_id = str(datos.get("id", ""))
    with lock:
        job = jobs.get(job_id)
        proc = procs.get(job_id)
        if job and job["estado"] == "corriendo":
            job["cancelado"] = True
    if proc:
        proc.terminate()
    return {"ok": proc is not None}


@router.post("/api/corridas/borrar")
async def api_borrar(request: Request):
    datos = await _cuerpo(request)
    sello = str(datos.get("sello", ""))
    if re.fullmatch(RE_SELLO, sello):
        shutil.rmtree(SALIDAS / sello, ignore_errors=True)
    return cargar_corridas()
