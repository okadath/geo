"""T02: endpoint de mundo, lista publica, mundo del dia y visibilidad."""
import json
import sys
import time
from datetime import date

import pytest

S1, S2, S3 = "20260101-000000", "20260102-000000", "20260103-000000"
STEM_A = "d000001_f2_aaaaaa"
STEM_B = "d000002_f2_bbbbbb"


def _meta(entorno, sello):
    return json.loads((entorno["salidas"] / sello / "params.json").read_text())


def _parchear_meta(entorno, sello, **cambios):
    ruta = entorno["salidas"] / sello / "params.json"
    meta = json.loads(ruta.read_text())
    meta.update(cambios)
    ruta.write_text(json.dumps(meta))


def _creado_detalle(entorno, sello, stem, creado):
    ruta = entorno["salidas"] / sello / "detalles" / f"{stem}.json"
    meta = json.loads(ruta.read_text())
    meta["creado"] = creado
    ruta.write_text(json.dumps(meta))


def _sesion(cliente, email, plan="free"):
    """Crea el usuario directamente en la BD (independiente de como se den de
    alta) y fija la cookie de sesion en el cliente."""
    cuentas = sys.modules["servidor.cuentas"]
    con = cuentas._con()
    try:
        cols = {f["name"]: f for f in con.execute("PRAGMA table_info(usuarios)")}
        fila = {"email": email, "plan": plan, "creado": time.time(),
                "expira": None if plan == "free" else time.time() + 86400}
        for nombre, f in cols.items():
            if nombre not in fila and f["notnull"] and f["dflt_value"] is None:
                fila[nombre] = ""
        fila = {k: v for k, v in fila.items() if k in cols}
        con.execute("INSERT OR REPLACE INTO usuarios(%s) VALUES(%s)"
                    % (",".join(fila), ",".join("?" * len(fila))),
                    tuple(fila.values()))
        con.commit()
    finally:
        con.close()
    cliente.cookies.set("sesion", cuentas.crear_sesion(email))


# ------------------------------ ficha ---------------------------------------

def test_mundo_resuelve_d_mas_reciente_con_capas(cliente, corrida_falsa, entorno):
    corrida_falsa(S1, STEM_A)
    corrida_falsa(S1, STEM_B)
    _creado_detalle(entorno, S1, STEM_A, "2026-01-01T00:00:01")
    _creado_detalle(entorno, S1, STEM_B, "2026-01-01T00:00:09")
    r = cliente.get(f"/api/w/{S1}")
    assert r.status_code == 200
    m = r.json()
    assert m["sello"] == S1 and m["d"] == STEM_B
    assert m["meta"]["semilla"] == 7
    assert m["publico"] is True and m["dueno"] is None
    assert m["imagen"] == f"/api/fantasia/render?sello={S1}&d={STEM_B}&calidad=1"
    assert isinstance(m["lugares"], list)
    assert isinstance(m["nombre"], str) and m["nombre"]


def test_mundo_prefiere_detalle_con_civ(cliente, corrida_falsa, entorno):
    corrida_falsa(S1, STEM_A)
    corrida_falsa(S1, STEM_B)
    _creado_detalle(entorno, S1, STEM_A, "2026-01-01T00:00:01")
    _creado_detalle(entorno, S1, STEM_B, "2026-01-01T00:00:09")
    (entorno["salidas"] / S1 / "detalles" / f"{STEM_A}_civ.png").write_bytes(b"x")
    assert cliente.get(f"/api/w/{S1}").json()["d"] == STEM_A


def test_mundo_d_explicito_gana_e_invalido_se_ignora(cliente, corrida_falsa, entorno):
    corrida_falsa(S1, STEM_A)
    corrida_falsa(S1, STEM_B)
    _creado_detalle(entorno, S1, STEM_B, "2026-01-01T00:00:09")
    assert cliente.get(f"/api/w/{S1}?d={STEM_A}").json()["d"] == STEM_A
    assert cliente.get(f"/api/w/{S1}?d=d999999_f2_cccccc").json()["d"] == STEM_B


def test_mundo_404(cliente, corrida_falsa, entorno):
    assert cliente.get(f"/api/w/{S1}").status_code == 404
    assert cliente.get("/api/w/noesunsello").status_code == 404
    corrida_falsa(S1, STEM_A)
    (entorno["salidas"] / S1 / "detalles" / f"{STEM_A}_capas.json").unlink()
    r = cliente.get(f"/api/w/{S1}")
    assert r.status_code == 404
    assert r.json() == {"error": "mundo no encontrado"}


def test_nombre_se_persiste_y_es_determinista(cliente, corrida_falsa, entorno):
    corrida_falsa(S1)
    corrida_falsa(S2)
    n1 = cliente.get(f"/api/w/{S1}").json()["nombre"]
    assert _meta(entorno, S1)["nombre"] == n1
    # misma semilla -> mismo nombre
    assert cliente.get(f"/api/w/{S2}").json()["nombre"] == n1
    _parchear_meta(entorno, S1, nombre="Thalyra")
    assert cliente.get(f"/api/w/{S1}").json()["nombre"] == "Thalyra"
    # el resto del meta sigue intacto para el lab
    c = cliente.get("/api/corridas").json()
    assert {x["sello"]: x["params"]["semilla"] for x in c} == {S1: 7, S2: 7}


# ------------------------------ lista publica --------------------------------

def _sellos(r):
    assert r.status_code == 200
    return [m["sello"] for m in r.json()]


def test_lista_sin_publicos_json_todo_publico(cliente, corrida_falsa):
    for s in (S1, S2, S3):
        corrida_falsa(s)
    assert _sellos(cliente.get("/api/w")) == [S3, S2, S1]
    assert _sellos(cliente.get("/api/w?n=2")) == [S3, S2]
    assert sorted(_sellos(cliente.get("/api/w?orden=azar"))) == [S1, S2, S3]
    item = cliente.get("/api/w").json()[0]
    assert set(item) >= {"sello", "nombre", "d", "imagen"}


def test_lista_respeta_publicos_json_y_meta(cliente, corrida_falsa, entorno):
    for s in (S1, S2, S3):
        corrida_falsa(s)
    entorno["publicos"].write_text(json.dumps([S1, S2]))
    assert _sellos(cliente.get("/api/w")) == [S2, S1]
    # meta.publico gana sobre publicos.json
    _parchear_meta(entorno, S1, publico=False)
    _parchear_meta(entorno, S3, publico=True)
    assert _sellos(cliente.get("/api/w")) == [S3, S2]


def test_lista_busqueda(cliente, corrida_falsa, entorno):
    corrida_falsa(S1)
    corrida_falsa(S2)
    _parchear_meta(entorno, S1, nombre="Ýsra Állende")
    assert _sellos(cliente.get(f"/api/w?q={S2}")) == [S2]
    assert _sellos(cliente.get("/api/w?q=ysra")) == [S1]
    assert _sellos(cliente.get("/api/w?q=ALLEN")) == [S1]
    assert _sellos(cliente.get("/api/w?q=zzzz")) == []


# ------------------------------ mundo del dia --------------------------------

def test_dia_sin_mundos(cliente):
    r = cliente.get("/api/w/dia")
    assert r.status_code == 404
    assert r.json() == {"error": "sin mundos"}


def test_dia_estable_por_fecha_y_desde_circular(cliente, corrida_falsa, monkeypatch):
    for s in (S1, S2, S3):
        corrida_falsa(s)
    mundos = sys.modules["servidor.mundos"]
    vistos = set()
    for dia in range(1, 15):
        monkeypatch.setattr(mundos, "_hoy", lambda dia=dia: date(2026, 3, dia))
        a = cliente.get("/api/w/dia").json()["sello"]
        assert cliente.get("/api/w/dia").json()["sello"] == a
        vistos.add(a)
    assert len(vistos) > 1    # cambia con la fecha
    assert cliente.get(f"/api/w/dia?desde={S1}").json()["sello"] == S2
    assert cliente.get(f"/api/w/dia?desde={S2}").json()["sello"] == S3
    assert cliente.get(f"/api/w/dia?desde={S3}").json()["sello"] == S1
    m = cliente.get(f"/api/w/dia?desde={S3}").json()
    assert {"nombre", "d", "imagen", "lugares"} <= set(m)


def test_dia_solo_publicos(cliente, corrida_falsa, entorno):
    corrida_falsa(S1)
    corrida_falsa(S2)
    _parchear_meta(entorno, S1, publico=False)
    assert cliente.get("/api/w/dia").json()["sello"] == S2
    assert cliente.get(f"/api/w/dia?desde={S2}").json()["sello"] == S2


# ------------------------------ visibilidad ----------------------------------

DUENO = "duena@ejemplo.com"


def test_visibilidad_anonimo_y_no_dueno_403(cliente, corrida_falsa, entorno):
    corrida_falsa(S1)
    _parchear_meta(entorno, S1, dueno=DUENO, publico=False)
    url = f"/api/w/{S1}/visibilidad"
    assert cliente.post(url, json={"publico": True}).status_code == 403
    _sesion(cliente, "otro@ejemplo.com")
    assert cliente.post(url, json={"publico": True}).status_code == 403
    assert _meta(entorno, S1)["publico"] is False
    # la ficha de un privado responde igual, sin revelar al dueno
    m = cliente.get(f"/api/w/{S1}").json()
    assert m["publico"] is False and m["dueno"] is None and m["es_dueno"] is False


def test_visibilidad_dueno_200_y_refleja_en_lista(cliente, corrida_falsa, entorno):
    corrida_falsa(S1)
    corrida_falsa(S2)
    _parchear_meta(entorno, S1, dueno=DUENO, publico=False)
    assert _sellos(cliente.get("/api/w")) == [S2]
    _sesion(cliente, DUENO, "pro")
    url = f"/api/w/{S1}/visibilidad"
    r = cliente.post(url, json={"publico": True})
    assert r.status_code == 200
    assert r.json() == {"sello": S1, "publico": True}
    assert _sellos(cliente.get("/api/w")) == [S2, S1]
    m = cliente.get(f"/api/w/{S1}").json()
    assert m["dueno"] == DUENO and m["es_dueno"] is True
    assert cliente.post(url, json={"publico": False}).status_code == 200
    assert _sellos(cliente.get("/api/w")) == [S2]
    assert cliente.post(url, json={"publico": "si"}).status_code == 400
    assert cliente.post(f"/api/w/{S3}/visibilidad",
                        json={"publico": True}).status_code == 404


def test_generar_pro_nace_privado_con_dueno(cliente, monkeypatch):
    rutas_lab = sys.modules["servidor.rutas_lab"]
    corridas = sys.modules["servidor.corridas"]
    metas = []
    monkeypatch.setattr(corridas, "_ejecutar",
                        lambda job, cmd, carpeta, sello, meta: metas.append(meta))
    hilos = []

    class HiloSincrono:
        def __init__(self, target, args, daemon=None):
            self.t, self.a = target, args

        def start(self):
            hilos.append(self)
            self.t(*self.a)

    monkeypatch.setattr(rutas_lab.threading, "Thread", HiloSincrono)
    _sesion(cliente, DUENO, "pro")
    r = cliente.post("/api/generar", json={"semilla": 3})
    assert r.status_code == 200, r.text
    assert len(hilos) == 1
    assert metas[0]["dueno"] == DUENO and metas[0]["publico"] is False
