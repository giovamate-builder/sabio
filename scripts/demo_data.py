"""Genera dos sitios de ejemplo para probar SABIO: una tienda de tecnología y una pastelería."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "demo_sites"

TECNO = {
    "name": "TecnoSur", "tagline": "Tienda online de tecnología en Pilar, Buenos Aires",
    "products": [
        ("Auriculares inalámbricos Sonix B200", "Audio", 38999, "InStock", "Auriculares Bluetooth 5.3 con cancelación de ruido, 30 horas de batería y estuche de carga USB-C. Color negro."),
        ("Parlante portátil Sonix Go Mini", "Audio", 24500, "OutOfStock", "Parlante Bluetooth resistente al agua IPX7, 12 horas de autonomía, ideal para exteriores."),
        ("Notebook Lumen 14 Ryzen 5", "Computación", 899999, "InStock", "Notebook de 14 pulgadas, procesador AMD Ryzen 5 7530U, 16 GB de RAM, SSD de 512 GB, Windows 11."),
        ("Mouse inalámbrico Orbit M3", "Computación", 12900, "InStock", "Mouse ergonómico inalámbrico de 2,4 GHz, 1600 DPI, pila AA incluida."),
        ("Teclado mecánico Orbit K87", "Computación", 54900, "LimitedAvailability", "Teclado mecánico TKL con switches rojos, retroiluminación RGB y distribución en español latinoamericano."),
        ("Monitor Vista 24 Full HD", "Computación", 219000, "InStock", "Monitor IPS de 24 pulgadas, resolución 1920x1080, 75 Hz, entradas HDMI y VGA."),
        ("Smartwatch Pulso S5", "Wearables", 79900, "InStock", "Reloj inteligente con medición de pasos, ritmo cardíaco y sueño, pantalla AMOLED de 1,4 pulgadas, 7 días de batería."),
        ("Cargador rápido 65W USB-C", "Accesorios", 18900, "InStock", "Cargador GaN de 65 W con dos puertos USB-C y uno USB-A, compatible con notebooks y celulares."),
        ("Cable USB-C a USB-C 2 metros", "Accesorios", 6500, "InStock", "Cable trenzado de 2 metros, carga de hasta 100 W y transferencia de datos USB 2.0."),
        ("Webcam Clara HD 1080p", "Computación", 32900, "OutOfStock", "Cámara web Full HD con micrófono incorporado y clip universal para monitor."),
        ("Router WiFi 6 Nexo AX1800", "Redes", 74900, "InStock", "Router de doble banda WiFi 6, hasta 1800 Mbps, cuatro antenas y control parental."),
        ("Disco SSD externo 1 TB Rayo", "Almacenamiento", 119000, "PreOrder", "SSD portátil de 1 TB con conexión USB-C, velocidad de lectura de hasta 1050 MB/s."),
    ],
    "pages": {
        "envios": ("Envíos", ["Hacemos envíos a todo el país con Correo Argentino y Andreani.",
                              "En Pilar, Escobar y Tigre entregamos con moto propia en 24 horas hábiles.",
                              "El envío es gratis en compras superiores a $150.000.",
                              "Para el resto del país el plazo es de 3 a 7 días hábiles según la provincia.",
                              "El costo del envío se calcula en el carrito ingresando tu código postal.",
                              "También podés retirar sin cargo por nuestro local de Av. Tomás Márquez 1200, Pilar, de lunes a viernes de 10 a 18 h."]),
        "medios-de-pago": ("Medios de pago", ["Aceptamos tarjetas de crédito y débito Visa, Mastercard y American Express.",
                                              "Ofrecemos hasta 6 cuotas sin interés con tarjetas bancarias.",
                                              "Con transferencia bancaria tenés un 10% de descuento.",
                                              "También podés pagar con Mercado Pago."]),
        "cambios-y-devoluciones": ("Cambios y devoluciones", ["Tenés 30 días desde que recibís el producto para cambiarlo o devolverlo.",
                                                               "El producto tiene que estar sin uso y en su caja original.",
                                                               "Todos los productos tienen garantía oficial de 12 meses.",
                                                               "Para iniciar un cambio escribinos a ventas@tecnosur.com.ar con tu número de pedido."]),
        "contacto": ("Contacto", ["Escribinos a ventas@tecnosur.com.ar.",
                                  "WhatsApp: +54 9 230 455-1234 (https://wa.me/5492304551234).",
                                  "Local: Av. Tomás Márquez 1200, Pilar. Horario de atención: lunes a viernes de 10 a 18 h y sábados de 10 a 13 h."]),
        "nosotros": ("Quiénes somos", ["TecnoSur es una tienda de tecnología fundada en 2019 en Pilar.",
                                       "Vendemos computación, audio, redes y accesorios con garantía oficial."]),
    },
    "color": "#1f6feb",
}

DULCE = {
    "name": "Dulce Pilar", "tagline": "Pastelería artesanal y recetas caseras",
    "products": [
        ("Chocotorta entera (8 porciones)", "Tortas", 18500, "InStock", "Chocotorta clásica con galletitas de chocolate, dulce de leche y queso crema. Se entrega fría."),
        ("Lemon pie", "Tortas", 16900, "InStock", "Base de masa sablée, crema de limón y merengue italiano gratinado."),
        ("Torta Rogel", "Tortas", 21000, "OutOfStock", "Capas finas de masa crocante con dulce de leche y merengue."),
        ("Docena de alfajores de maicena", "Masas", 9800, "InStock", "Alfajores de maicena rellenos de dulce de leche con coco rallado."),
        ("Box de medialunas x12", "Panadería", 7200, "InStock", "Medialunas de manteca recién horneadas, disponibles de martes a domingo."),
    ],
    "pages": {
        "recetas/chocotorta": ("Receta de chocotorta casera", [
            "Ingredientes de la chocotorta: 2 paquetes de galletitas de chocolate, 400 g de dulce de leche repostero, 300 g de queso crema, 1 taza de café o leche chocolatada para mojar las galletitas.",
            "Paso 1 de la receta de chocotorta: mezclar el dulce de leche con el queso crema hasta lograr una crema lisa.",
            "Paso 2: mojar rápidamente cada galletita en el café y formar una capa en una fuente rectangular.",
            "Paso 3: cubrir con una capa de crema y repetir, alternando galletitas y crema, hasta terminar con crema.",
            "Paso 4: decorar con galletitas molidas o cacao y llevar a la heladera por lo menos 4 horas antes de servir."]),
        "recetas/budin-de-limon": ("Receta de budín de limón", [
            "Ingredientes: 3 huevos, 200 g de azúcar, 120 ml de aceite, 1 yogur natural, ralladura de 2 limones y 250 g de harina leudante.",
            "Batir los huevos con el azúcar, sumar el aceite, el yogur y la ralladura, incorporar la harina y hornear 45 minutos a 180 °C."]),
        "pedidos": ("Cómo hacer tu pedido", [
            "Las tortas se encargan con 48 horas de anticipación.",
            "Hacemos entregas en Pilar y alrededores los sábados y domingos. El envío cuesta $3.500.",
            "También podés retirar por el local de Las Camelias 455, Pilar, de martes a domingo de 9 a 20 h."]),
        "contacto": ("Contacto", ["Pedidos por WhatsApp: https://wa.me/5492304559876.", "Correo: hola@dulcepilar.com.ar."]),
    },
    "color": "#c2410c",
}


def page(site, title, body_html, ld=None):
    ld_html = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>' if ld else ""
    nav = " · ".join(f'<a href="{k}.html">{v[0]}</a>' for k, v in site["pages"].items())
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<base href="{{{{BASE}}}}"><title>{title} | {site['name']}</title><meta name="description" content="{site['tagline']}">{ld_html}
<style>body{{font-family:system-ui,Arial,sans-serif;margin:0;color:#222}}header{{background:{site['color']};color:#fff;padding:18px 28px}}
header a{{color:#fff}}nav{{padding:10px 28px;background:#f3f3f3;font-size:14px}}main{{padding:24px 28px;max-width:960px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}}.card{{border:1px solid #ddd;border-radius:10px;padding:12px}}
.price{{font-weight:700;font-size:18px}}.av{{font-size:13px;color:#555}}</style></head>
<body><header><a href="index.html" style="text-decoration:none"><b style="font-size:22px">{site['name']}</b></a><div>{site['tagline']}</div></header>
<nav><a href="index.html">Inicio</a> · {nav}</nav><main>{body_html}</main>
<!--SABIO--></body></html>"""


def slug(s):
    import re, unicodedata
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


AV_TXT = {"InStock": "En stock", "OutOfStock": "Sin stock", "LimitedAvailability": "Últimas unidades", "PreOrder": "Preventa"}


def build(site, folder: Path, base_url: str):
    folder.mkdir(parents=True, exist_ok=True)
    urls = ["index.html"]
    cards = []
    for name, cat, price, av, desc in site["products"]:
        s = slug(name)
        ld = {"@context": "https://schema.org", "@type": "Product", "name": name, "description": desc,
              "category": cat, "sku": s.upper()[:10], "brand": {"@type": "Brand", "name": site["name"]},
              "offers": {"@type": "Offer", "price": price, "priceCurrency": "ARS",
                         "availability": f"https://schema.org/{av}", "url": f"productos/{s}.html"}}
        html = (f"<h1>{name}</h1><p class='price'>${price:,}".replace(",", ".") +
                f"</p><p class='av'>{AV_TXT[av]}</p><p>{desc}</p><p>Categoría: {cat}</p>")
        (folder / "productos").mkdir(exist_ok=True)
        (folder / "productos" / f"{s}.html").write_text(page(site, name, html, ld), encoding="utf-8")
        urls.append(f"productos/{s}.html")
        cards.append(f"<div class='card'><a href='productos/{s}.html'><b>{name}</b></a>"
                     f"<div class='price'>${price:,}".replace(",", ".") + f"</div><div class='av'>{AV_TXT[av]}</div></div>")
    for key, (title, paras) in site["pages"].items():
        p = folder / f"{key}.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(page(site, title, f"<h1>{title}</h1>" + "".join(f"<p>{x}</p>" for x in paras)), encoding="utf-8")
        urls.append(f"{key}.html")
    (folder / "index.html").write_text(page(site, "Inicio", f"<h1>{site['tagline']}</h1><div class='grid'>{''.join(cards)}</div>"),
                                       encoding="utf-8")
    (folder / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                        + "".join(f"<url><loc>{base_url}/{u}</loc></url>" for u in urls) + "</urlset>", encoding="utf-8")
    (folder / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    tp = int(sys.argv[1]) if len(sys.argv) > 1 else 8101
    dp = int(sys.argv[2]) if len(sys.argv) > 2 else 8102
    build(TECNO, OUT / "tecnosur", f"http://localhost:{tp}")
    build(DULCE, OUT / "dulcepilar", f"http://localhost:{dp}")
    print("Sitios de ejemplo generados en", OUT)
