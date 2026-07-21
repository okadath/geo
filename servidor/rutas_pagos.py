"""Pasarela de pagos — Paddle, lista en codigo pero SIN cobrar (ADR-007).

La regla de oro (ADR-007): NUNCA un checkout falso. Mientras no existan
credenciales en el entorno (PADDLE_TOKEN para el checkout, PADDLE_WEBHOOK_SECRET
para el webhook), la pasarela responde honestamente "modo beta" con 503 y el
front muestra la lista de espera. Toda la logica de firma del webhook esta
escrita y probada; solo falta encender las variables de entorno cuando Paddle
este conectado (fase 4).

El import de servidor.cuentas es SIEMPRE perezoso (dentro de la funcion): otra
fase escribe cuentas.py en paralelo y no debe romper el arranque de la app.
"""
import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .planes import PRECIOS

router = APIRouter()

# ventana de tolerancia de la marca de tiempo del webhook (anti-replay): 5 min
_TOLERANCIA_TS = 5 * 60

# id logico de precio -> (plan, dias de vigencia). Los `id` viajan a Paddle como
# price id logico (planes.py); anual = 365 dias, mensual = 31.
_PLAN_POR_ID = {
    p["id"]: (p["plan"], 365 if p["ciclo"] == "anual" else 31)
    for p in PRECIOS
}


@router.get("/api/pagos/config")
def config():
    """Estado de la pasarela para el front: hoy siempre beta (sin cobro), con
    la tabla de precios de planes.py para pintar la tabla de upgrade."""
    return {"activo": False, "modo": "beta", "planes": PRECIOS}


@router.post("/api/pagos/checkout")
async def checkout(request: Request):
    """Inicia el checkout de un plan. Sin PADDLE_TOKEN en el entorno (siempre,
    hoy) responde 503 modo beta: el front lo traduce a la lista de espera.
    Nunca simula un cobro (ADR-007)."""
    try:
        datos = json.loads(await request.body() or b"{}")
    except ValueError:
        datos = {}
    plan_id = str((datos or {}).get("plan_id", ""))
    if plan_id and plan_id not in _PLAN_POR_ID:
        return JSONResponse({"error": "plan desconocido"}, status_code=400)
    if not os.environ.get("PADDLE_TOKEN"):
        return JSONResponse(
            {"error": "pasarela no configurada", "modo": "beta"},
            status_code=503)
    # Con token conectado (fase 4): aqui se crearia la transaccion Paddle y se
    # devolveria la URL/overlay del checkout. Hoy nunca se llega con token.
    return JSONResponse(
        {"error": "pasarela no configurada", "modo": "beta"}, status_code=503)


def _firma_valida(cabecera, cuerpo_crudo, secreto):
    """Verifica el header Paddle-Signature ("ts=...;h1=...").

    La firma es HMAC-SHA256 de "<ts>:<cuerpo_crudo>" con el secreto del webhook.
    Devuelve True solo si (a) el header trae ts y h1, (b) el HMAC coincide en
    comparacion de tiempo constante y (c) el ts no es mas viejo que la ventana
    anti-replay. Cualquier fallo -> False.
    """
    ts = None
    h1 = None
    for parte in cabecera.split(";"):
        parte = parte.strip()
        if parte.startswith("ts="):
            ts = parte[3:]
        elif parte.startswith("h1="):
            h1 = parte[3:]
    if not ts or not h1:
        return False
    # anti-replay: rechazar marcas de tiempo viejas o no numericas
    try:
        if abs(time.time() - int(ts)) > _TOLERANCIA_TS:
            return False
    except (TypeError, ValueError):
        return False
    firmado = f"{ts}:".encode() + cuerpo_crudo
    esperado = hmac.new(secreto.encode(), firmado, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, h1)


def _email_del_payload(data):
    """Email del suscriptor. Supuesto documentado: Paddle Billing lo trae en
    data.customer.email; si el checkout se creo con custom_data.email (nuestro
    caso al pasar el email de la sesion), se usa ese como respaldo."""
    correo = ((data.get("customer") or {}).get("email")
              or (data.get("custom_data") or {}).get("email"))
    return str(correo) if correo else ""


def _plan_del_payload(data):
    """Resuelve (plan, dias) del evento. Supuesto documentado: al crear el
    checkout adjuntamos nuestro id logico en custom_data.price_id; como respaldo
    se intenta casar el price id del primer item contra los ids de PRECIOS."""
    pid = (data.get("custom_data") or {}).get("price_id")
    if pid and pid in _PLAN_POR_ID:
        return _PLAN_POR_ID[pid]
    for item in (data.get("items") or []):
        cand = (item.get("price") or {}).get("id")
        if cand in _PLAN_POR_ID:
            return _PLAN_POR_ID[cand]
    return (None, 0)


@router.post("/api/pagos/webhook")
async def webhook(request: Request):
    """Webhook de Paddle: verifica la firma y actualiza el plan del usuario.

    Sin PADDLE_WEBHOOK_SECRET en el entorno -> 503 modo beta (la firma no se
    puede verificar, asi que no se procesa nada). Con secreto: firma invalida
    -> 401; firma valida -> aplica el evento y responde 200.
    """
    secreto = os.environ.get("PADDLE_WEBHOOK_SECRET")
    if not secreto:
        return JSONResponse(
            {"error": "pasarela no configurada", "modo": "beta"},
            status_code=503)

    crudo = await request.body()
    cabecera = request.headers.get("Paddle-Signature", "")
    if not _firma_valida(cabecera, crudo, secreto):
        return JSONResponse({"error": "firma invalida"}, status_code=401)

    try:
        evento = json.loads(crudo or b"{}")
    except ValueError:
        return JSONResponse({"error": "cuerpo invalido"}, status_code=400)

    tipo = str(evento.get("event_type", ""))
    data = evento.get("data") or {}
    email = _email_del_payload(data)
    if not email:
        return JSONResponse({"error": "sin email"}, status_code=400)

    # import perezoso: la otra fase escribe cuentas.py; no debe romper el boot
    try:
        from servidor.cuentas import cambiar_plan
    except ImportError:
        # integracion final la prueba la fase 4; la firma ya quedo verificada
        return JSONResponse(
            {"ok": False, "pendiente": "cuentas.cambiar_plan no disponible"},
            status_code=200)

    if tipo in ("subscription.created", "subscription.updated"):
        plan, dias = _plan_del_payload(data)
        if not plan:
            return JSONResponse({"error": "plan no resoluble"}, status_code=400)
        cambiar_plan(email, plan, dias)
        return {"ok": True, "email": email, "plan": plan}
    if tipo == "subscription.canceled":
        cambiar_plan(email, "free", 0)
        return {"ok": True, "email": email, "plan": "free"}

    # otros eventos: aceptados sin efecto (Paddle reintenta si no es 2xx)
    return {"ok": True, "ignorado": tipo}
