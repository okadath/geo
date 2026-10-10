"""Pruebas de humo del seam HTTP: la app arranca contra el entorno temporal."""


def test_lab_responde(cliente):
    r = cliente.get("/lab")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_corridas_incluye_la_falsa(cliente, corrida_falsa):
    sello, stem = corrida_falsa("20260101-000000")
    r = cliente.get("/api/corridas")
    assert r.status_code == 200
    corridas = r.json()
    assert [c["sello"] for c in corridas] == [sello]
    detalles = corridas[0]["detalles"]
    assert len(detalles) == 1
    assert detalles[0]["png"] == f"/salidas/{sello}/detalles/{stem}.png"
    assert detalles[0]["capas"] == f"/salidas/{sello}/detalles/{stem}_capas.json"


def test_ruta_inexistente_404_json(cliente):
    r = cliente.get("/noexiste")
    assert r.status_code == 404
    assert r.json() == {"error": "no existe"}


def test_corrida_falsa_basta_al_analizador(cliente, corrida_falsa):
    # /api/batalla/lugar pasa por batalla_srv._cargar_datos + analizar reales
    sello, stem = corrida_falsa("20260101-000000")
    r = cliente.get(f"/api/batalla/lugar?sello={sello}&d={stem}&rx=12&ry=8")
    assert r.status_code == 200
    lugar = r.json()
    assert lugar["es_mar"] is False
    assert lugar["tema"] == "puerto"    # aldea junto al mar
    r = cliente.get(f"/api/batalla/lugar?sello={sello}&d={stem}&rx=2&ry=8")
    assert r.json()["es_mar"] is True
