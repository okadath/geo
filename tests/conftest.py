"""Fixtures del seam HTTP (ver ESPECIFICACION_RUTAS.md, «Testing Decisions»).

Todas las pruebas ejercitan la app FastAPI completa con TestClient. Nada toca
los datos reales: `salidas/`, `cuentas.db` y `publicos.json` se redirigen a un
tmp_path por prueba mediante las variables de entorno que lee
servidor/config.py AL IMPORTAR:

  TECTO_SALIDAS   carpeta de corridas            (defecto BASE/salidas)
  TECTO_DB        BD sqlite de cuentas y limites (defecto BASE/cuentas.db)
  TECTO_PUBLICOS  lista de corridas publicas     (defecto BASE/publicos.json)

Como los modulos `servidor.*` capturan esas constantes al importarse, la
fixture `cliente` purga `servidor.*` de sys.modules y reimporta la app DESPUES
de fijar el entorno. Los modulos propietarios de la raiz (batalla_srv,
fantasia_srv, juego_srv) tienen su propio `SALIDAS` y NO se tocan: se
parchea su atributo con monkeypatch (lo leen en cada llamada) y se vacian sus
caches en memoria.

Uso desde otras pruebas:

    def test_algo(cliente, corrida_falsa):
        sello, stem = corrida_falsa("20260101-000000")
        r = cliente.get("/api/corridas")

`entorno` (dict con las rutas temporales: salidas, db, publicos) tambien esta
disponible, p. ej. para escribir un publicos.json:

    entorno["publicos"].write_text('["20260101-000000"]')
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# modulos de la raiz con su propio SALIDAS (y caches por (sello, stem))
MODULOS_SRV = ("batalla_srv", "fantasia_srv", "juego_srv")
CACHES_SRV = ("_CACHE_DATOS", "_CACHE_GLIFOS")

STEM_FALSO = "d000001_f0_abcdef"
N = 16    # resolucion del detalle falso (nx = ny = N)


def _purgar_servidor():
    for nombre in [m for m in sys.modules
                   if m == "servidor" or m.startswith("servidor.")]:
        del sys.modules[nombre]


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Redirige SALIDAS, la BD de cuentas y publicos.json a tmp_path.
    publicos.json NO se crea: sin el archivo todas las corridas son publicas
    (modo desarrollo)."""
    rutas = {
        "salidas": tmp_path / "salidas",
        "db": tmp_path / "cuentas.db",
        "publicos": tmp_path / "publicos.json",
    }
    rutas["salidas"].mkdir()
    monkeypatch.setenv("TECTO_SALIDAS", str(rutas["salidas"]))
    monkeypatch.setenv("TECTO_DB", str(rutas["db"]))
    monkeypatch.setenv("TECTO_PUBLICOS", str(rutas["publicos"]))
    return rutas


@pytest.fixture
def cliente(entorno, monkeypatch):
    """TestClient sobre servidor.app:app importada con el entorno temporal."""
    from fastapi.testclient import TestClient

    _purgar_servidor()
    from servidor.app import app
    from servidor import config, cuentas, rutas_lab

    # si algo hubiera importado servidor antes de fijar el entorno, la prueba
    # debe fallar aqui y no escribir en los datos reales
    assert config.SALIDAS == entorno["salidas"]
    assert cuentas.DB == entorno["db"]
    assert rutas_lab.PUBLICOS == entorno["publicos"]

    for nombre in MODULOS_SRV:
        mod = sys.modules.get(nombre)
        if mod is None:
            continue
        monkeypatch.setattr(mod, "SALIDAS", entorno["salidas"], raising=False)
        for cache in CACHES_SRV:
            if hasattr(mod, cache):
                monkeypatch.setattr(mod, cache, {})

    with TestClient(app) as c:
        yield c
    _purgar_servidor()


def _png(ruta, arr):
    Image.fromarray(np.asarray(arr, dtype=np.uint8), "RGB").save(ruta)


@pytest.fixture
def corrida_falsa(entorno):
    """Fabrica `crear(sello="20260101-000000", stem=STEM_FALSO) -> (sello, stem)`
    que deja en SALIDAS una corrida minima con un detalle de N x N px. Se
    puede llamar antes o despues de pedir `cliente` (todo se lee de disco en
    cada peticion).

    Archivos y claves obligatorias (y quien las exige):

    <sello>/params.json
        Sin el, corridas.cargar_corridas() ignora la carpeta. Claves:
        "sello", "creado", "params" (_corrida copia creado/params). El ticket
        hablaba de meta.json, pero ningun modulo lo lee: el que cuenta es
        params.json.
    <sello>/detalles/<stem>.json
        Metadatos del detalle; corridas._detalles lo lista tal cual (cualquier
        dict sirve; "creado" ordena la lista). Se ponen "paso", "factor",
        "resolucion", "res_datos" y "creado" como en los reales.
    <sello>/detalles/<stem>.png
        PNG 1x1: la URL "png" del detalle.
    <sello>/detalles/<stem>_capas.json
        batalla_srv._cargar_datos / analizar: "resolucion" [nx, ny] (sin ella
        asume 1536), "escalas.tair" [min, max], "biomas" [{id, nombre, rgb}],
        y listas "rios"/"caminos" (con "puntos") y "asentamientos" (con x, y),
        que pueden ir vacias. "paises.lista" la usa titulo_escena. Su
        existencia ademas expone la URL "capas" en _detalles.
    <sello>/detalles/<stem>_datos.png    RGB = temp, precip, alt (0..255)
    <sello>/detalles/<stem>_datos2.png   RGB = bioma (255 = mar), koppen, hielo
        _cargar_datos devuelve None (400 en /api/batalla/*) si falta
        cualquiera de los tres (capas, datos, datos2).

    Mundo falso: mitad oeste mar (x < N/2), mitad este bosque templado
    (bioma 7) a media altura; una aldea en (12, 8) y un rio vertical en x=10.
    El stem debe casar con batalla_srv.RE_STEM (d######_f#_xxxxxx).
    """
    def crear(sello="20260101-000000", stem=STEM_FALSO):
        carpeta = entorno["salidas"] / sello
        det = carpeta / "detalles"
        det.mkdir(parents=True, exist_ok=True)
        (carpeta / "params.json").write_text(json.dumps({
            "sello": sello, "creado": "2026-01-01T00:00:00",
            "params": {"semilla": 7, "resolucion": 64},
        }), encoding="utf-8")
        (det / f"{stem}.json").write_text(json.dumps({
            "paso": 1, "factor": 2, "resolucion": [N, N],
            "res_datos": [N, N], "creado": "2026-01-01T00:00:01",
        }), encoding="utf-8")
        _png(det / f"{stem}.png", [[[0, 0, 0]]])

        mar = np.zeros((N, N), bool)
        mar[:, : N // 2] = True
        d1 = np.zeros((N, N, 3), np.uint8)
        d1[..., 0] = 160                         # temperatura templada
        d1[..., 1] = 128                         # precipitacion media
        d1[..., 2] = np.where(mar, 0, 90)        # altitud: 0 en el mar
        d2 = np.zeros((N, N, 3), np.uint8)
        d2[..., 0] = np.where(mar, 255, 7)       # bioma: mar / bosque templado
        _png(det / f"{stem}_datos.png", d1)
        _png(det / f"{stem}_datos2.png", d2)

        (det / f"{stem}_capas.json").write_text(json.dumps({
            "version": 1,
            "resolucion": [N, N],
            "res_datos": [N, N],
            "escalas": {"tair": [-1.0, 1.0], "precip": [0, 1],
                        "alt": [0, 1], "hielo": [0, 1]},
            "biomas": [{"id": 7, "nombre": "bosque templado",
                        "rgb": [60, 120, 60]}],
            "rios": [{"id": 1, "nombre": "Rio Falso", "caudal": 0.5,
                      "puntos": [[10.0, 0.0], [10.0, 15.0]]}],
            "caminos": [],
            "asentamientos": [{"id": 1, "nombre": "Aldea Falsa",
                               "x": 12.0, "y": 8.0}],
            "paises": {"lista": []},
        }), encoding="utf-8")
        return sello, stem

    return crear
