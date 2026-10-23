"""Normalización de texto en español para el buscador (sin dependencias externas)."""
import re
import unicodedata

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun bajo bien cada como con
contra cual cuales cuando de del desde donde dos el ella ellas ellos en entre era es esa esas
ese eso esos esta estan estas este esto estos fue ha hay hasta la las le les lo los mas me mi
mis mucho muy ni no nos o otra otro para pero poco por porque que quien se sea ser si sin sobre
son su sus tambien te ti tiene tienen tengo tenes tenés todo todos tu tus un una uno unos y ya yo
hola buenas buen dia tardes noches gracias quiero queria querria necesito saber decime decir
podes puedo puede pueden pasame pasar dame dar me informacion info favor che consulta pregunta
vos usted ustedes hacen hace haces cuanto cuanta cuantos cuantas cuesta cuestan sale salen vale valen
vende venden vendes vendan tenes tienes tiene hay habra das da dan doy mostrame mostrar ver mira
puedo podria podrias podes pueden sabes sabe saben quisiera busco buscando estoy esta estan
cual cuales donde cuando como hola alguno alguna otro otra mas menos bueno hacer
recomendas recomendar recomendame recomiendan recomienda recomendacion recomendaciones busco
""".split())


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, sin letras estiradas ("holaaa", "tortaaas") ni signos repetidos ("???")."""
    t = strip_accents(text.lower())
    t = re.sub(r"([a-z])\1{2,}", r"\1", t)
    return re.sub(r"([!?¡¿.,])\1+", r"\1", t)


def stem(w: str) -> str:
    # Stemming liviano: plurales y algunos sufijos frecuentes.
    for suf in ("aciones", "acion", "mente"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    if len(w) > 5 and w.endswith("es"):
        w = w[:-2]
    elif len(w) > 4 and w.endswith("s"):
        w = w[:-1]
    # "cables" pierde "es" y "cable" no: sacando la "e" final las dos quedan "cabl"
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", normalize(text))
    return [stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


# Sinónimos y formas de decir de Argentina: la palabra del cliente se expande a la que suelen usar
# los sitios. Se aplica solo a la pregunta, no al índice. Las claves están ya normalizadas.
SYNONYMS = {
    # envíos, plazos, pagos, cambios, horarios
    "mand": ["envio"], "mandan": ["envio"], "llega": ["envio"], "llegar": ["envio", "plazo"], "tarda": ["plazo", "dia"],
    "demora": ["plazo", "dia"], "despacho": ["envio"], "entrega": ["envio"], "delivery": ["envio"],
    "manda": ["envio"], "envian": ["envio"], "enviar": ["envio"], "envia": ["envio"], "llevan": ["envio", "entrega"],
    "domicilio": ["envio", "entrega"], "interior": ["envio", "pais"],
    "abren": ["horario"], "abierto": ["horario"], "atienden": ["horario"], "cierran": ["horario"],
    "cuota": ["cuota", "pago"], "pagar": ["pago"], "tarjeta": ["pago"], "efectivo": ["pago"],
    "devolver": ["devolucion", "cambio"], "cambiar": ["cambio"], "garantia": ["garantia"],
    "direccion": ["local", "av"], "queda": ["local"], "ubicacion": ["local"], "ubicado": ["local"],
    "encuentran": ["local"], "promo": ["oferta", "descuento"], "promocion": ["oferta", "descuento"],
    # tecnología
    "musica": ["audio", "auricular", "parlante"], "escuchar": ["audio", "auricular", "parlante"],
    "cable": ["cable", "inalambrico"], "inalambrico": ["inalambrico", "bluetooth"],
    "notebook": ["notebook"], "laptop": ["notebook"], "compu": ["computadora", "computacion", "notebook", "pc"],
    "computadora": ["computadora", "computacion", "notebook", "pc"], "celu": ["celular", "telefono"],
    "celular": ["celular", "telefono"], "auri": ["auricular"], "auris": ["auricular"], "tele": ["televisor", "tv"],
    "modem": ["router", "wifi"], "reloj": ["reloj", "smartwatch"], "camara": ["camara", "webcam"],
    "tera": ["tb"], "gigas": ["gb"], "pantalla": ["pantalla", "monitor"], "mause": ["mouse"],
    "video": ["video", "vga", "gpu", "grafica"], "grafica": ["grafica", "vga", "gpu"],
    # ropa y calzado
    "zapa": ["zapatilla"], "zapas": ["zapatilla"], "zapatilla": ["zapatilla", "calzado"],
    "remera": ["remera", "camiseta"], "buzo": ["buzo", "sweater", "hoodie"], "campera": ["campera", "chaqueta"],
    "jean": ["jean", "pantalon"], "lent": ["anteojo", "lente"],
    # comida y pastelería ("sanguches" queda "sanguch" después del stemming)
    "sanguche": ["sandwich"], "sanguch": ["sandwich"], "sanguchito": ["sandwich"], "sandwiche": ["sandwich"],
    "birra": ["cerveza"], "pastel": ["torta"], "factura": ["medialuna", "factura"],
    # verbos que en los sitios suelen aparecer como sustantivo
    "mide": ["medicion", "medida"], "miden": ["medicion", "medida"], "medir": ["medicion", "medida"],
    "lee": ["lectura"], "leer": ["lectura"], "carga": ["carga", "cargador"], "cargar": ["carga", "cargador"],
}
# Las claves se comparan con palabras ya procesadas por stem()
SYNONYMS = {stem(k): v for k, v in SYNONYMS.items()}


def expansions(text: str) -> list[tuple[str, list[str]]]:
    """Cada palabra de la pregunta con sus sinónimos: [("auri", ["auricular"]), ("bluetooth", [])]."""
    out = []
    for t in dict.fromkeys(tokens(text)):
        alts = []
        for k, v in SYNONYMS.items():
            # Las claves cortas ("celu", "tele") solo valen exactas: "tele" no tiene que agarrar "telefono"
            if t == k or (len(t) >= 5 and t.startswith(k) and len(k) >= 5):
                alts += [stem(x) for x in v if stem(x) != t]
        out.append((t, list(dict.fromkeys(alts))))
    return out


def query_tokens(text: str) -> list[str]:
    groups = expansions(text)
    return list(dict.fromkeys([b for b, _ in groups] + [a for _, alts in groups for a in alts]))


# Palabras de atributo o unidad: si el sitio no las usa, no impiden responder con el resto
# ("cuántos watts tiene el cargador" se contesta con la ficha del cargador, que dice "65W")
NONBLOCKING = {stem(w) for w in """watt watts pulgada pulgadas gb tb mb hz mah metro metros kilo kilos gramo gramos
litro litros color colores talle talles modelo marca tamano medida precio costo valor unidad unidades cantidad""".split()}


def edit_distance(a: str, b: str, limit: int = 2) -> int:
    """Distancia de Damerau-Levenshtein (con trasposición), cortando apenas supera `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]
