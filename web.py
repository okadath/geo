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
RE_ARCHIVO = r"mapa(?:_placas|_manto|_final)?\.(?:gif|png)"

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
    "deriva":      (1.0, 10.0, float, 6.0),
}
ALGORITMO = ("velocidad", "mar", "continentes", "plumas",
             "erosion", "empuje", "momento", "rigidez", "deriva")

jobs = {}
procs = {}
lock = threading.Lock()


def limpiar(datos):
    """Valida y acota los parametros recibidos; ignora todo lo demas."""
    p = {}
    for k, (lo, hi, tipo, defecto) in PARAMS.items():
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


def _corrida(sello, extra=None):
    """Descriptor de una corrida: sello, parametros y URLs de las imagenes
    que existan en su carpeta."""
    carpeta = SALIDAS / sello
    item = {"sello": sello}
    try:
        meta = json.loads((carpeta / "params.json").read_text())
        item["creado"] = meta.get("creado")
        item["params"] = meta.get("params", {})
    except (OSError, ValueError):
        item["params"] = {}
    for clave, fich in (("mapa", "mapa.gif"), ("placas", "mapa_placas.gif"),
                        ("manto", "mapa_manto.gif"), ("png", "mapa_final.png")):
        if (carpeta / fich).exists():
            item[clave] = f"/salidas/{sello}/{fich}"
    if extra:
        item.update(extra)
    return item


def correr(job_id, p, sello):
    carpeta = SALIDAS / sello
    carpeta.mkdir(parents=True, exist_ok=True)   # por si se borro entre tanto
    cmd = [sys.executable, "-u", str(BASE / "tecto.py"),
           "-t", str(p["tiempo"]), "-c", str(p["cada"]), "--ms", str(p["ms"]),
           "-s", str(p["semilla"]), "-r", str(p["resolucion"]),
           "-d", str(p["detalle"]), "-o", str(carpeta / "mapa")]
    for k in ALGORITMO:
        cmd += [f"--{k}", str(p[k])]
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
        # persistir los parametros junto a las imagenes: asi la corrida
        # aparece en el historial y se puede recargar exacta
        (carpeta / "params.json").write_text(json.dumps(
            {"sello": sello, "creado": datetime.now().isoformat(timespec="seconds"),
             "params": p}, indent=2, ensure_ascii=False))
    else:
        # corrida fallida o cancelada: no dejar carpetas vacias en el historial
        shutil.rmtree(carpeta, ignore_errors=True)
    with lock:
        estado = "cancelado" if cancelado else ("listo" if ok else "error")
        datos = _corrida(sello) if estado == "listo" else {"sello": sello}
        jobs[job_id].update(estado=estado, progreso=1.0, log="\n".join(cola),
                            **datos)


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
        self.end_headers()
        self.wfile.write(cuerpo)

    def _archivo(self, ruta, ctype):
        try:
            datos = ruta.read_bytes()
        except OSError:
            return self._json({"error": "no existe"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(datos)))
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
            return self._archivo(BASE / "web.html", "text/html; charset=utf-8")
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
            # solo carpetas con sello de tiempo y los archivos que genera tecto
            m = re.fullmatch(rf"({RE_SELLO})/({RE_ARCHIVO})", resto)
            if not m:
                return self._json({"error": "nombre invalido"}, 400)
            ctype = "image/gif" if resto.endswith(".gif") else "image/png"
            return self._archivo(SALIDAS / m.group(1) / m.group(2), ctype)
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
                                "manto": None, "png": None}
            threading.Thread(target=correr, args=(job_id, p, sello),
                             daemon=True).start()
            return self._json({"id": job_id, "params": p, "sello": sello})
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
