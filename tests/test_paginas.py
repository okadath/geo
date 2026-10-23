"""T06: rutas de paginas nuevas, OG de la ficha y redirecciones 302."""
import html

import pytest

from conftest import STEM_FALSO

S = "20260101-000000"


@pytest.mark.parametrize("ruta", [
    "/", "/nuevo", "/yo",
    f"/w/{S}", f"/w/{S}/detail", f"/w/{S}/jugar", f"/w/{S}/12,8",
    f"/w/{S}/0,0",
])
def test_paginas_nuevas_200_html(cliente, corrida_falsa, ruta):
    corrida_falsa(S)
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_jugar_sirve_juego_html(cliente):
    from servidor.config import BASE
    r = cliente.get(f"/w/{S}/jugar")
    assert r.content == (BASE / "juego.html").read_bytes()


def test_jugar_sin_enlaces_viejos(cliente, corrida_falsa):
    """T11: juego.html ya no enlaza al estudio ni construye /juego?..."""
    corrida_falsa(S)
    r = cliente.get(f"/w/{S}/jugar")
    assert r.status_code == 200
    assert "/estudio/mundo" not in r.text
    assert 'href="/juego?' not in r.text


@pytest.mark.parametrize("ruta", [
    "/w/no-es-sello","/w/no-es-sello/mapa", "/w/no-es-sello/detail",
    "/w/no-es-sello/jugar",
    "/w/no-es-sello/1,2", f"/w/{S}/1,", f"/w/{S}/a,b", f"/w/{S}/1,2,3",
    f"/w/{S}/otra",
])
def test_sello_o_xy_invalidos_404_json(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 404
    assert r.json() == {"error": "no existe"}


def test_ficha_og_rellenado(cliente, corrida_falsa):
    from servidor import mundos
    corrida_falsa(S)
    m = mundos.mundo(S)
    r = cliente.get(f"/w/{S}")
    assert r.status_code == 200
    t = r.text
    assert "{{og_" not in t
    nombre = html.escape(m["nombre"], quote=True)
    assert f'<meta property="og:title" content="{nombre}">' in t
    # sin BASE_URL en el entorno, el origen OG es el de la peticion
    base = str(cliente.base_url).rstrip("/")
    imagen = html.escape(base + m["imagen"], quote=True)
    assert f'<meta property="og:image" content="{imagen}">' in t
    assert "Semilla 7" in t
    url = html.escape(f"{base}/w/{S}", quote=True)
    assert f'<meta property="og:url" content="{url}">' in t


def test_ficha_og_con_d(cliente, corrida_falsa):
    corrida_falsa(S)
    t = cliente.get(f"/w/{S}?d={STEM_FALSO}").text
    base = str(cliente.base_url).rstrip("/")
    assert f'content="{base}/w/{S}?d={STEM_FALSO}"' in t
    assert f"d={STEM_FALSO}&amp;calidad=1" in t


def test_ficha_inexistente_marcadores_vacios(cliente):
    r = cliente.get("/w/20991231-235959")
    assert r.status_code == 200
    t = r.text
    assert "{{og_" not in t
    assert '<meta property="og:title" content="">' in t
    assert '<meta property="og:image" content="">' in t


D = f"d={STEM_FALSO}"
REDIRECCIONES = [
    ("/estudio", "/"),
    ("/estudio?sello=" + S, "/"),
    (f"/estudio/mundo?sello={S}&{D}", f"/w/{S}?{D}"),
    (f"/estudio/mundo?sello={S}", f"/w/{S}"),
    (f"/estudio/mundo?sello={S}&{D}&modo=battlemap", f"/w/{S}/detail?{D}"),
    (f"/estudio/mundo?modo=battlemap&sello={S}", f"/w/{S}/detail"),
    (f"/w/{S}/mapa", f"/w/{S}/detail"),
    (f"/w/{S}/mapa?{D}", f"/w/{S}/detail?{D}"),
    (f"/estudio/mundo?sello={S}&{D}&modo=conquistar", f"/w/{S}/jugar?{D}"),
    (f"/estudio/mundo?sello={S}&{D}&modo=otro", f"/w/{S}?{D}"),
    ("/estudio/mundo", "/"),
    (f"/estudio/mundo?{D}&modo=battlemap", "/"),
    ("/estudio/mundo?sello=../etc&modo=conquistar", "/"),
    (f"/fantasia?sello={S}&{D}", f"/w/{S}/detail?{D}"),
    (f"/fantasia?sello={S}", f"/w/{S}/detail"),
    ("/fantasia", "/"),
    ("/fantasia?sello=malo", "/"),
    (f"/batalla?sello={S}&{D}", f"/w/{S}/detail?{D}"),
    ("/batalla", "/"),
    ("/batalla?sello=2026", "/"),
    (f"/juego?sello={S}&{D}", f"/w/{S}/jugar?{D}"),
    (f"/juego?sello={S}", f"/w/{S}/jugar"),
    ("/juego", "/"),
    ("/juego?sello=x", "/"),
    ("/cuenta", "/yo"),
    ("/entrar", "/yo"),
    ("/pro", "/yo#pro"),
]


@pytest.mark.parametrize("vieja,nueva", REDIRECCIONES)
def test_redirecciones(cliente, vieja, nueva):
    r = cliente.get(vieja, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == nueva


def test_entrar_token_sigue_en_cuentas(cliente):
    r = cliente.get("/entrar/token-falso", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/yo?enlace=invalido"


@pytest.mark.parametrize("ruta,ctype", [
    ("/lab", "text/html"),
    ("/regiones", "text/html"),
    ("/app/css/base.css", "text/css"),
])
def test_rutas_intactas(cliente, ruta, ctype):
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(ctype)


def test_salidas_intacto(cliente, corrida_falsa):
    corrida_falsa(S)
    r = cliente.get(f"/salidas/{S}/detalles/{STEM_FALSO}.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert cliente.get(f"/salidas/{S}/../x").status_code in (400, 404)
