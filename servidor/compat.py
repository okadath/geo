"""Adaptador entre los modulos _srv (contrato http.server) y FastAPI.

Los modulos propietarios (juego_srv/fantasia_srv/batalla_srv) esperan un
`handler` con la interfaz del viejo BaseHTTPRequestHandler: metodos
`_json`, `_archivo` y `_bytes` que ESCRIBEN la respuesta. Aqui no hay socket:
HandlerCompat captura lo que el _srv quiera responder (status, content-type,
cache y cuerpo en bytes) para que rutas_modulos lo convierta luego en una
Response de FastAPI.

Los _srv tambien reciben un objeto `url` con `.path` y `.query` (resultado de
urlparse); ese objeto lo arma el catch-all y se lo pasa tal cual, asi que aqui
no hace falta reproducirlo.

Firmas identicas a las del viejo Manejador:
  _json(obj, codigo=200)
  _archivo(ruta, ctype, cache=True)
  _bytes(datos, ctype="image/png", cache=False)

Atributos nuevos (fase 2): `.plan` y `.usuario` quedan disponibles para que
los _srv o los gates los consulten; en la fase 1 se rellenan con el plan
resuelto ("anonimo"/"free") pero todavia no gatean nada.
"""
import json
from pathlib import Path


class HandlerCompat:
    """Imita al viejo handler pero, en vez de escribir a un socket, guarda la
    respuesta en atributos para convertirla despues a una Response de FastAPI.

    Un HandlerCompat se usa para UNA sola peticion. Tras delegar en el _srv,
    `atendido` dice si algun metodo escribio respuesta; si sigue False, ningun
    modulo la tomo (el catch-all responde 404)."""

    def __init__(self, usuario=None, plan="free"):
        # datos de la respuesta capturada
        self.status = 200
        self.ctype = "application/json; charset=utf-8"
        self.cuerpo = b""
        self.cache = False          # False -> Cache-Control: no-store
        self.atendido = False       # ¿algun metodo escribio respuesta?
        # contexto de plan/usuario (enganche de la fase 2; hoy informativo)
        self.usuario = usuario
        self.plan = plan

    # --- interfaz que consumen los _srv (identica a la del viejo Manejador) ---
    def _json(self, obj, codigo=200):
        self.cuerpo = json.dumps(obj).encode()
        self.status = codigo
        self.ctype = "application/json; charset=utf-8"
        self.cache = False          # el viejo _json siempre mandaba no-store
        self.atendido = True

    def _archivo(self, ruta, ctype, cache=True):
        try:
            datos = Path(ruta).read_bytes()
        except OSError:
            return self._json({"error": "no existe"}, 404)
        self.cuerpo = datos
        self.status = 200
        self.ctype = ctype
        self.cache = cache
        self.atendido = True

    def _bytes(self, datos, ctype="image/png", cache=False):
        """Respuesta binaria en memoria (PNG renderizados por los modulos)."""
        self.cuerpo = datos
        self.status = 200
        self.ctype = ctype
        self.cache = cache
        self.atendido = True
