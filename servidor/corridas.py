"""Logica de corridas movida del viejo web.py sin cambios de comportamiento.

Aqui viven: la validacion de parametros (limpiar), la creacion de carpetas
con sello (nuevo_sello), los descriptores de corrida/detalles, el lanzador de
tecto.py (_ejecutar) y las tres formas de correrlo (correr, correr_extrapolacion,
correr_detalle), mas el listado de corridas (cargar_corridas). El estado de los
jobs vive en `jobs`/`procs` protegido por `lock`, igual que antes.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
from datetime import datetime

from .config import (ALGORITMO, BASE, DETALLE, PARAMS, RE_SELLO, SALIDAS)

jobs = {}
procs = {}
lock = threading.Lock()


def limpiar(datos, spec=PARAMS):
    """Valida y acota los parametros recibidos; ignora todo lo demas."""
    p = {}
    for k, (lo, hi, tipo, defecto) in spec.items():
        try:
            v = tipo(datos.get(k, defecto))
        except (TypeError, ValueError):
            v = defecto
        p[k] = min(max(v, lo), hi)
    return p


def nuevo_sello():
    """Sello de tiempo unico para la carpeta de una corrida (crea el dir).

    Se llama con el lock tomado para que dos peticiones simultaneas no
    reclamen la misma carpeta.
    """
    SALIDAS.mkdir(exist_ok=True)
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    sello, n = base, 2
    while (SALIDAS / sello).exists():
        sello = f"{base}-{n}"
        n += 1
    (SALIDAS / sello).mkdir()
    return sello


def _detalles(sello):
    """Cuadros detallados de una corrida (PNG gigantes de un solo frame con
    geografia menor por ruido), con los metadatos de su .json hermano."""
    lista = []
    for fj in sorted((SALIDAS / sello / "detalles").glob("d*.json")):
        if fj.stem.endswith("_capas"):   # capas.json de un detalle HD, no un detalle
            continue
        try:
            meta = json.loads(fj.read_text())
        except (OSError, ValueError):
            continue
        meta["png"] = f"/salidas/{sello}/detalles/{fj.stem}.png"
        clima_png = SALIDAS / sello / "detalles" / f"{fj.stem}_clima.png"
        if clima_png.exists():
            meta["clima"] = f"/salidas/{sello}/detalles/{fj.stem}_clima.png"
        # artefactos de "clima HD" (aditivos): se exponen solo si existen, de
        # modo que los detalles viejos siguen mostrandose como antes
        for clave, suf in (("climahd", "_climahd.png"), ("koppen", "_koppen.png"),
                           ("cuencas", "_cuencas.png"), ("paises", "_paises.png"),
                           ("civ", "_civ.png"), ("regiones", "_regiones.png"),
                           ("datos", "_datos.png"),
                           ("datos2", "_datos2.png"), ("capas", "_capas.json")):
            if (SALIDAS / sello / "detalles" / f"{fj.stem}{suf}").exists():
                meta[clave] = f"/salidas/{sello}/detalles/{fj.stem}{suf}"
        lista.append(meta)
    # ordenar por timestamp de creacion, el mas reciente primero; los que no
    # traigan `creado` (detalles viejos) quedan al final
    lista.sort(key=lambda m: m.get("creado") or "", reverse=True)
    return lista


def _corrida(sello, extra=None):
    """Descriptor de una corrida: sello, parametros y URLs de las imagenes
    que existan en su carpeta."""
    carpeta = SALIDAS / sello
    item = {"sello": sello}
    try:
        meta = json.loads((carpeta / "params.json").read_text())
        item["creado"] = meta.get("creado")
        item["params"] = meta.get("params", {})
        if "rama_de" in meta:
            item["rama_de"] = meta["rama_de"]     # corrida hija de una extrapolacion
    except (OSError, ValueError):
        item["params"] = {}
    for clave, fich in (("mapa", "mapa.gif"), ("placas", "mapa_placas.gif"),
                        ("manto", "mapa_manto.gif"), ("clima", "mapa_clima.gif"),
                        ("png", "mapa_final.png"),
                        ("repro", "mapa_repro.json")):
        if (carpeta / fich).exists():
            item[clave] = f"/salidas/{sello}/{fich}"
    # ¿tiene mundo de checkpoints? -> se puede extrapolar desde sus cuadros
    item["extrapolable"] = (carpeta / "mapa_mundo" / "frames").is_dir()
    item["detalles"] = _detalles(sello)
    if extra:
        item.update(extra)
    return item


def _ejecutar(job_id, cmd, carpeta, sello, meta_json):
    """Lanza tecto.py, sigue el progreso (lineas 'paso N/M'), y al terminar
    persiste meta_json (params.json) si fue exitoso o borra la carpeta si no.
    Compartido por la generacion normal y por la extrapolacion (rama)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    with lock:
        procs[job_id] = proc
    cola = []
    for linea in proc.stdout:
        cola = (cola + [linea.rstrip()])[-6:]
        m = re.search(r"paso (\d+)/(\d+)", linea)
        if m:
            with lock:
                jobs[job_id]["progreso"] = int(m.group(1)) / int(m.group(2))
    ok = proc.wait() == 0 and (carpeta / "mapa.gif").exists()
    with lock:
        procs.pop(job_id, None)
        cancelado = jobs[job_id].get("cancelado")
    if ok and not cancelado:
        # persistir metadatos junto a las imagenes: la corrida entra al
        # historial y se puede recargar (o volver a extrapolar) exacta
        (carpeta / "params.json").write_text(
            json.dumps(meta_json, indent=2, ensure_ascii=False))
    else:
        # corrida fallida o cancelada: no dejar carpetas vacias en el historial
        shutil.rmtree(carpeta, ignore_errors=True)
    with lock:
        estado = "cancelado" if cancelado else ("listo" if ok else "error")
        datos = _corrida(sello) if estado == "listo" else {"sello": sello}
        jobs[job_id].update(estado=estado, progreso=1.0, log="\n".join(cola),
                            **datos)


def correr(job_id, p, sello):
    carpeta = SALIDAS / sello
    carpeta.mkdir(parents=True, exist_ok=True)   # por si se borro entre tanto
    # --reproductor: cuadros PNG por frame + repro.json (timeline) + mundo de
    # checkpoints, para el reproductor web (adelante/reversa/pausa) y extrapolar
    cmd = [sys.executable, "-u", str(BASE / "tecto.py"),
           "-t", str(p["tiempo"]), "-c", str(p["cada"]), "--ms", str(p["ms"]),
           # -r = ALTO del mapa; tecto genera 2:1 (ancho = 2*alto). El API sigue
           # guardando el escalar en params.json (es el alto).
           "-s", str(p["semilla"]), "-r", str(p["resolucion"]),
           "-d", str(p["detalle"]), "--reproductor",
           "-o", str(carpeta / "mapa")]
    for k in ALGORITMO:
        cmd += [f"--{k}", str(p[k])]
    meta = {"sello": sello, "creado": datetime.now().isoformat(timespec="seconds"),
            "params": p}
    _ejecutar(job_id, cmd, carpeta, sello, meta)


def correr_extrapolacion(job_id, origen, paso, pasos, sello):
    """Rama NO destructiva: extrapola `pasos` desde el cuadro `paso` del mundo de
    checkpoints de la corrida `origen`, hacia una corrida nueva `sello`."""
    carpeta = SALIDAS / sello
    carpeta.mkdir(parents=True, exist_ok=True)
    try:
        src = json.loads((SALIDAS / origen / "params.json").read_text())["params"]
    except (OSError, ValueError):
        src = {}
    cada = int(src.get("cada", 8))
    cmd = [sys.executable, "-u", str(BASE / "tecto.py"),
           "--extrapolar", str(SALIDAS / origen / "mapa_mundo"),
           "--desde-paso", str(int(paso)), "-t", str(int(pasos)),
           "-c", str(cada), "--cada-estado", "10", "--ms", str(src.get("ms", 60)),
           "-d", str(src.get("detalle", 0.6)), "-o", str(carpeta / "mapa")]
    params = dict(src); params["tiempo"] = int(pasos)
    meta = {"sello": sello, "creado": datetime.now().isoformat(timespec="seconds"),
            "params": params, "rama_de": {"sello": origen, "paso": int(paso)}}
    _ejecutar(job_id, cmd, carpeta, sello, meta)


def correr_detalle(job_id, origen, paso, pd):
    """Detalla UN cuadro de la corrida `origen`: PNG gigante (factor x la
    resolucion) con geografia menor por ruido, guardado en detalles/ dentro de
    la corrida. Genera DOS PNG con el mismo stem: el de relieve `{nombre}.png` y
    el de clima `{nombre}_clima.png` (biomas, rios, corrientes, hielo). No toca
    el mundo de checkpoints ni la evolucion original; el nombre lleva la firma
    de los diales, asi que repetir con los mismos valores sobrescribe los
    mismos archivos (es determinista)."""
    carpeta = SALIDAS / origen / "detalles"
    carpeta.mkdir(parents=True, exist_ok=True)
    firma = hashlib.md5(json.dumps([paso, pd], sort_keys=True).encode()).hexdigest()[:6]
    nombre = f"d{paso:06d}_f{pd['factor']}_{firma}"
    cmd = [sys.executable, "-u", str(BASE / "tecto.py"),
           "--detallar", str(SALIDAS / origen / "mapa_mundo"),
           "--desde-paso", str(int(paso)), "--factor", str(pd["factor"]),
           "--semilla-detalle", str(pd["semilla"]),
           "--casquetes", str(pd["casquetes"]), "--relieve", str(pd["relieve"]),
           "--sinuosidad", str(pd["sinuosidad"]),
           "--temperatura", str(pd["temperatura"]),
           "--precipitaciones", str(pd["precipitaciones"]),
           "--semilla-civ", str(pd["semilla_civ"]),
           "--asentamientos", str(pd["asentamientos"]),
           "--paises", str(pd["paises"]),
           "--tam-paises", str(pd["tam_paises"]),
           "-o", str(carpeta / nombre)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    with lock:
        procs[job_id] = proc
    cola = []
    for linea in proc.stdout:
        cola = (cola + [linea.rstrip()])[-6:]
        m = re.search(r"paso (\d+)/(\d+)", linea)
        if m and int(m.group(2)):
            with lock:
                jobs[job_id]["progreso"] = int(m.group(1)) / int(m.group(2))
    ok = proc.wait() == 0 and (carpeta / f"{nombre}.png").exists()
    if not ok:   # no dejar un detalle a medias en la lista
        for ext in (".png", ".json"):
            (carpeta / f"{nombre}{ext}").unlink(missing_ok=True)
        for suf in ("_clima.png", "_climahd.png", "_koppen.png",
                    "_cuencas.png", "_paises.png", "_civ.png", "_regiones.png",
                    "_datos.png", "_datos2.png", "_capas.json"):
            (carpeta / f"{nombre}{suf}").unlink(missing_ok=True)
    with lock:
        procs.pop(job_id, None)
        cancelado = jobs[job_id].get("cancelado")
        estado = "cancelado" if cancelado else ("listo" if ok else "error")
        jobs[job_id].update(
            estado=estado, progreso=1.0, log="\n".join(cola),
            detalle=f"/salidas/{origen}/detalles/{nombre}.png" if ok else None,
            detalles=_detalles(origen))


def cargar_corridas():
    """Lista las corridas guardadas (carpetas con sello de tiempo), de la
    mas reciente a la mas antigua."""
    if not SALIDAS.exists():
        return []
    sellos = sorted((d.name for d in SALIDAS.iterdir()
                     if d.is_dir() and re.fullmatch(RE_SELLO, d.name)),
                    reverse=True)
    return [_corrida(s) for s in sellos if (SALIDAS / s / "params.json").exists()]
