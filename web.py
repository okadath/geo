"""Interfaz web local para tecto.py.

Levanta un servidor en http://127.0.0.1:8000 con sliders para los
parametros principales, genera GIFs llamando al CLI (tecto.py) como
subproceso, y permite guardar mundos (semilla + parametros) en
semillas.json para repetir una simulacion exacta.

Uso:  python3 web.py [-p PUERTO]

Solo biblioteca estandar. Los resultados van a salidas/ y los mundos
guardados a semillas.json (ambos fuera de git). El servidor escucha solo
en 127.0.0.1.
"""
import argparse
import json
import re
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
SALIDAS = BASE / "salidas"
SEMILLAS = BASE / "semillas.json"

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
}
ALGORITMO = ("velocidad", "mar", "continentes", "plumas",
             "erosion", "empuje", "momento", "rigidez")

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


def correr(job_id, p):
    SALIDAS.mkdir(exist_ok=True)   # por si se borro con el servidor corriendo
    cmd = [sys.executable, "-u", str(BASE / "tecto.py"),
           "-t", str(p["tiempo"]), "-c", str(p["cada"]), "--ms", str(p["ms"]),
           "-s", str(p["semilla"]), "-r", str(p["resolucion"]),
           "-d", str(p["detalle"]), "-o", str(SALIDAS / job_id)]
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
    ok = proc.wait() == 0 and (SALIDAS / f"{job_id}.gif").exists()
    png = SALIDAS / f"{job_id}_final.png"
    placas = SALIDAS / f"{job_id}_placas.gif"
    with lock:
        procs.pop(job_id, None)
        cancelado = jobs[job_id].get("cancelado")
        jobs[job_id].update(
            estado="cancelado" if cancelado else ("listo" if ok else "error"),
            progreso=1.0,
            gif=f"/salidas/{job_id}.gif" if ok else None,
            placas=f"/salidas/{job_id}_placas.gif" if ok and placas.exists() else None,
            png=f"/salidas/{job_id}_final.png" if png.exists() else None,
            log="\n".join(cola))


def cargar_semillas():
    try:
        return json.loads(SEMILLAS.read_text())
    except (OSError, ValueError):
        return []


def guardar_semillas(lista):
    SEMILLAS.write_text(json.dumps(lista, indent=2, ensure_ascii=False))


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
        if url.path == "/api/semillas":
            return self._json(cargar_semillas())
        if url.path == "/api/estado":
            job_id = parse_qs(url.query).get("id", [""])[0]
            with lock:
                job = dict(jobs.get(job_id) or {})
            if not job:
                return self._json({"error": "trabajo desconocido"}, 404)
            return self._json(job)
        if url.path.startswith("/salidas/"):
            nombre = url.path[len("/salidas/"):]
            # solo los archivos que este servidor genero (id hex + sufijo)
            if not re.fullmatch(r"[0-9a-f]{8}(_final|_placas)?\.(gif|png)", nombre):
                return self._json({"error": "nombre invalido"}, 400)
            ctype = "image/gif" if nombre.endswith(".gif") else "image/png"
            return self._archivo(SALIDAS / nombre, ctype)
        return self._json({"error": "no existe"}, 404)

    def do_POST(self):
        datos = self._cuerpo()
        if self.path == "/api/generar":
            p = limpiar(datos)
            job_id = uuid.uuid4().hex[:8]
            with lock:
                jobs[job_id] = {"estado": "corriendo", "progreso": 0.0, "params": p,
                                "gif": None, "placas": None, "png": None}
            threading.Thread(target=correr, args=(job_id, p), daemon=True).start()
            return self._json({"id": job_id, "params": p})
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
        if self.path == "/api/semillas":
            nombre = str(datos.get("nombre", "")).strip()[:60]
            if not nombre:
                return self._json({"error": "falta el nombre"}, 400)
            lista = [s for s in cargar_semillas() if s.get("nombre") != nombre]
            lista.append({"nombre": nombre, "params": limpiar(datos.get("params", {}))})
            guardar_semillas(lista)
            return self._json(lista)
        if self.path == "/api/semillas/borrar":
            nombre = str(datos.get("nombre", ""))
            lista = [s for s in cargar_semillas() if s.get("nombre") != nombre]
            guardar_semillas(lista)
            return self._json(lista)
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
