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
""".split())


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def stem(w: str) -> str:
    # Stemming liviano: plurales y algunos sufijos frecuentes.
    for suf in ("aciones", "acion", "mente", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text: str) -> list[str]:
    t = strip_accents(text.lower())
    words = re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", t)
    return [stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


# Sinónimos frecuentes en consultas de e-commerce: la palabra del cliente se expande
# a la que suelen usar los sitios. Se aplica solo a la pregunta, no al índice.
SYNONYMS = {
    "mand": ["envio"], "mandan": ["envio"], "llega": ["envio"], "llegar": ["envio", "plazo"], "tarda": ["plazo", "dia"],
    "demora": ["plazo", "dia"], "despacho": ["envio"], "entrega": ["envio"], "delivery": ["envio"],
    "abren": ["horario"], "abierto": ["horario"], "atienden": ["horario"], "cierran": ["horario"],
    "cuota": ["cuota", "pago"], "pagar": ["pago"], "tarjeta": ["pago"], "efectivo": ["pago"],
    "devolver": ["devolucion", "cambio"], "cambiar": ["cambio"], "garantia": ["garantia"],
    "musica": ["audio", "auricular", "parlante"], "escuchar": ["audio", "auricular", "parlante"],
    "cable": ["cable", "inalambrico"], "inalambrico": ["inalambrico", "bluetooth"],
    "notebook": ["notebook"], "laptop": ["notebook"], "compu": ["computacion", "notebook"],
    "celular": ["celular", "telefono"], "direccion": ["local", "av"], "queda": ["local"], "ubicacion": ["local"],
}


def query_tokens(text: str) -> list[str]:
    base = tokens(text)
    extra = []
    for t in base:
        for k, v in SYNONYMS.items():
            if t == k or (len(t) >= 5 and t.startswith(k) and len(k) >= 4):
                extra += [stem(x) for x in v]
    return list(dict.fromkeys(base + extra))
