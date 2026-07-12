"""Interfaz web local para tecto.py.

Levanta un servidor en http://127.0.0.1:8000 con sliders para los
parametros principales y genera GIFs llamando al CLI (tecto.py) como
subproceso. Cada corrida se guarda en su propia carpeta con sello de
tiempo (salidas/AAAAMMDD-HHMMSS/) junto con sus parametros, de modo que
el panel «Corridas guardadas» lista el historial y «Cargar» reabre las
imagenes de una corrida anterior.

Uso:  python3 web.py [-p PUERTO]

Solo biblioteca estandar. Los resultados van a salidas/ (fuera de git).
El servidor escucha solo en 127.0.0.1.
"""
import argparse
import hashlib
import importlib
import json
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
SALIDAS = BASE / "salidas"

# nombre de carpeta de una corrida: sello de tiempo, con sufijo -N si dos
# corridas arrancan en el mismo segundo
RE_SELLO = r"[0-9]{8}-[0-9]{6}(?:-[0-9]+)?"
RE_ARCHIVO = r"mapa(?:_placas|_manto|_clima|_final)?\.(?:gif|png)"

# parametro: (minimo, maximo, tipo, valor por defecto) — todo lo que llega
# del navegador se acota a estos rangos antes de tocar la linea de comandos
PARAMS = {
    "tiempo":      (50, 6000, int, 800),
    "cada":        (1, 50, int, 8),
    "ms":          (20, 300, int, 60),
    "semilla":     (0, 2**31 - 1, int, 7),
    "resolucion":  (64, 512, int, 256),
    "detalle":     (0.0, 1.5, float, 0.6),
    # diales del algoritmo (flags largos de tecto.py con el mismo nombre)
    "velocidad":   (2.0, 40.0, float, 18.0),
    "mar":         (0.35, 0.70, float, 0.52),
    "continentes": (0.10, 1.20, float, 0.55),
    "plumas":      (10, 300, int, 70),
    "erosion":     (0.0, 0.03, float, 0.008),
    "empuje":      (0.0, 0.6, float, 0.15),
    "momento":     (0.005, 0.2, float, 0.02),
    "rigidez":     (0.0, 1.0, float, 0.85),
    "deriva":      (1.0, 10.0, float, 8.0),
    "anos_paso":   (0.1, 10.0, float, 1.0),
}
ALGORITMO = ("velocidad", "mar", "continentes", "plumas",
             "erosion", "empuje", "momento", "rigidez", "deriva", "anos_paso")

# diales del detallado de UN cuadro (tecto.py --detallar): mismos rangos que
# el CLI; el factor ademas se acota para que resolucion*factor <= 4096 px. Los
# diales de clima (temperatura/precipitaciones) viven aqui: se eligen al detallar un
# cuadro y sobreescriben los del mundo, sin tocar la generacion
DETALLE = {
    "factor":      (2, 16, int, 8),
    "semilla":     (0, 2**31 - 1, int, 0),
    "casquetes":   (0.0, 0.45, float, 0.18),
    "relieve":     (0.2, 3.0, float, 1.2),
    "sinuosidad":  (0.0, 3.0, float, 1.0),
    "temperatura": (-1.0, 1.0, float, 0.0),
    "precipitaciones": (0.2, 2.0, float, 1.0),
    # diales de civilizacion (0 = automatico): ver civ.py
    "semilla_civ":   (0, 2**31 - 1, int, 0),
    "asentamientos": (0, 200, int, 0),
    "paises":        (0, 48, int, 0),
    # tamano de los paises: 0 auto, 1 grandes (imperios), 2 chicos (reinos)
    "tam_paises":    (0, 2, int, 0),
}

jobs = {}
procs = {}
lock = threading.Lock()

# modulos de backend enchufables (motor del juego, renders del lado servidor):
# cada uno expone manejar_get(handler, url) -> bool y
# manejar_post(handler, ruta, datos) -> bool; True = peticion atendida.
# La logica propietaria (motor, calculos, generacion) vive en estos modulos,
# NO en el navegador.
MODULOS = []
for _nombre in ("juego_srv", "fantasia_srv", "batalla_srv"):
    try:
        MODULOS.append(importlib.import_module(_nombre))
    except ImportError:
        pass


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


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *args):   # silenciar el log por peticion
        pass

    def _json(self, obj, codigo=200):
        cuerpo = json.dumps(obj).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _archivo(self, ruta, ctype, cache=True):
        try:
            datos = ruta.read_bytes()
        except OSError:
            return self._json({"error": "no existe"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(datos)))
        if not cache:   # la pagina y el timeline cambian entre corridas
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def _bytes(self, datos, ctype="image/png", cache=False):
        """Respuesta binaria en memoria (PNG renderizados por los modulos)."""
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(datos)))
        if not cache:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def _cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n)) if n else {}
        except ValueError:
            return {}

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            return self._archivo(BASE / "web.html", "text/html; charset=utf-8",
                                 cache=False)
        # pagina de subregiones: mapa interactivo con seleccion de provincias y
        # cuencas marinas de UN detalle (query: ?sello=...&d=<stem del detalle>)
        if url.path == "/regiones":
            return self._archivo(BASE / "regiones.html",
                                 "text/html; charset=utf-8", cache=False)
        # juego de conquista por turnos (estilo Age of History) sobre las
        # provincias de UN detalle (misma query que /regiones)
        if url.path == "/juego":
            return self._archivo(BASE / "juego.html",
                                 "text/html; charset=utf-8", cache=False)
        # mapa de fantasia: render estilizado (pergamino) de UN detalle
        # (misma query que /regiones)
        if url.path == "/fantasia":
            return self._archivo(BASE / "fantasia.html",
                                 "text/html; charset=utf-8", cache=False)
        # generador de battlemaps: escenas de encuentro 20x20 desde un punto
        # del detalle (misma query que /regiones)
        if url.path == "/batalla":
            return self._archivo(BASE / "batalla.html",
                                 "text/html; charset=utf-8", cache=False)
        # modulo del detallado: allowlist estricta (sin traversal), solo estos
        # dos archivos; sin cache, igual que la pagina, para ver los cambios al
        # recargar
        if url.path in ("/detallar/detallar.js", "/detallar/detallar.css"):
            nombre = url.path.rsplit("/", 1)[1]
            ctype = ("application/javascript; charset=utf-8"
                     if nombre.endswith(".js") else "text/css; charset=utf-8")
            return self._archivo(BASE / "detallar" / nombre, ctype, cache=False)
        if url.path == "/api/corridas":
            return self._json(cargar_corridas())
        if url.path == "/api/estado":
            job_id = parse_qs(url.query).get("id", [""])[0]
            with lock:
                job = dict(jobs.get(job_id) or {})
            if not job:
                return self._json({"error": "trabajo desconocido"}, 404)
            return self._json(job)
        if url.path.startswith("/salidas/"):
            resto = url.path[len("/salidas/"):]
            barra = resto.find("/")
            if barra < 0 or not re.fullmatch(RE_SELLO, resto[:barra]):
                return self._json({"error": "nombre invalido"}, 400)
            sello, rel = resto[:barra], resto[barra + 1:]
            # rutas permitidas (regex estricta -> sin traversal): los GIF/PNG
            # finales, el JSON del reproductor y los cuadros PNG por frame
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
                return self._json({"error": "nombre invalido"}, 400)
            return self._archivo(SALIDAS / sello / rel, ctype,
                                 cache=(rel != "mapa_repro.json"))
        for mod in MODULOS:
            if mod.manejar_get(self, url):
                return
        return self._json({"error": "no existe"}, 404)

    def do_POST(self):
        datos = self._cuerpo()
        if self.path == "/api/generar":
            p = limpiar(datos)
            job_id = uuid.uuid4().hex[:8]
            with lock:
                sello = nuevo_sello()
                jobs[job_id] = {"estado": "corriendo", "progreso": 0.0, "params": p,
                                "sello": sello, "mapa": None, "placas": None,
                                "manto": None, "clima": None, "png": None}
            threading.Thread(target=correr, args=(job_id, p, sello),
                             daemon=True).start()
            return self._json({"id": job_id, "params": p, "sello": sello})
        if self.path == "/api/extrapolar":
            origen = str(datos.get("sello", ""))
            paso = int(datos.get("paso", 0))
            pasos = max(1, int(datos.get("pasos", 400)))
            if not re.fullmatch(RE_SELLO, origen) or \
               not (SALIDAS / origen / "mapa_mundo" / "frames").is_dir():
                return self._json({"error": "origen no extrapolable"}, 400)
            job_id = uuid.uuid4().hex[:8]
            with lock:
                sello = nuevo_sello()
                jobs[job_id] = {"estado": "corriendo", "progreso": 0.0,
                                "params": {}, "sello": sello, "mapa": None}
            threading.Thread(target=correr_extrapolacion,
                             args=(job_id, origen, paso, pasos, sello),
                             daemon=True).start()
            return self._json({"id": job_id, "sello": sello})
        if self.path == "/api/detallar":
            origen = str(datos.get("sello", ""))
            try:
                paso = max(0, int(datos.get("paso", 0)))
            except (TypeError, ValueError):
                paso = 0
            if not re.fullmatch(RE_SELLO, origen) or \
               not (SALIDAS / origen / "mapa_mundo" / "frames").is_dir():
                return self._json({"error": "la corrida no tiene mundo de "
                                            "checkpoints"}, 400)
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
            threading.Thread(target=correr_detalle,
                             args=(job_id, origen, paso, pd),
                             daemon=True).start()
            return self._json({"id": job_id, "params": pd})
        if self.path == "/api/cancelar":
            job_id = str(datos.get("id", ""))
            with lock:
                job = jobs.get(job_id)
                proc = procs.get(job_id)
                if job and job["estado"] == "corriendo":
                    job["cancelado"] = True
            if proc:
                proc.terminate()
            return self._json({"ok": proc is not None})
        if self.path == "/api/corridas/borrar":
            sello = str(datos.get("sello", ""))
            if re.fullmatch(RE_SELLO, sello):
                shutil.rmtree(SALIDAS / sello, ignore_errors=True)
            return self._json(cargar_corridas())
        for mod in MODULOS:
            if mod.manejar_post(self, self.path, datos):
                return
        return self._json({"error": "no existe"}, 404)


def main():
    p = argparse.ArgumentParser(description="Interfaz web local de tecto.py")
    p.add_argument("-p", "--puerto", type=int, default=8000)
    args = p.parse_args()
    SALIDAS.mkdir(exist_ok=True)
    servidor = ThreadingHTTPServer(("127.0.0.1", args.puerto), Manejador)
    print(f"tecto web -> http://127.0.0.1:{args.puerto}  (Ctrl+C para salir)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
