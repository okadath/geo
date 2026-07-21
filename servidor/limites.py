"""Contadores y rate limit de renders frios (anti-abuso, PLATAFORMA §1.2).

Dos limites, por identidad ("email" del usuario o "ip:<addr>" del anonimo):
  - tope DIARIO por plan (PLANES[plan]["renders_dia"]): persistente en
    cuentas.db (tabla renders_dia), sobrevive reinicios.
  - tope por MINUTO comun a todos (RENDERS_POR_MINUTO): en memoria, con lock;
    ventana deslizante de marcas de tiempo por identidad.

`permitir_render(identidad, plan)` decide ANTES de renderizar (lee ambos
contadores); `incrementar(identidad)` se llama DESPUES de un render efectivo
(suma 1 al dia y apunta la marca del minuto). Asi un render que falla (400) o
que ni se intenta no consume cupo.
"""
import time
import threading
from collections import defaultdict, deque

from .cuentas import _con
from .planes import PLANES, RENDERS_POR_MINUTO

# ventana deslizante en memoria: identidad -> deque de epochs (ultimo minuto)
_marcas = defaultdict(deque)
_lock = threading.Lock()

_VENTANA = 60.0   # segundos de la ventana del rate limit por minuto


def _hoy():
    return time.strftime("%Y-%m-%d", time.localtime())


def _init():
    con = _con()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS renders_dia(
            fecha     TEXT NOT NULL,
            identidad TEXT NOT NULL,
            n         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(fecha, identidad))""")
        con.commit()
    finally:
        con.close()


_init()


def uso_hoy(identidad):
    """Renders contabilizados hoy para esta identidad."""
    con = _con()
    try:
        fila = con.execute(
            "SELECT n FROM renders_dia WHERE fecha=? AND identidad=?",
            (_hoy(), identidad)).fetchone()
    finally:
        con.close()
    return int(fila["n"]) if fila else 0


def _por_minuto(identidad, ahora):
    """Cuenta (y purga) las marcas de la ultima ventana para esta identidad."""
    dq = _marcas[identidad]
    lim = ahora - _VENTANA
    while dq and dq[0] < lim:
        dq.popleft()
    return len(dq)


def permitir_render(identidad, plan):
    """(ok, motivo). Comprueba tope por minuto y tope diario del plan."""
    ahora = time.time()
    with _lock:
        if _por_minuto(identidad, ahora) >= RENDERS_POR_MINUTO:
            return False, ("maximo %d renders por minuto; espera un momento"
                           % RENDERS_POR_MINUTO)
    tope = (PLANES.get(plan) or PLANES["free"])["renders_dia"]
    if uso_hoy(identidad) >= tope:
        return False, "alcanzaste el tope de %d renders de hoy" % tope
    return True, "ok"


def incrementar(identidad):
    """Contabiliza un render efectivo: suma al dia (persistente) y apunta la
    marca del minuto (memoria)."""
    ahora = time.time()
    with _lock:
        _marcas[identidad].append(ahora)
    con = _con()
    try:
        con.execute(
            "INSERT INTO renders_dia(fecha, identidad, n) VALUES(?,?,1)"
            " ON CONFLICT(fecha, identidad) DO UPDATE SET n = n + 1",
            (_hoy(), identidad))
        con.commit()
    finally:
        con.close()
