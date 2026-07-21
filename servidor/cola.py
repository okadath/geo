"""Cola acotada de renders frios (llamadas a los modulos _srv).

Los renders de fantasia/batalla son sincronos y pesan CPU: si llegan muchos a
la vez saturan la maquina. Aqui se acotan a `WORKERS` en vuelo simultaneo
(os.cpu_count()-1, minimo 1) mediante una cola con PRIORIDAD: los planes
comerciales pasan antes que pro/free. Los jobs de tecto.py (subprocesos, ya
asincronos por hilo) NO pasan por aqui.

En la fase 1 la prioridad se cablea fija (PRIORIDAD_NORMAL) porque todos son
"anonimo"/"free"; la fase 2 solo tiene que pasar la prioridad segun el plan a
`ejecutar`.
"""
import heapq
import itertools
import os
import threading

# prioridad: numero MENOR = se atiende antes (heap min). comercial < normal.
PRIORIDAD_COMERCIAL = 0
PRIORIDAD_NORMAL = 10

WORKERS = max(1, (os.cpu_count() or 2) - 1)


class ColaRenders:
    """Semaforo con orden de prioridad: hasta WORKERS ejecuciones a la vez; el
    resto espera y arranca en orden (prioridad, llegada). Un contador de
    secuencia unico rompe empates y da FIFO dentro de cada prioridad."""

    def __init__(self, workers=WORKERS):
        self._workers = workers
        self._activos = 0
        self._heap = []                       # entradas (prioridad, secuencia)
        self._seq = itertools.count()
        self._cond = threading.Condition()

    def _adquirir(self, prioridad):
        """Bloquea hasta que sea el turno de esta peticion (por prioridad)."""
        with self._cond:
            # hueco libre y nadie esperando -> pasa directo, sin encolar
            if self._activos < self._workers and not self._heap:
                self._activos += 1
                return
            entrada = (prioridad, next(self._seq))
            heapq.heappush(self._heap, entrada)
            # avanza solo cuando hay hueco Y esta entrada es la cabeza del heap
            while not (self._activos < self._workers and self._heap[0] == entrada):
                self._cond.wait()
            heapq.heappop(self._heap)
            self._activos += 1
            # deja evaluar a la nueva cabeza por si aun quedan huecos
            self._cond.notify_all()

    def _liberar(self):
        with self._cond:
            self._activos -= 1
            self._cond.notify_all()

    def ejecutar(self, fn, prioridad=PRIORIDAD_NORMAL):
        """Corre fn() respetando el limite de workers y la prioridad. Devuelve
        lo que devuelva fn; siempre libera el cupo al terminar."""
        self._adquirir(prioridad)
        try:
            return fn()
        finally:
            self._liberar()


# instancia unica compartida por todo el servidor
COLA = ColaRenders()
