"""Planes de suscripcion: limites (PLATAFORMA.md §1.2) y precios (NEGOCIO.md §9.4).

Modulo de DATOS puro, compartido por el gating (rutas_modulos/limites) y la
pasarela (rutas_pagos). Los limites se aplican SIEMPRE en el servidor, nunca
en JS (ADR-007). Un plan expirado se trata como "free".
"""

# limites por plan; None = sin limite practico (el tope tecnico anti-abuso
# se aplica aparte en limites.py)
PLANES = {
    "free": {
        "nombre": "Free",
        "generar_mundos": False,      # solo mundos precocinados (publicos.json)
        "fantasia_calidad_max": 1,    # 1x
        "battlemap_px_max": 70,       # px por casilla
        "marca_agua": True,
        "renders_dia": 20,
        "cola_prioritaria": False,
        "licencia_comercial": False,
    },
    "pro": {
        "nombre": "Pro",
        "generar_mundos": True,
        "fantasia_calidad_max": 4,    # hasta 4x
        "battlemap_px_max": 140,
        "marca_agua": False,
        "renders_dia": 500,           # tope tecnico anti-abuso, no comercial
        "cola_prioritaria": False,
        "licencia_comercial": False,
    },
    "comercial": {
        "nombre": "Comercial",
        "generar_mundos": True,
        "fantasia_calidad_max": 4,
        "battlemap_px_max": 140,
        "marca_agua": False,
        "renders_dia": 500,
        "cola_prioritaria": True,
        "licencia_comercial": True,
    },
}

# rate limit anti-abuso para TODOS los planes: renders frios por minuto
RENDERS_POR_MINUTO = 10

# precios publicados (NEGOCIO §9.4); el boton destacado es SIEMPRE el anual
# (§9.2: la comision fija de la pasarela se diluye 12x). Los `id` son los que
# viajaran a Paddle como price id logico cuando se conecte la pasarela.
PRECIOS = [
    {"id": "pro-anual", "plan": "pro", "ciclo": "anual",
     "precio": "$29/año", "usd": 29, "destacado": True},
    {"id": "pro-mensual", "plan": "pro", "ciclo": "mensual",
     "precio": "$4.99/mes", "usd": 4.99, "destacado": False},
    {"id": "comercial-anual", "plan": "comercial", "ciclo": "anual",
     "precio": "$59/año", "usd": 59, "destacado": True},
    {"id": "comercial-mensual", "plan": "comercial", "ciclo": "mensual",
     "precio": "$9.99/mes", "usd": 9.99, "destacado": False},
]


def limites(plan):
    """Limites vigentes de un plan; desconocido o expirado -> free."""
    return PLANES.get(plan) or PLANES["free"]
