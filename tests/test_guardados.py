"""T05: guardados de mundos y battlemaps (/api/yo/guardados) y su resumen en
/api/cuenta (guardados_n, mundos_propios)."""
import json

import pytest

S1, S2 = "20260101-000000", "20260102-000000"
EMAIL = "ana@example.com"
URL = "/api/yo/guardados"


def _entrar(cliente, email=EMAIL):
    from servidor import cuentas
    cuentas.asegurar_usuario(email)
    cliente.cookies.set("sesion", cuentas.crear_sesion(email))


def _borrar(cliente, cuerpo):
    return cliente.request("DELETE", URL, json=cuerpo)


# ------------------------------ sin sesion ----------------------------------

def test_sin_sesion_401_en_los_tres(cliente):
    assert cliente.get(URL).status_code == 401
    assert cliente.post(URL, json={"tipo": "mundo",
                                   "sello": S1}).status_code == 401
    assert _borrar(cliente, {"tipo": "mundo", "sello": S1}).status_code == 401


def test_sesion_invalida_401(cliente):
    cliente.cookies.set("sesion", "no-existe")
    assert cliente.get(URL).status_code == 401


# ------------------------------ CRUD ----------------------------------------

def test_anadir_listar_y_quitar_mundo(cliente):
    _entrar(cliente)
    assert cliente.get(URL).json() == {"guardados": []}

    r = cliente.post(URL, json={"tipo": "mundo", "sello": S1,
                                "x": 3, "y": 4, "query": "ignorada"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["ok"] is True and cuerpo["nuevo"] is True
    g = cuerpo["guardado"]
    assert (g["tipo"], g["sello"], g["x"], g["y"], g["query"]) == (
        "mundo", S1, None, None, None)
    assert isinstance(g["creado"], float)

    lista = cliente.get(URL).json()["guardados"]
    assert lista == [g]

    r = _borrar(cliente, {"tipo": "mundo", "sello": S1})
    assert r.status_code == 200 and r.json() == {"ok": True, "borrado": True}
    assert cliente.get(URL).json() == {"guardados": []}
    # quitar algo que ya no esta: 200 sin borrar
    assert _borrar(cliente, {"tipo": "mundo", "sello": S1}).json() == {
        "ok": True, "borrado": False}


def test_battlemap_con_coordenadas_y_query(cliente):
    _entrar(cliente)
    r = cliente.post(URL, json={"tipo": "battlemap", "sello": S1, "x": 12,
                                "y": 8, "query": "?tema=bosque&px=1024"})
    assert r.status_code == 200
    g = r.json()["guardado"]
    assert (g["tipo"], g["x"], g["y"], g["query"]) == (
        "battlemap", 12, 8, "tema=bosque&px=1024")
    # otra celda del mismo mundo y el propio mundo son guardados distintos
    cliente.post(URL, json={"tipo": "battlemap", "sello": S1, "x": 0, "y": 0})
    cliente.post(URL, json={"tipo": "mundo", "sello": S1})
    assert len(cliente.get(URL).json()["guardados"]) == 3

    r = _borrar(cliente, {"tipo": "battlemap", "sello": S1, "x": 12, "y": 8})
    assert r.json()["borrado"] is True
    restantes = {(g["tipo"], g["x"], g["y"])
                 for g in cliente.get(URL).json()["guardados"]}
    assert restantes == {("battlemap", 0, 0), ("mundo", None, None)}


def test_duplicado_idempotente(cliente):
    _entrar(cliente)
    r1 = cliente.post(URL, json={"tipo": "battlemap", "sello": S1,
                                 "x": 1, "y": 2, "query": "tema=a"})
    r2 = cliente.post(URL, json={"tipo": "battlemap", "sello": S1,
                                 "x": 1, "y": 2, "query": "tema=b"})
    assert r1.status_code == r2.status_code == 200
    assert r2.json()["nuevo"] is False
    # se conserva la fecha y se actualiza la query
    assert r2.json()["guardado"]["creado"] == r1.json()["guardado"]["creado"]
    assert r2.json()["guardado"]["query"] == "tema=b"
    assert len(cliente.get(URL).json()["guardados"]) == 1


def test_query_saneada_a_200(cliente):
    _entrar(cliente)
    q = "tema=" + "x" * 500 + "\n\x00"
    r = cliente.post(URL, json={"tipo": "battlemap", "sello": S1,
                                "x": 1, "y": 1, "query": q})
    guardada = r.json()["guardado"]["query"]
    assert len(guardada) == 200 and guardada.startswith("tema=xxx")
    assert "\n" not in guardada and "\x00" not in guardada


def test_guardados_son_por_usuario(cliente):
    _entrar(cliente, "ana@example.com")
    cliente.post(URL, json={"tipo": "mundo", "sello": S1})
    _entrar(cliente, "bea@example.com")
    assert cliente.get(URL).json() == {"guardados": []}
    # bea no puede quitar lo de ana
    assert _borrar(cliente, {"tipo": "mundo", "sello": S1}).json()[
        "borrado"] is False
    _entrar(cliente, "ana@example.com")
    assert len(cliente.get(URL).json()["guardados"]) == 1


# ------------------------------ validacion ----------------------------------

@pytest.mark.parametrize("cuerpo", [
    {"tipo": "mundo", "sello": "../etc"},
    {"tipo": "mundo", "sello": "20260101"},
    {"tipo": "mundo", "sello": S1 + "x"},
    {"tipo": "mundo", "sello": 20260101},
    {"tipo": "mundo"},
    {"tipo": "ciudad", "sello": S1},
    {"sello": S1},
    {"tipo": "battlemap", "sello": S1},
    {"tipo": "battlemap", "sello": S1, "x": -1, "y": 0},
    {"tipo": "battlemap", "sello": S1, "x": "1", "y": 0},
    {"tipo": "battlemap", "sello": S1, "x": True, "y": 0},
    [1, 2],
])
def test_validacion_400(cliente, cuerpo):
    _entrar(cliente)
    assert cliente.post(URL, json=cuerpo).status_code == 400
    assert _borrar(cliente, cuerpo).status_code == 400
    assert cliente.get(URL).json() == {"guardados": []}


def test_json_ilegible_400(cliente):
    _entrar(cliente)
    r = cliente.post(URL, content=b"{no es json",
                     headers={"content-type": "application/json"})
    assert r.status_code == 400


# ------------------------------ /api/cuenta ---------------------------------

def test_cuenta_anonima_sin_guardados(cliente):
    c = cliente.get("/api/cuenta").json()
    assert c["anonimo"] is True
    assert c["guardados_n"] == 0 and c["mundos_propios"] == []


def test_cuenta_con_guardados_y_mundos_propios(cliente, corrida_falsa,
                                               entorno):
    corrida_falsa(S1)
    corrida_falsa(S2)
    ruta = entorno["salidas"] / S2 / "params.json"
    meta = json.loads(ruta.read_text())
    meta.update(dueno=EMAIL, publico=False)
    ruta.write_text(json.dumps(meta))

    _entrar(cliente)
    c = cliente.get("/api/cuenta").json()
    assert c["guardados_n"] == 0 and c["mundos_propios"] == [S2]

    cliente.post(URL, json={"tipo": "mundo", "sello": S1})
    cliente.post(URL, json={"tipo": "battlemap", "sello": S1, "x": 1, "y": 1})
    assert cliente.get("/api/cuenta").json()["guardados_n"] == 2

    # otro usuario free sin mundos
    _entrar(cliente, "bea@example.com")
    c = cliente.get("/api/cuenta").json()
    assert c["guardados_n"] == 0 and c["mundos_propios"] == []
