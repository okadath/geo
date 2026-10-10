"""Cuenta por enlace magico y webhook de Paddle creando usuario (T04).

Todo por el seam HTTP. Sin SMTP_HOST el modulo de correo esta en modo dev y
escribe el enlace en el log "servidor.correo": se captura con caplog.
"""
import hashlib
import hmac
import json
import logging
import re
import sqlite3
import sys
import time

import pytest

RE_ENLACE = re.compile(r"https?://[^\s]+/entrar/([0-9a-f]{64})")


@pytest.fixture(autouse=True)
def _sin_smtp(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)


def _pedir(cliente, caplog, email="ana@ejemplo.com", volver=None):
    """POST /api/cuenta/enlace y devuelve (respuesta, token capturado o None)."""
    caplog.clear()
    cuerpo = {"email": email}
    if volver is not None:
        cuerpo["volver"] = volver
    with caplog.at_level(logging.INFO, logger="servidor.correo"):
        r = cliente.post("/api/cuenta/enlace", json=cuerpo)
    tokens = [m.group(1) for rec in caplog.records
              if rec.name == "servidor.correo"
              for m in [RE_ENLACE.search(rec.getMessage())] if m]
    return r, (tokens[-1] if tokens else None)


def _entrar(cliente, token):
    return cliente.get(f"/entrar/{token}", follow_redirects=False)


def test_enlace_crea_usuario_y_abre_sesion(cliente, caplog):
    r, token = _pedir(cliente, caplog, email="  Ana@Ejemplo.com ")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "modo": "dev"}
    assert token, "el enlace debe aparecer en el log en modo dev"

    # el usuario existe ya, en free, antes de usar el enlace
    from servidor import cuentas
    usr = cuentas.obtener_usuario("ana@ejemplo.com")
    assert usr and usr["plan"] == "free"

    r = _entrar(cliente, token)
    assert r.status_code == 302
    assert r.headers["location"] == "/yo"
    assert "sesion=" in r.headers["set-cookie"]
    assert "httponly" in r.headers["set-cookie"].lower()

    r = cliente.get("/api/cuenta")
    assert r.status_code == 200
    assert r.json()["email"] == "ana@ejemplo.com"
    assert r.json()["plan"] == "free"


def test_enlace_respeta_volver_relativo(cliente, caplog):
    _, token = _pedir(cliente, caplog, volver="/w/20260101-000000?d=1#x")
    r = _entrar(cliente, token)
    assert r.status_code == 302
    assert r.headers["location"] == "/w/20260101-000000?d=1#x"


def test_segundo_uso_es_invalido(cliente, caplog):
    _, token = _pedir(cliente, caplog)
    assert _entrar(cliente, token).status_code == 302
    cliente.cookies.clear()
    r = _entrar(cliente, token)
    assert r.status_code == 302
    assert r.headers["location"] == "/yo?enlace=invalido"
    assert "set-cookie" not in r.headers


def test_token_inexistente_es_invalido(cliente):
    r = _entrar(cliente, "0" * 64)
    assert r.status_code == 302
    assert r.headers["location"] == "/yo?enlace=invalido"


def test_token_caducado_es_invalido(cliente, caplog, monkeypatch):
    _, token = _pedir(cliente, caplog)
    cuentas = sys.modules["servidor.cuentas"]
    luego = time.time() + 16 * 60
    monkeypatch.setattr(cuentas, "_ahora", lambda: luego)
    r = _entrar(cliente, token)
    assert r.status_code == 302
    assert r.headers["location"] == "/yo?enlace=invalido"
    assert cliente.get("/api/cuenta").json().get("anonimo") is True


@pytest.mark.parametrize("volver", [
    "//evil.com", "http://evil.com/x", "https://evil.com", "/\\evil.com",
    "javascript:alert(1)", "evil.com", "/a b", "/x:y", "", 42,
])
def test_volver_malicioso_usa_yo(cliente, caplog, volver):
    _, token = _pedir(cliente, caplog, volver=volver)
    assert token
    r = _entrar(cliente, token)
    assert r.status_code == 302
    assert r.headers["location"] == "/yo"


@pytest.mark.parametrize("email", ["", "sin-arroba", "a@b", "a b@c.com", None])
def test_email_invalido_400(cliente, caplog, email):
    r, token = _pedir(cliente, caplog, email=email)
    assert r.status_code == 400
    assert token is None


def test_sexto_enlace_en_una_hora_429(cliente, caplog):
    for _ in range(5):
        r, _ = _pedir(cliente, caplog, email="eva@ejemplo.com")
        assert r.status_code == 200
    r, token = _pedir(cliente, caplog, email="eva@ejemplo.com")
    assert r.status_code == 429
    assert token is None
    # el limite es por correo: otro correo sigue pudiendo
    r, _ = _pedir(cliente, caplog, email="otro@ejemplo.com")
    assert r.status_code == 200


def test_rutas_con_clave_eliminadas(cliente):
    for ruta in ("/api/cuenta/registro", "/api/cuenta/entrar"):
        r = cliente.post(ruta, json={"email": "a@b.co", "clave": "12345678"})
        assert r.status_code in (404, 405)


def test_salir_cierra_la_sesion(cliente, caplog):
    _, token = _pedir(cliente, caplog)
    _entrar(cliente, token)
    assert cliente.get("/api/cuenta").json()["email"] == "ana@ejemplo.com"
    assert cliente.post("/api/cuenta/salir").json() == {"ok": True}
    assert cliente.get("/api/cuenta").json().get("anonimo") is True


# ---- webhook de Paddle ------------------------------------------------------

SECRETO = "whsec_prueba"


def _firmar(cuerpo, secreto=SECRETO):
    ts = str(int(time.time()))
    h1 = hmac.new(secreto.encode(), f"{ts}:".encode() + cuerpo,
                  hashlib.sha256).hexdigest()
    return f"ts={ts};h1={h1}"


def test_webhook_crea_usuario_con_plan(cliente, monkeypatch):
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", SECRETO)
    cuerpo = json.dumps({
        "event_type": "subscription.created",
        "data": {"customer": {"email": "Nuevo@Ejemplo.com"},
                 "custom_data": {"price_id": "pro-anual"}},
    }).encode()
    r = cliente.post("/api/pagos/webhook", content=cuerpo,
                     headers={"Paddle-Signature": _firmar(cuerpo),
                              "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "email": "nuevo@ejemplo.com",
                        "plan": "pro"}

    from servidor import cuentas
    usr = cuentas.obtener_usuario("nuevo@ejemplo.com")
    assert usr["plan"] == "pro"
    assert usr["expira"] > time.time() + 300 * 86400


def test_webhook_firma_invalida_no_crea(cliente, monkeypatch):
    monkeypatch.setenv("PADDLE_WEBHOOK_SECRET", SECRETO)
    cuerpo = json.dumps({
        "event_type": "subscription.created",
        "data": {"customer": {"email": "malo@ejemplo.com"},
                 "custom_data": {"price_id": "pro-anual"}},
    }).encode()
    r = cliente.post("/api/pagos/webhook", content=cuerpo,
                     headers={"Paddle-Signature": _firmar(cuerpo, "otro")})
    assert r.status_code == 401
    from servidor import cuentas
    assert cuentas.obtener_usuario("malo@ejemplo.com") is None


def test_checkout_anonimo_sigue_en_beta(cliente, monkeypatch):
    monkeypatch.delenv("PADDLE_TOKEN", raising=False)
    r = cliente.post("/api/pagos/checkout", json={"plan_id": "pro-anual"})
    assert r.status_code == 503
    assert r.json()["modo"] == "beta"


def test_checkout_anonimo_valida_email_con_token(cliente, monkeypatch):
    monkeypatch.setenv("PADDLE_TOKEN", "tok")
    r = cliente.post("/api/pagos/checkout", json={"plan_id": "pro-anual"})
    assert r.status_code == 400
    r = cliente.post("/api/pagos/checkout",
                     json={"plan_id": "pro-anual", "email": "x@ejemplo.com"})
    assert r.status_code == 503    # sin integracion Paddle real todavia


# ---- migracion de una BD con el esquema viejo (sal/hash NOT NULL) ----------

def test_migra_bd_con_esquema_viejo(entorno, monkeypatch, caplog):
    con = sqlite3.connect(str(entorno["db"]))
    con.execute("""CREATE TABLE usuarios(
        email  TEXT PRIMARY KEY,
        sal    TEXT NOT NULL,
        hash   TEXT NOT NULL,
        plan   TEXT NOT NULL DEFAULT 'free',
        expira REAL,
        creado REAL NOT NULL)""")
    con.execute("""CREATE TABLE sesiones(
        token TEXT PRIMARY KEY, email TEXT NOT NULL, expira REAL NOT NULL)""")
    con.execute("INSERT INTO usuarios VALUES('viejo@ejemplo.com','ab','cd',"
                "'pro',?,?)", (time.time() + 86400, time.time()))
    con.commit()
    con.close()

    from fastapi.testclient import TestClient
    for nombre in [m for m in sys.modules
                   if m == "servidor" or m.startswith("servidor.")]:
        del sys.modules[nombre]
    from servidor.app import app
    from servidor import cuentas
    assert cuentas.DB == entorno["db"]

    with TestClient(app) as c:
        # el usuario viejo se conserva (con su plan) y entra por enlace
        r, token = _pedir(c, caplog, email="viejo@ejemplo.com")
        assert r.status_code == 200 and token
        _entrar(c, token)
        cta = c.get("/api/cuenta").json()
        assert cta["email"] == "viejo@ejemplo.com"
        assert cta["plan"] == "pro"
        # y uno nuevo se crea sin clave
        r, _ = _pedir(c, caplog, email="nuevo@ejemplo.com")
        assert r.status_code == 200

    con = sqlite3.connect(str(entorno["db"]))
    info = {f[1]: f[3] for f in con.execute("PRAGMA table_info(usuarios)")}
    assert info["sal"] == 0 and info["hash"] == 0
    filas = dict(con.execute("SELECT email, sal FROM usuarios").fetchall())
    tablas = {f[0] for f in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert filas == {"viejo@ejemplo.com": "ab", "nuevo@ejemplo.com": None}
    assert "usuarios_v2" not in tablas

    # idempotente: una segunda migracion no cambia nada
    cuentas._init_hecho = False
    cuentas._con().close()
    con = sqlite3.connect(str(entorno["db"]))
    assert con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 2
    con.close()
    for nombre in [m for m in sys.modules
                   if m == "servidor" or m.startswith("servidor.")]:
        del sys.modules[nombre]
