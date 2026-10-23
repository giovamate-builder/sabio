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
