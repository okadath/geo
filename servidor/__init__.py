"""Paquete del servidor web de tecto (FastAPI + Uvicorn).

Migracion del viejo web.py (http.server) a FastAPI conservando el 100% del
comportamiento: mismas rutas, mismas validaciones (allowlists/regexes),
mismo shape JSON y los mismos jobs en hilos con lock. Los modulos
propietarios (juego_srv/fantasia_srv/batalla_srv) NO se tocan: se adaptan
via servidor.compat.HandlerCompat.

La app vive en servidor.app:app y la levanta el lanzador delgado web.py.
"""
