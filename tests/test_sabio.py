"""Pruebas automáticas de SABIO. Correr con:  pytest -q"""
import asyncio
import json
import re
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


def test_lee_json_embebido_y_etiquetas_og():
    next_html = """<html><head><title>Tienda</title><script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"listado":[{"nombre":"Mouse Gamer X","precio":15999,"stock":0,"url":"/p/mouse-x"}]}}}
    </script></head><body><div id="__next"></div></body></html>"""
    pr = parse_page("https://t.com/", next_html).products
    assert pr and pr[0].name == "Mouse Gamer X" and pr[0].availability == "sin stock"
    assert pr[0].url == "https://t.com/p/mouse-x"
    state_html = """<html><body><script>window.__INITIAL_STATE__ = {"catalogo":{"items":[
    {"title":"Teclado K1","price":"23000","inStock":true}]}};</script></body></html>"""
    assert parse_page("https://t.com/", state_html).products[0].availability == "en stock"
    og_html = """<html><head><meta property="og:title" content="Monitor 27"><meta property="product:price:amount"
    content="320000"><meta property="product:price:currency" content="ARS"></head><body></body></html>"""
    assert parse_page("https://t.com/m", og_html).products[0].price == "320000"


# Tienda de prueba que arma su catálogo con JavaScript a partir de su propia API
JS_SHOP = """<!doctype html><html><head><title>Hardware Sur</title>
<script>var a=1;</script><script>var b=2;</script><script>var c=3;</script></head>
<body><main id="app"></main><script>
fetch('/api/productos').then(r => r.json()).then(d => {
  const m = document.getElementById('app');
  m.innerHTML = '<h1>Hardware Sur, tienda de componentes de PC</h1><p>Comprá online y agregá al carrito. ' +
    'Envíos a todo el país en 48 horas y hasta 12 cuotas sin interés con tarjeta.</p>' +
    d.items.map(p => `<h2>${p.nombre}</h2><p>Precio $${p.precio}. Garantía oficial de 12 meses. ` +
      'Producto nuevo, sellado, con factura A o B y soporte técnico del fabricante.</p>').join('');
});
</script></body></html>"""
JS_API = {"items": [{"nombre": "Placa de video RTX 4060", "precio": 650000, "stock": 3, "url": "/producto/rtx-4060"},
                    {"nombre": "Fuente 750W Gold", "precio": 120000, "stock": 0, "url": "/producto/fuente-750"}]}


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.fixture
def js_shop(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/productos":
                body, ctype = json.dumps(JS_API).encode(), "application/json"
            elif self.path in ("/", "/index.html"):
                body, ctype = JS_SHOP.encode(), "text/html; charset=utf-8"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SABIO_ALLOW_PRIVATE", "1")
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


@pytest.mark.skipif(not _chromium_ok(), reason="Playwright/Chromium no instalado")
def test_lee_tienda_hecha_con_javascript(js_shop, monkeypatch):
    from app.crawler import crawl
    monkeypatch.setenv("SABIO_RENDER_JS", "off")
    sin_navegador = run(crawl(js_shop, max_pages=3))
    assert "RTX 4060" not in sin_navegador[0].text and not sin_navegador[0].products

    monkeypatch.setenv("SABIO_RENDER_JS", "auto")
    page = run(crawl(js_shop, max_pages=3))[0]
    assert page.rendered and "Placa de video RTX 4060" in page.text
    prods = {p.name: p for p in page.products}  # salen de la API que la página llama al cargar
    assert prods["Placa de video RTX 4060"].availability == "en stock"
    assert prods["Fuente 750W Gold"].availability == "sin stock"


def _tienda_sin_catalogo():
    """Una tienda de la que SABIO solo pudo leer la portada (como pasaba con los sitios JavaScript)."""
    store.init()
    html = """<html><head><title>Hardware Sur</title></head><body><main><h1>Hardware Sur</h1>
    <p>Componentes de PC. Comprá online, agregá al carrito y pagá en cuotas.</p></main></body></html>"""
    pages = [parse_page("https://hardwaresur.com/", html)]
    store.create_site("t2", "https://hardwaresur.com")
    store.replace_chunks("t2", chunk_pages(pages, []))
    store.update_site("t2", status="listo", profile=build_profile(pages, []), crawled_at=1.0)


@pytest.mark.parametrize("q", ["¿tienen stock?", "¿tienen stock de placas de video?", "¿hacen envíos a Córdoba?",
                               "¿cuál es el horario de atención?", "¿tienen garantía?", "¿puedo retirar en el local?"])
def test_pregunta_de_compra_en_tienda_nunca_es_fuera_de_alcance(q):
    _tienda_sin_catalogo()
    a = run(engine.answer("t2", q))
    assert a.status != "fuera_de_alcance"
    if a.status == "sin_info":
        assert "comunicarte" in a.text  # ofrece el contacto


def test_tienda_sigue_rechazando_otro_rubro():
    _tienda_sin_catalogo()
    assert run(engine.answer("t2", "me das la receta de la chocotorta")).status == "fuera_de_alcance"


def test_envios_responde_con_la_meta_descripcion():
    store.init()
    html = """<html><head><title>Hardware Sur</title><meta name="description" content="Componentes de PC al mejor
    precio. Envíos a todo el país."></head><body><main><h1>Hardware Sur</h1><p>Agregá al carrito y comprá online.</p>
    </main></body></html>"""
    pages = [parse_page("https://hardwaresur.com/", html)]
    store.create_site("t4", "https://hardwaresur.com")
    store.replace_chunks("t4", chunk_pages(pages, []))
    store.update_site("t4", status="listo", profile=build_profile(pages, []), crawled_at=1.0)
    a = run(engine.answer("t4", "¿hacen envíos?"))
    assert a.status == "respondida" and "todo el país" in a.text
    # "Córdoba" no figura en el sitio: SABIO prefiere no afirmar nada, pero tampoco lo trata como otro rubro
    assert run(engine.answer("t4", "¿hacen envíos a Córdoba?")).status in ("sin_info", "respondida")


def test_rastreador_se_detiene_si_el_sitio_lo_rechaza(monkeypatch):
    from app import crawler
    pedidos = []

    def handler(req):
        pedidos.append(str(req.url))
        if req.url.path in ("/robots.txt", "/sitemap.xml"):
            return httpx.Response(404)
        if req.url.path == "/":
            links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(40))
            return httpx.Response(200, html=f"<html><body><main><p>Inicio</p>{links}</main></body></html>")
        return httpx.Response(429)

    real = httpx.AsyncClient
    monkeypatch.setattr(crawler.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv("SABIO_RENDER_JS", "off")
    info = {}
    pages = run(crawler.crawl("https://tienda.com/", max_pages=50, concurrency=2, info=info))
    assert len(pages) == 1 and info["bloqueado"] == 429
    assert len(pedidos) < 12  # no siguió golpeando las 40 páginas


TIENDA_HTML = {
    "sandwiches": ("Sándwiches de miga x24", "Sándwiches de miga de jamón y queso.", 15600),
    "zapatillas": ("Zapatillas urbanas Runner", "Zapatillas de lona con suela de goma.", 45000),
    "notebook": ("Notebook Lumen 14", "Computadora portátil de 14 pulgadas con 16 GB de RAM.", 899999),
    "auriculares": ("Auriculares Sonix B200", "Auriculares inalámbricos Bluetooth con 30 horas de batería.", 38999),
    "cargador": ("Cargador 65W USB-C", "Cargador compatible con notebooks y celulares.", 18900),
    "mouse": ("Mouse inalámbrico Orbit", "Mouse ergonómico inalámbrico.", 12900),
    "torta": ("Torta Rogel", "Torta de dulce de leche y merengue.", 21000),
}


def _tienda_variada():
    store.init()
    pages = []
    for slug, (name, desc, price) in TIENDA_HTML.items():
        ld = json.dumps({"@type": "Product", "name": name, "description": desc,
                         "offers": {"price": str(price), "priceCurrency": "ARS", "availability": "InStock"}})
        pages.append(parse_page(f"https://variada.com/p/{slug}", f"""<html><head><title>{name} | Variada</title>
        <script type="application/ld+json">{ld}</script></head><body><main><h1>{name}</h1><p>{desc}</p>
        <p>Agregalo al carrito.</p></main></body></html>"""))
    prods = [p for pg in pages for p in pg.products]
    store.create_site("t5", "https://variada.com")
    store.replace_chunks("t5", chunk_pages(pages, prods))
    store.update_site("t5", status="listo", profile=build_profile(pages, prods), crawled_at=5.0)


@pytest.mark.parametrize("q,esperado", [
    ("tienen sanguches de miga?", "Sándwiches de miga"),
    ("tenés zapas?", "Zapatillas"),
    ("cuanto sale la compu?", "Notebook"),
    ("cargador para el celu", "Cargador"),
    ("tenés auris???", "Auriculares"),
    ("algo para escuchar música sin cables", "Auriculares"),
    ("tenés tortas???", "Torta Rogel"),
    ("precio de la notbook", "Notebook"),      # error de tipeo
    ("el mause inalambrico cuanto sale", "Mouse"),
    ("TIENEN AURICULARES INALAMBRICOS!!!", "Auriculares"),
])
def test_entiende_sinonimos_lunfardo_y_errores_de_tipeo(q, esperado):
    _tienda_variada()
    a = run(engine.answer("t5", q))
    assert a.status == "respondida" and esperado in a.text, a.text


@pytest.mark.parametrize("q", ["tienen auriculares Sony?", "tienen celulares samsung?", "venden libros?",
                               "tienen helado de dulce de leche?", "arreglan notebooks?"])
def test_no_inventa_con_un_termino_que_el_sitio_no_tiene(q):
    """Con "Sony" o "helado" ausentes, contestar con lo demás ("auriculares", "dulce de leche") sería inventar."""
    _tienda_variada()
    assert run(engine.answer("t5", q)).status in ("sin_info", "fuera_de_alcance")


def test_correccion_de_tipeo_no_confunde_terminaciones():
    idx = Index([{"title": "Libre de gluten", "text": "Galletitas libres de gluten.", "kind": "page", "url": "u"},
                 {"title": "Mouse", "text": "Mouse inalámbrico", "kind": "page", "url": "v"}])
    from app.textutil import tokens
    t = lambda w: tokens(w)[0]  # noqa: E731 - el índice guarda las palabras ya procesadas
    assert idx.fuzzy(t("libro")) == set()          # "libro" no es "libre"
    assert idx.fuzzy(t("mause")) == {t("mouse")}


def test_busqueda_hibrida_combina_rankings_sin_cambiar_la_evidencia():
    import numpy as np
    chunks = [{"title": "Envíos", "text": "Envíos a todo el país.", "kind": "page", "url": "/envios"},
              {"title": "Garantía", "text": "Garantía oficial de 12 meses en todos los productos.", "kind": "page",
               "url": "/garantia"},
              {"title": "Nosotros", "text": "Somos una tienda con garantía.", "kind": "page", "url": "/nosotros"}]
    vecs = np.eye(3, dtype=np.float32)
    idx = Index(chunks, vecs)
    solo_palabras, _ = Index(chunks).search("tienen garantia?")
    hibrida, _ = idx.search("tienen garantia?", qvec=np.array([0, 1, 0], dtype=np.float32))
    assert hibrida[0][1]["url"] == "/garantia" and "sem" in hibrida[0][1]
    # la cobertura (evidencia escrita) es la misma con y sin embeddings
    assert {h[1]["url"]: h[2] for h in hibrida if h[2]} == {h[1]["url"]: h[2] for h in solo_palabras}
    # un fragmento que solo trae la búsqueda semántica no tiene evidencia escrita
    otra, _ = idx.search("tienen garantia?", qvec=np.array([1, 0, 0], dtype=np.float32))
    assert [h[2] for h in otra if h[1]["url"] == "/envios"] == [0.0]


def test_modo_llm_reescribe_la_pregunta_y_no_manda_temperature(monkeypatch):
    _tienda_variada()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    llamadas = []

    class FakeMsgs:
        async def create(self, **kw):
            llamadas.append(kw)
            texto = ("auriculares bluetooth\nauriculares inalámbricos" if "Reescribí" in kw["system"]
                     else "Sí, tenemos los Auriculares Sonix B200 [1].")
            return type("R", (), {"stop_reason": "end_turn",
                                  "content": [type("B", (), {"type": "text", "text": texto})()]})()

    import anthropic
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda: type("C", (), {"messages": FakeMsgs()})())
    a = run(engine.answer("t5", "tenés auris?"))
    assert a.status == "respondida" and a.mode == "llm"
    assert len(llamadas) == 2 and "Reescribí" in llamadas[0]["system"]
    assert llamadas[0]["output_config"] == {"effort": "low"}
    assert all("temperature" not in kw for kw in llamadas)  # la API la rechaza desde el 21/10/2026


def test_embeddings_con_voyage(monkeypatch):
    from app import semantic
    monkeypatch.setenv("SABIO_EMBEDDINGS", "auto")
    monkeypatch.setenv("VOYAGE_API_KEY", "test")
    pedidos = []

    def handler(req):
        body = json.loads(req.content)
        pedidos.append(body)
        assert req.headers["authorization"] == "Bearer test"
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [3.0, 4.0]}
                                                  for i in range(len(body["input"]))]})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    v = semantic.embed_documents(["a", "b"])
    assert semantic.backend() == "voyage" and v.shape == (2, 2) and abs(v[0][0] - 0.6) < 1e-6  # normalizado
    assert pedidos[0]["input_type"] == "document" and pedidos[0]["model"] == semantic.VOYAGE_MODEL
    monkeypatch.setenv("SABIO_EMBEDDINGS", "off")
    assert semantic.embed_query("x") is None


def test_perfil_usa_og_site_name_y_descarta_telefonos_falsos():
    html = """<html><head><title>Descubrí la nueva colección</title><meta property="og:site_name" content="Bensimon">
    </head><body><main><p>Imagen 00-1024-1024. Código 013734256107.</p><p>Teléfono: 011 4555-1234</p>
    </main></body></html>"""
    prof = build_profile([parse_page("https://b.com/", html)], [])
    assert prof["nombre"] == "Bensimon"
    assert prof["contacto"]["telefonos"] == ["011 4555-1234"]


def test_estadisticas_separan_fuera_de_tema():
    store.init()
    store.create_site("t3", "https://x.com")
    store.log_message("t3", "", "receta de chocotorta", "-", "fuera_de_alcance", [])
    store.log_message("t3", "", "¿abren los lunes?", "-", "sin_info", [])
    st = store.stats("t3")
    assert [x["question"] for x in st["fuera_de_tema"]] == ["receta de chocotorta"]
    assert [x["question"] for x in st["sin_respuesta"]] == ["¿abren los lunes?"]


# ---------------------------------------------------------------- Bloque 1: estabilidad del rastreo

def _client():
    from fastapi.testclient import TestClient
    from app import main
    return TestClient(main.app)  # sin "with": no corre el arranque (demo, re-rastreo)


def _mock_web(monkeypatch, handler):
    from app import crawler, ingest
    real = httpx.AsyncClient
    monkeypatch.setattr(crawler.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    async def no_platform(url):
        return None
    monkeypatch.setattr(ingest, "detect_platform", no_platform)
    monkeypatch.setenv("SABIO_RENDER_JS", "off")


def _sitio_con_enlaces(n=40):
    def handler(req):
        if req.url.path in ("/robots.txt", "/sitemap.xml"):
            return httpx.Response(404)
        links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(n))
        return httpx.Response(200, html=f"<html><body><main><h1>Página {req.url.path}</h1>"
                                        f"<p>Texto de la página {req.url.path}.</p>{links}</main></body></html>")
    return handler


def test_limite_de_paginas_configurable(monkeypatch):
    from app import ingest
    _mock_web(monkeypatch, _sitio_con_enlaces())
    monkeypatch.setenv("SABIO_MAX_PAGES", "5")
    store.init()
    store.create_site("lim", "https://limite.com")
    info = run(ingest.ingest_site("lim", max_pages=1000))  # el pedido no puede pasar el límite del servidor
    assert info["paginas"] == 5 and store.get_site("lim")["status"] == "listo"


def test_rastreo_cortado_por_tiempo_conserva_lo_leido(monkeypatch):
    from app import ingest

    async def lento(url, max_pages, info, out, on_progress):
        out.append(parse_page("https://lento.com/envios", FAQ_HTML))
        await asyncio.sleep(30)

    monkeypatch.setattr(ingest, "crawl", lento)
    monkeypatch.setenv("SABIO_CRAWL_TIMEOUT_S", "1")
    store.init()
    store.create_site("lento", "https://lento.com")
    run(ingest.ingest_site("lento"))
    s = store.get_site("lento")
    assert s["status"] == "error" and "tiempo máximo (1 s)" in s["error"] and "1 páginas" in s["error"]
    assert s["crawl_info"]["parcial"] and store.get_chunks("lento")
    r = _client().post("/api/chat", json={"site_id": "lento", "message": "¿hacen envíos?"}).json()
    assert r["estado"] == "respondida" and "todo el país" in r["respuesta"]  # responde con lo leído


def test_rastreo_cortado_sin_contenido_queda_en_error(monkeypatch):
    from app import ingest

    async def colgado(url, max_pages, info, out, on_progress):
        await asyncio.sleep(30)

    monkeypatch.setattr(ingest, "crawl", colgado)
    monkeypatch.setenv("SABIO_CRAWL_TIMEOUT_S", "1")
    store.init()
    store.create_site("colgado", "https://colgado.com")
    with pytest.raises(RuntimeError):
        run(ingest.ingest_site("colgado"))
    s = store.get_site("colgado")
    assert s["status"] == "error" and "sin leer contenido" in s["error"]
    r = _client().post("/api/chat", json={"site_id": "colgado", "message": "hola"}).json()
    assert r["estado"] == "preparando"


def test_un_solo_rastreo_a_la_vez(monkeypatch):
    from app import ingest, main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "")
    monkeypatch.setenv("SABIO_ENV", "dev")  # sin clave, el panel solo se habilita en desarrollo (Bloque 2)
    monkeypatch.setenv("SABIO_ALLOW_PRIVATE", "1")
    store.init()
    store.create_site("ocupado", "https://ocupado.com")
    assert ingest.reserve("ocupado")
    try:
        c = _client()
        r = c.post("/api/sites", json={"url": "https://otro.com"})
        assert r.status_code == 409 and "rastreo en curso" in r.json()["detail"]
        assert c.post("/api/sites/t1/recrawl").status_code == 409
        with pytest.raises(ingest.CrawlBusy):
            run(ingest.ingest_site("t1"))
        assert not ingest.reserve("t1")
    finally:
        ingest.release("ocupado")
    assert ingest.busy() is None


def test_arranque_marca_rastreos_interrumpidos():
    from app import main
    store.init()
    store.create_site("trabado", "https://trabado.com")
    store.update_site("trabado", status="rastreando")
    run(main._startup())
    s = store.get_site("trabado")
    assert s["status"] == "error" and s["error"] == "El rastreo se interrumpió, volvé a rastrear"


def test_borrar_sitio(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave")
    store.init()
    store.create_site("borrar", "https://borrar.com")
    store.replace_chunks("borrar", [{"url": "u", "title": "t", "kind": "page", "text": "x"}])
    store.log_message("borrar", "s", "q", "a", "respondida", [])
    store.create_site("demo-tecnosur", "https://x/demo/tecnosur")
    c = _client()
    assert c.delete("/api/sites/borrar").status_code == 401
    assert c.delete("/api/sites/borrar", headers={"X-Admin-Token": "mal"}).status_code == 401
    assert c.delete("/api/sites/demo-tecnosur", headers={"X-Admin-Token": "clave"}).status_code == 403
    assert c.delete("/api/sites/no-existe", headers={"X-Admin-Token": "clave"}).status_code == 404
    assert c.delete("/api/sites/borrar", headers={"X-Admin-Token": "clave"}).status_code == 200
    assert store.get_site("borrar") is None and store.get_chunks("borrar") == []
    assert store.stats("borrar")["total"] == 0 and store.get_site("demo-tecnosur")


def test_rastreo_queda_dentro_de_la_carpeta_inicial(monkeypatch):
    from app.crawler import crawl, scope_prefix
    assert scope_prefix("https://apple.com/la/mac") == "/la/"
    assert scope_prefix("https://tienda.com/inicio") == "/" and scope_prefix("https://tienda.com") == "/"

    def handler(req):
        if req.url.path in ("/robots.txt", "/sitemap.xml"):
            return httpx.Response(404)
        return httpx.Response(200, html='<html><body><main><p>Hola mundo, texto.</p><a href="/la/ipad">ipad</a>'
                                        '<a href="/us/mac">us</a><a href="/la/iphone">iphone</a></main></body></html>')
    _mock_web(monkeypatch, handler)
    paths = sorted(p.url.split("apple.com")[1] for p in run(crawl("https://apple.com/la/mac", max_pages=50)))
    assert paths == ["/la/ipad", "/la/iphone", "/la/mac"]


def test_pagina_gigante_no_llena_la_memoria(monkeypatch):
    from app.crawler import MAX_PAGE_TEXT, crawl
    enorme = "<html><body><main>" + "<p>Texto repetido de una página enorme.</p>" * 200_000 + "</main></body></html>"

    def handler(req):
        if req.url.path in ("/robots.txt", "/sitemap.xml"):
            return httpx.Response(404)
        return httpx.Response(200, html=enorme)  # unos 8 MB
    _mock_web(monkeypatch, handler)
    pages = run(crawl("https://enorme.com", max_pages=1))
    assert len(pages) == 1 and 0 < len(pages[0].text) <= MAX_PAGE_TEXT


# ---------------------------------------------------------------- Bloque 2: seguridad del panel

PROTEGIDOS = [("get", "/api/sites", None), ("get", "/api/sites/t1", None), ("get", "/api/sites/t1/stats", None),
              ("post", "/api/sites", {"url": "https://acceso.com"}), ("post", "/api/sites/t1/recrawl", None),
              ("delete", "/api/sites/borrable", None)]


@pytest.fixture
def api_sin_rastreo(monkeypatch):
    """Cliente de la API con los rastreos reemplazados por uno vacío (no sale a internet)."""
    from app import ingest, main

    async def falso(site_id, max_pages=None, reserved=False):
        ingest.release(site_id)
    monkeypatch.setattr(main, "ingest_site", falso)
    monkeypatch.setenv("SABIO_ALLOW_PRIVATE", "1")
    monkeypatch.delenv("SABIO_ENV", raising=False)
    _site()
    store.create_site("borrable", "https://borrable.com")
    return _client()


def _pedir(c, metodo, url, body, headers=None):
    return getattr(c, metodo)(url, headers=headers or {}, **({"json": body} if body else {}))


@pytest.mark.parametrize("metodo,url,body", PROTEGIDOS)
def test_endpoints_del_panel_exigen_la_clave(api_sin_rastreo, monkeypatch, metodo, url, body):
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave-correcta")
    assert _pedir(api_sin_rastreo, metodo, url, body).status_code == 401
    assert _pedir(api_sin_rastreo, metodo, url, body, {"X-Admin-Token": "otra"}).status_code == 401
    r = _pedir(api_sin_rastreo, metodo, url, body, {"X-Admin-Token": "clave-correcta"})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("metodo,url,body", PROTEGIDOS)
def test_sin_clave_el_panel_queda_deshabilitado_salvo_en_dev(api_sin_rastreo, monkeypatch, metodo, url, body):
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "")
    r = _pedir(api_sin_rastreo, metodo, url, body)
    assert r.status_code == 403 and "SABIO_ADMIN_TOKEN" in r.json()["detail"]
    monkeypatch.setenv("SABIO_ENV", "dev")
    assert _pedir(api_sin_rastreo, metodo, url, body).status_code == 200


def test_la_clave_se_compara_en_tiempo_constante(api_sin_rastreo, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave-correcta")
    llamadas = []
    real = main.hmac.compare_digest
    monkeypatch.setattr(main.hmac, "compare_digest", lambda a, b: llamadas.append((a, b)) or real(a, b))
    api_sin_rastreo.get("/api/sites", headers={"X-Admin-Token": "clave-correcta"})
    assert llamadas == [(b"clave-correcta", b"clave-correcta")]


def test_el_widget_sigue_funcionando_sin_clave(api_sin_rastreo, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave-correcta")
    r = api_sin_rastreo.post("/api/chat", json={"site_id": "t1", "message": "¿tienen stock del mate imperial?"})
    assert r.status_code == 200 and r.json()["estado"] == "respondida"
    assert api_sin_rastreo.get("/widget.js").status_code == 200
    assert api_sin_rastreo.get("/api/health").status_code == 200
    widget = (ROOT / "widget" / "widget.js").read_text(encoding="utf-8")
    # el widget solo usa rutas públicas: el chat y el voto 👍/👎 (Bloque 6)
    assert set(__import__("re").findall(r"/api/[a-z/]+", widget)) == {"/api/chat", "/api/feedback"}


# ---------------------------------------------------------------- Bloque 3: calidad de respuestas

def _demo_tecnosur(sid="b3-tecnosur", key="tecnosur", name="TecnoSur"):
    """Un sitio de ejemplo indexado desde sus archivos, con URL pública absoluta (como en Render)."""
    from app.ingest import ingest_local
    store.init()
    store.create_site(sid, f"https://sabio.example.com/demo/{key}")
    ingest_local(sid, ROOT / "demo_sites" / key, f"/demo/{key}/", name)
    return sid


@pytest.mark.parametrize("q", ["¿qué venden?", "¿Qué productos tienen?", "¿qué es esta tienda?",
                               "hola, ¿qué venden??", "¿a qué se dedican?"])
def test_preguntas_generales_responden_con_el_perfil(q):
    sid = _demo_tecnosur()
    a = run(engine.answer(sid, q))
    assert a.status == "respondida"
    assert "Tienda online de tecnología" in a.text and "Computación" in a.text  # descripción y categorías
    productos = a.text.split("Algunos productos: ")[1].rstrip(".").split(", ")
    assert 4 <= len(productos) <= 5
    nombres = {c["title"] for c in store.get_chunks(sid) if c["kind"] == "product"}
    assert set(productos) <= nombres  # todo sale de lo rastreado
    assert a.sources == [{"titulo": "Página de inicio de TecnoSur", "url": "https://sabio.example.com/demo/tecnosur"}]


def test_pregunta_general_no_atrapa_otras_preguntas():
    sid = _demo_tecnosur()
    assert run(engine.answer(sid, "¿qué venden en la farmacia de enfrente?")).status == "fuera_de_alcance"
    a = run(engine.answer(sid, "¿qué precio tiene la notebook?"))
    assert "899.999" in a.text and "Algunos productos" not in a.text


def test_envio_a_destino_que_el_sitio_no_nombra():
    sid = _demo_tecnosur()
    a = run(engine.answer(sid, "¿me lo mandan a Córdoba?"))
    assert a.status == "respondida" and a.text.startswith("El sitio de TecnoSur no menciona «Córdoba»")
    assert "Hacemos envíos a todo el país" in a.text and "ventas@tecnosur.com.ar" in a.text  # contenido y contacto
    assert a.sources[0]["url"] == "https://sabio.example.com/demo/tecnosur/envios.html"
    envios = next(c["text"] for c in store.get_chunks(sid) if c["url"].endswith("envios.html"))
    assert all(m in envios for m in re.findall(r"\$[\d.]+", a.text))  # ningún costo que no esté escrito
    assert "llega" not in a.text.lower().replace("llegar", "")


def test_envio_con_dos_terminos_desconocidos_no_responde():
    sid = _demo_tecnosur()
    assert run(engine.answer(sid, "¿me mandan una heladera a Córdoba?")).status in ("sin_info", "fuera_de_alcance")


def _paginas(n, comun="Tienda online de tecnología en Pilar, Buenos Aires"):
    return [parse_page(f"https://r.com/p{i}", f"<html><head><title>P{i}</title></head><body><main><p>{comun}</p>"
                                            f"<p>Contenido propio de la página {i}.</p></main></body></html>")
            for i in range(n)]


def test_lineas_repetidas_se_quitan_salvo_del_inicio():
    from app.search import repeated_lines
    pages = _paginas(6)
    assert repeated_lines([p.text.split("\n") for p in pages]) == {"Tienda online de tecnología en Pilar, Buenos Aires"}
    chunks = [c for c in chunk_pages(pages, []) if c["kind"] == "page"]
    assert "Tienda online" in chunks[0]["text"]                       # la portada la conserva
    assert all("Tienda online" not in c["text"] for c in chunks[1:])  # el resto no la repite
    assert all("Contenido propio" in c["text"] for c in chunks)


def test_lineas_repetidas_no_se_quitan_en_sitios_chicos():
    chunks = [c for c in chunk_pages(_paginas(4), []) if c["kind"] == "page"]
    assert all("Tienda online" in c["text"] for c in chunks)


def test_respuestas_sin_eslogan_repetido():
    sid = _demo_tecnosur()
    a = run(engine.answer(sid, "¿qué medios de pago aceptan?"))
    assert a.status == "respondida" and not a.text.startswith("Tienda online") and "Visa" in a.text


@pytest.mark.parametrize("q", ["¿cuánto sale la notebook?", "¿qué medios de pago aceptan?"])
def test_fuentes_siempre_con_url_absoluta(q):
    sid = _demo_tecnosur()
    a = run(engine.answer(sid, q))
    assert a.sources and all(s["url"].startswith("https://sabio.example.com/demo/tecnosur/") for s in a.sources)


# ---------------------------------------------------------------- Bloque 4: página /presentacion

def test_api_eval_devuelve_solo_el_resumen():
    r = _client().get("/api/eval")
    esperado = json.loads((ROOT / "eval" / "resultados.json").read_text(encoding="utf-8"))["resumen"]
    assert r.status_code == 200 and r.json() == esperado
    assert {"precision", "rechazo_correcto", "respuestas_inventadas", "latencia_p50_ms"} <= set(r.json())


def test_api_eval_sin_resultados(monkeypatch, tmp_path):
    from app import main
    monkeypatch.setattr(main, "ROOT", tmp_path)
    assert _client().get("/api/eval").status_code == 404


def test_pagina_de_presentacion():
    r = _client().get("/presentacion")
    html = r.text
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    for q in ["¿Tienen auriculares bluetooth en stock?", "¿Qué medios de pago aceptan?",
              "Pasame la receta de la chocotorta", "¿Qué venden?", "¿Abren los lunes?", "¿Quién ganó el mundial?"]:
        assert q in html
    assert 'data-site="demo-tecnosur"' in html and 'data-site="demo-dulcepilar"' in html
    assert "session: 'presentacion'" in html and "/api/eval" in html and "AbortController" in html
    assert 'href="/presentacion"' in (ROOT / "admin" / "inicio.html").read_text(encoding="utf-8")
    assert 'href="/presentacion"' in (ROOT / "admin" / "index.html").read_text(encoding="utf-8")


def test_sesiones_internas_no_cuentan_en_las_metricas():
    store.init()
    store.delete_site("t6")  # la base de pruebas persiste entre corridas
    store.create_site("t6", "https://x.com")
    store.log_message("t6", "visitante", "¿hacen envíos?", "-", "respondida", [])
    for s in ("presentacion", "eval", "verificacion"):
        store.log_message("t6", s, f"pregunta de {s}", "-", "sin_info", [])
    st = store.stats("t6")
    assert st["total"] == 1 and st["sin_respuesta"] == [] and len(st["recientes"]) == 1


# ---------------------------------------------------------------- Bloque 5: planes y límites de uso

def test_migracion_agrega_el_plan_sin_perder_datos(monkeypatch, tmp_path):
    import sqlite3
    db = tmp_path / "vieja.db"
    c = sqlite3.connect(db)  # esquema de antes del Bloque 5, con datos
    c.executescript("""CREATE TABLE sites (id TEXT PRIMARY KEY, url TEXT NOT NULL, name TEXT, platform TEXT, creds TEXT,
      status TEXT DEFAULT 'nuevo', progress INTEGER DEFAULT 0, pages INTEGER DEFAULT 0, products INTEGER DEFAULT 0,
      profile TEXT, created REAL, crawled_at REAL, error TEXT, allow_general INTEGER DEFAULT 0, contact TEXT);
      CREATE TABLE chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, url TEXT, title TEXT, kind TEXT, text TEXT, product TEXT);
      CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, session TEXT, question TEXT, answer TEXT,
      status TEXT, sources TEXT, ts REAL);
      INSERT INTO sites (id, url, name, status, pages) VALUES ('demo-tecnosur', 'https://x/demo/tecnosur', 'TecnoSur', 'listo', 18);
      INSERT INTO chunks (site_id, url, title, kind, text) VALUES ('demo-tecnosur', '/envios', 'Envíos', 'page', 'Envíos a todo el país');
      INSERT INTO messages (site_id, session, question, answer, status, ts) VALUES ('demo-tecnosur', 's', 'q', 'a', 'respondida', 1);""")
    c.commit()
    c.close()
    monkeypatch.setattr(store, "DB_PATH", str(db))
    store.init()
    s = store.get_site("demo-tecnosur")
    assert s["plan"] == "emprendedor" and s["name"] == "TecnoSur" and s["pages"] == 18
    assert store.get_chunks("demo-tecnosur")[0]["text"] == "Envíos a todo el país"
    assert store.stats("demo-tecnosur")["total"] == 1


def test_mes_en_hora_argentina():
    import calendar
    nov = calendar.timegm((2026, 11, 1, 3, 0, 0))  # 1/11 00:00 en Argentina
    assert store.month_start(calendar.timegm((2026, 12, 1, 2, 59, 0))) == nov  # todavía 30/11 en Argentina
    assert store.month_start(calendar.timegm((2026, 12, 1, 3, 0, 0))) == calendar.timegm((2026, 12, 1, 3, 0, 0))


def _mensaje(site, session, ts, status="respondida"):
    with store.conn() as c:
        c.execute("INSERT INTO messages (site_id,session,question,answer,status,sources,ts) VALUES (?,?,?,?,?,?,?)",
                  (site, session, "q", "a", status, "[]", ts))


def test_uso_cuenta_conversaciones_del_mes():
    import calendar
    store.init()
    store.delete_site("uso")  # la base de pruebas persiste entre corridas
    store.create_site("uso", "https://uso.com")
    ahora = calendar.timegm((2026, 11, 15, 12, 0, 0))
    for s in ("a", "a", "b", "presentacion", "eval", "verificacion"):
        _mensaje("uso", s, ahora)
    _mensaje("uso", "", ahora)
    _mensaje("uso", "", ahora)  # sin sesión: cada mensaje es una conversación
    _mensaje("uso", "c", calendar.timegm((2026, 10, 20, 12, 0, 0)))  # mes anterior
    _mensaje("uso", "d", ahora, status="limite")  # rechazado por límite: no suma
    assert store.usage("uso", ahora) == 4
    assert store.session_started("uso", "a", ahora) and not store.session_started("uso", "c", ahora)


def test_avisos_al_80_y_al_100(monkeypatch):
    import calendar
    monkeypatch.setitem(store.PLANS, "emprendedor", 5)
    store.init()
    store.delete_site("aviso")  # la base de pruebas persiste entre corridas
    store.create_site("aviso", "https://aviso.com")
    ahora = calendar.timegm((2026, 11, 15, 12, 0, 0))
    estados = []
    for i in range(5):
        _mensaje("aviso", f"s{i}", ahora)
        estados.append(store.plan_status("aviso", "emprendedor", ahora)["estado"])
    assert estados == ["ok", "ok", "ok", "aviso", "limite"]
    assert store.plan_status("aviso", "pro", ahora) == {"plan": "pro", "limite": 8000, "conversaciones_mes": 5,
                                                        "porcentaje": 0.1, "estado": "ok"}


def test_al_limite_el_widget_responde_con_el_contacto(monkeypatch):
    from app import main
    monkeypatch.setitem(store.PLANS, "emprendedor", 2)
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave")
    _site()
    store.delete_site("lim2")  # la base de pruebas persiste entre corridas
    store.create_site("lim2", "https://materiasur.com")  # sitio nuevo: plan emprendedor
    store.replace_chunks("lim2", store.get_chunks("t1"))
    store.update_site("lim2", status="listo", profile=store.get_site("t1")["profile"], crawled_at=2.0)
    c = _client()
    chat = lambda s, q="¿tienen stock del mate imperial?": c.post(  # noqa: E731
        "/api/chat", json={"site_id": "lim2", "message": q, "session": s}).json()
    assert chat("a")["estado"] == "respondida" and chat("b")["estado"] == "respondida"
    r = chat("c")  # tercera conversación del mes con límite 2
    assert r["estado"] == "limite" and "hola@materiasur.com.ar" in r["respuesta"] and r["fuentes"] == []
    assert chat("a")["estado"] == "respondida"            # la conversación empezada puede seguir
    assert chat("presentacion")["estado"] == "respondida"  # las sesiones internas no tienen límite
    uso = c.get("/api/sites/lim2/stats", headers={"X-Admin-Token": "clave"}).json()["uso"]
    assert uso["estado"] == "limite" and uso["conversaciones_mes"] == 2
    # Al subir de plan vuelve a responder
    r = c.put("/api/sites/lim2/plan", json={"plan": "pyme"}, headers={"X-Admin-Token": "clave"})
    assert r.status_code == 200 and r.json()["limite"] == 2000
    assert chat("c")["estado"] == "respondida"


def test_cambiar_plan_requiere_clave_y_plan_valido(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave")
    _site()
    c = _client()
    assert c.put("/api/sites/t1/plan", json={"plan": "pro"}).status_code == 401
    assert c.put("/api/sites/t1/plan", json={"plan": "pro"}, headers={"X-Admin-Token": "mal"}).status_code == 401
    assert c.put("/api/sites/t1/plan", json={"plan": "gratis"}, headers={"X-Admin-Token": "clave"}).status_code == 400
    assert c.put("/api/sites/nada/plan", json={"plan": "pro"}, headers={"X-Admin-Token": "clave"}).status_code == 404
    assert c.put("/api/sites/t1/plan", json={"plan": "pro"}, headers={"X-Admin-Token": "clave"}).status_code == 200
    assert store.get_site("t1")["plan"] == "pro"


def test_sitios_nuevos_emprendedor_y_demos_pro():
    from app import main
    store.init()
    store.create_site("nuevo", "https://nuevo.com")
    assert store.get_site("nuevo")["plan"] == "emprendedor"
    main._setup_demo()
    assert store.get_site("demo-tecnosur")["plan"] == "pro" and store.get_site("demo-dulcepilar")["plan"] == "pro"


# ---------------------------------------------------------------- Bloque 6: satisfacción y reporte

def _chat_con_id(c, session="v1", site="t1", q="¿tienen stock del mate imperial?"):
    r = c.post("/api/chat", json={"site_id": site, "message": q, "session": session}).json()
    assert isinstance(r["message_id"], int)
    return r["message_id"]


def test_feedback_un_voto_por_mensaje_y_validaciones(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave")  # el voto es público aunque haya clave
    _site()
    store.create_site("otro", "https://otro.com")
    c = _client()
    mid = _chat_con_id(c)
    voto = lambda **kw: c.post("/api/feedback", json={"site_id": "t1", "message_id": mid, "valor": 1,  # noqa: E731
                                                      "session": "v1", **kw})
    assert voto(valor=5).status_code == 400
    assert voto(site_id="otro").status_code == 404           # el mensaje no es de ese sitio
    assert voto(message_id=10**9).status_code == 404         # no existe
    assert voto(session="ajena").status_code == 403          # es de otra conversación
    assert voto().status_code == 200
    assert voto(valor=-1).status_code == 409                 # un voto por mensaje


def test_stats_suman_porcentaje_de_utiles():
    _site()
    store.delete_site("util")
    store.create_site("util", "https://util.com")
    ids = [store.log_message("util", s, "q", "a", "respondida", []) for s in ("a", "b", "c", "presentacion")]
    for mid, v, s in zip(ids, (1, 1, -1, -1), ("a", "b", "c", "presentacion")):
        store.add_feedback("util", mid, v, s)
    assert store.stats("util")["utiles"] == {"votos": 3, "positivos": 2, "porcentaje": 66.7}  # sin la sesión interna
    store.delete_site("util")
    with store.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM feedback WHERE site_id='util'").fetchone()[0] == 0


def test_reporte_mensual_csv(monkeypatch):
    import calendar
    from app import main
    monkeypatch.setattr(main, "ADMIN_TOKEN", "clave")
    store.init()
    store.delete_site("rep")
    store.create_site("rep", "https://rep.com")
    store.update_site("rep", name="Tienda Rep")
    nov = calendar.timegm((2026, 11, 10, 15, 0, 0))
    filas = [("a", "¿hacen envíos?", "respondida"), ("b", "¿abren los lunes?", "sin_info"),
             ("c", "¿abren los lunes?", "sin_info"), ("d", "receta de pizza", "fuera_de_alcance"),
             ("eval", "pregunta interna", "sin_info")]
    ids = []
    for s, q, st in filas:
        _mensaje_q = store.log_message("rep", s, q, "-", st, [])
        ids.append(_mensaje_q)
        with store.conn() as cn:
            cn.execute("UPDATE messages SET ts=? WHERE id=?", (nov, _mensaje_q))
    store.add_feedback("rep", ids[0], 1, "a")
    store.log_message("rep", "z", "pregunta de diciembre", "-", "sin_info", [])  # otro mes: no entra
    with store.conn() as cn:
        cn.execute("UPDATE messages SET ts=? WHERE question='pregunta de diciembre'",
                   (calendar.timegm((2026, 12, 2, 15, 0, 0)),))
    c = _client()
    assert c.get("/api/sites/rep/report?mes=2026-11").status_code == 401
    h = {"X-Admin-Token": "clave"}
    assert c.get("/api/sites/rep/report?mes=2026-13", headers=h).status_code == 400
    assert c.get("/api/sites/nada/report?mes=2026-11", headers=h).status_code == 404
    r = c.get("/api/sites/rep/report?mes=2026-11", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="sabio-rep-2026-11.csv"' in r.headers["content-disposition"]
    body = r.content.decode("utf-8")
    assert body.startswith(chr(0xFEFF))  # BOM para Excel
    lineas = body.lstrip(chr(0xFEFF)).splitlines()
    assert lineas[0] == "Reporte SABIO;Tienda Rep;2026-11"
    assert "Consultas totales;4" in lineas and "% resueltas;25,0%" in lineas and "% útiles;100,0%" in lineas
    sin = lineas.index("Top 10 preguntas sin respuesta;Veces")
    assert lineas[sin + 1] == "¿abren los lunes?;2"
    fuera = lineas.index("Top 10 preguntas fuera de tema;Veces")
    assert lineas[fuera + 1] == "receta de pizza;1"
    assert "pregunta interna" not in body and "diciembre" not in body
