"""Pruebas automáticas de SABIO. Correr con:  pytest -q"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SABIO_DB"] = str(ROOT / "data" / "test.db")

from app import connectors, engine, store  # noqa: E402
from app.extract import parse_page  # noqa: E402
from app.search import Index, build_profile, chunk_pages  # noqa: E402

PRODUCT_HTML = """<html><head><title>Mate Imperial | Matería Sur</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Mate Imperial",
"description":"Mate de calabaza forrado en cuero con virola de alpaca.","offers":{"@type":"Offer","price":"25000",
"priceCurrency":"ARS","availability":"https://schema.org/InStock"}}</script></head>
<body><nav>menu</nav><main><h1>Mate Imperial</h1><p>Mate de calabaza forrado en cuero.</p></main></body></html>"""

FAQ_HTML = """<html><head><title>Envíos | Matería Sur</title></head><body><main><h1>Envíos</h1>
<p>Enviamos a todo el país en 3 a 5 días hábiles.</p><p>Escribinos a hola@materiasur.com.ar.</p></main></body></html>"""


def _site():
    store.init()
    pages = [parse_page("https://materiasur.com/mate", PRODUCT_HTML), parse_page("https://materiasur.com/envios", FAQ_HTML)]
    prods = [p for pg in pages for p in pg.products]
    store.create_site("t1", "https://materiasur.com")
    store.replace_chunks("t1", chunk_pages(pages, prods))
    store.update_site("t1", status="listo", profile=build_profile(pages, prods), crawled_at=1.0)
    return pages


def test_extrae_producto_schema_org():
    p = parse_page("https://x.com/mate", PRODUCT_HTML)
    assert len(p.products) == 1
    pr = p.products[0]
    assert pr.name == "Mate Imperial" and pr.price == "25000" and pr.availability == "en stock"
    assert "menu" not in p.text  # la navegación no entra al conocimiento


def test_perfil_detecta_nombre_y_contacto():
    pages = _site()
    prof = build_profile(pages, [p for pg in pages for p in pg.products])
    assert prof["nombre"] == "Matería Sur"
    assert "hola@materiasur.com.ar" in prof["contacto"]["emails"]


def test_busqueda_encuentra_variantes():
    _site()
    idx = Index(store.get_chunks("t1"))
    hits, _ = idx.search("¿hacen envio al interior?")
    assert hits and "envios" in hits[0][1]["url"]


def run(coro):
    return asyncio.run(coro)


def test_responde_stock_y_precio():
    _site()
    a = run(engine.answer("t1", "¿tienen stock del mate imperial?"))
    assert a.status == "respondida" and "en stock" in a.text and "25.000" in a.text


def test_rechaza_pregunta_fuera_del_rubro():
    _site()
    a = run(engine.answer("t1", "dame la receta de la chocotorta"))
    assert a.status == "fuera_de_alcance"
    assert "chocotorta" in a.text


def test_no_inventa_si_falta_el_dato():
    _site()
    a = run(engine.answer("t1", "¿el mate imperial viene con bombilla de oro?"))
    assert a.status in ("sin_info", "respondida")
    assert "oro" not in a.text.lower() or "no encontré" in a.text.lower()


def test_modo_llm_respeta_sin_info(monkeypatch):
    """Si el modelo contesta [SIN_INFO], SABIO no muestra nada inventado."""
    _site()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    class FakeMsgs:
        async def create(self, **kw):
            assert "ÚNICAMENTE" in kw["system"]  # la regla de no inventar va siempre en el prompt
            assert "Mate Imperial" in kw["messages"][-1]["content"]  # el contexto del sitio se envía
            return type("R", (), {"content": [type("B", (), {"type": "text", "text": "[SIN_INFO]"})()]})()

    class FakeClient:
        messages = FakeMsgs()

    import anthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: FakeClient())
    a = run(engine.answer("t1", "¿de qué color es el mate imperial?"))
    assert a.status == "sin_info" and a.mode == "llm"


def test_modo_llm_cita_fuentes(monkeypatch):
    _site()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    class FakeMsgs:
        async def create(self, **kw):
            return type("R", (), {"content": [type("B", (), {"type": "text",
                                                             "text": "Sí, el Mate Imperial está en stock [1]."})()]})()

    import anthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: type("C", (), {"messages": FakeMsgs()})())
    a = run(engine.answer("t1", "¿hay mate imperial?"))
    assert a.status == "respondida" and a.sources and "[1]" not in a.text


def test_conector_shopify(monkeypatch):
    data = {"products": [{"title": "Yerba Orgánica 1kg", "handle": "yerba", "body_html": "<p>Yerba</p>",
                          "vendor": "Sur", "product_type": "Yerbas",
                          "variants": [{"price": "4500.00", "available": False, "sku": "Y1"}]}]}

    def handler(req):
        if "page=1" in str(req.url):
            return httpx.Response(200, json=data)
        return httpx.Response(200, json={"products": []})

    real = httpx.AsyncClient
    monkeypatch.setattr(connectors.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    prods = run(connectors.fetch_catalog("shopify", "https://tienda.com"))
    assert prods[0].name == "Yerba Orgánica 1kg" and prods[0].availability == "sin stock"


def test_conector_woocommerce(monkeypatch):
    data = [{"name": "Termo 1L", "permalink": "https://t.com/termo", "short_description": "Acero",
             "prices": {"price": "3500000", "currency_code": "ARS", "currency_minor_unit": 2},
             "is_in_stock": True, "sku": "T1"}]

    def handler(req):
        return httpx.Response(200, json=data if "page=1" in str(req.url) else [])

    real = httpx.AsyncClient
    monkeypatch.setattr(connectors.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    prods = run(connectors.fetch_catalog("woocommerce", "https://t.com"))
    assert prods[0].price == "35000.00" and prods[0].availability == "en stock"


def test_rastreador_no_lee_direcciones_internas(monkeypatch):
    from app.crawler import is_public_url
    monkeypatch.delenv("SABIO_ALLOW_PRIVATE", raising=False)
    assert not is_public_url("http://localhost:8000")
    assert not is_public_url("http://169.254.169.254/latest/meta-data")
    assert not is_public_url("http://192.168.0.10")
