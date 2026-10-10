"""Lugares destacados por reglas (T03): servidor/lugares.py sobre la corrida
falsa de conftest (16x16, mar al oeste, bosque templado al este, un rio,
sin caminos ni paises, una aldea en (12, 8))."""
import json
import sys
import time

import pytest

import batalla_srv


@pytest.fixture
def lug(entorno, monkeypatch):
    """servidor.lugares con batalla_srv apuntando a la SALIDAS temporal."""
    monkeypatch.setattr(batalla_srv, "SALIDAS", entorno["salidas"])
    monkeypatch.setattr(batalla_srv, "_CACHE_DATOS", {})
    sys.modules.pop("servidor.lugares", None)
    from servidor import lugares
    return lugares


def test_corrida_falsa_da_lugares_validos(lug, corrida_falsa):
    sello, stem = corrida_falsa()
    t0 = time.perf_counter()
    res = lug.lugares(sello, stem)
    assert time.perf_counter() - t0 < 2.0
    assert 1 <= len(res) <= 6
    celdas = set()
    for l in res:
        assert set(l) == {"x", "y", "nombre", "bioma", "regla"}
        assert isinstance(l["x"], int) and isinstance(l["y"], int)
        assert 0 <= l["x"] < 16 and 0 <= l["y"] < 16
        assert l["nombre"] and l["bioma"]
        assert l["regla"] in lug.ORDEN_REGLAS
        celdas.add((l["x"], l["y"]))
    assert len(celdas) == len(res)                 # sin repetir celda
    reglas = [l["regla"] for l in res]
    # la aldea esta junto al mar y el este es bosque
    assert "costa" in reglas and "bosque" in reglas
    costa = next(l for l in res if l["regla"] == "costa")
    assert (costa["x"], costa["y"]) == (12, 8)
    assert costa["nombre"] == "Puerto de Aldea Falsa"


def test_cache_en_disco_y_segunda_llamada_no_analiza(lug, corrida_falsa,
                                                      entorno, monkeypatch):
    sello, stem = corrida_falsa()
    primera = lug.lugares(sello, stem)
    ruta = entorno["salidas"] / sello / "detalles" / f"{stem}_lugares.json"
    obj = json.loads(ruta.read_text(encoding="utf-8"))
    assert obj == {"version": lug.VERSION, "lugares": primera}

    def prohibido(*a, **k):
        raise AssertionError("analizar no debe llamarse con cache")
    monkeypatch.setattr(batalla_srv, "analizar", prohibido)
    assert lug.lugares(sello, stem) == primera


def test_cache_de_version_vieja_se_recalcula(lug, corrida_falsa, entorno):
    sello, stem = corrida_falsa()
    ruta = entorno["salidas"] / sello / "detalles" / f"{stem}_lugares.json"
    ruta.write_text(json.dumps({"version": lug.VERSION - 1, "lugares": []}),
                    encoding="utf-8")
    res = lug.lugares(sello, stem)
    assert res
    assert json.loads(ruta.read_text(encoding="utf-8"))["version"] == lug.VERSION


def test_entradas_invalidas_o_sin_datos(lug, corrida_falsa):
    sello, stem = corrida_falsa()
    assert lug.lugares("../x", stem) == []
    assert lug.lugares(sello, "../../etc") == []
    assert lug.lugares(sello, "d999999_f0_000000") == []      # no existe
