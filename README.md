# SABIO

Asistente conversacional que se instala en cualquier sitio web, lee solo todo su contenido
(productos, precios, stock, envíos, preguntas frecuentes) y responde a los visitantes **únicamente
con lo que está publicado en ese sitio**. Si le preguntás a una tienda de tecnología la receta de
la chocotorta, te dice que eso no está en el sitio. Si se lo preguntás a una pastelería que la
publica, te la da con el enlace.

Proyecto de la materia Dirección de Proyectos Informáticos, Ingeniería en Informática, USAL (2026).
Equipo: Giovanni Matellini Delannoy (director), Joaquín Policaro, Rafael Irrazábal, Ignacio Di Martino.

## Cómo funciona

```
 Sitio del cliente                         Servidor SABIO
 ┌──────────────────┐   1 línea de script   ┌────────────────────────────────────────────┐
 │ <script widget>  │ ────────────────────▶ │ /api/chat                                   │
 │  burbuja de chat │ ◀──────────────────── │   ├─ búsqueda en el índice del sitio (BM25) │
 └──────────────────┘   respuesta + fuente  │   ├─ control de alcance (¿es del rubro?)    │
                                            │   ├─ Claude (solo con el contexto) o        │
        rastreo diario                      │   │  modo extractivo sin API                │
 sitemap + páginas + schema.org ──────────▶ │   └─ stock en vivo: Shopify / WooCommerce / │
 API de la plataforma (stock)               │      Tiendanube                             │
                                            │ SQLite: sitios, fragmentos, conversaciones  │
                                            └────────────────────────────────────────────┘
```

1. **Absorción**: el rastreador (`app/crawler.py`) lee `sitemap.xml`, recorre los enlaces internos
   respetando `robots.txt` y extrae el texto útil de cada página y los productos marcados con
   schema.org (`app/extract.py`). Si detecta Shopify o WooCommerce, también trae el catálogo
   desde la API pública con stock real (`app/connectors.py`). Tiendanube necesita el token de la app.
2. **Índice y perfil**: el contenido se divide en fragmentos, se indexa con BM25 y se arma un perfil
   automático del sitio con su nombre, categorías, vocabulario y datos de contacto (`app/search.py`).
3. **Respuesta** (`app/engine.py`):
   - Si la pregunta no usa ningún término que exista en el sitio, se rechaza (fuera de alcance).
   - Si lo encontrado no cubre la pregunta, responde "no tengo esa información" y ofrece el contacto.
   - Con `ANTHROPIC_API_KEY` responde Claude Haiku 5.5 con una regla estricta: usar solo el contexto
     y devolver `[SIN_INFO]` si no alcanza. Sin clave funciona en modo extractivo.
   - Cada respuesta lleva el enlace a la página de donde salió.
4. **Panel** (`/admin`): alta de sitios, línea de instalación, métricas y la lista de preguntas
   que el sitio no responde, para que el dueño sepa qué información le falta publicar.

## Probarlo en 1 minuto

```bash
pip install -r requirements.txt
python scripts/run_demo.py
```

Abre la API en `http://localhost:8000` y dos sitios de ejemplo:
- `http://localhost:8101` · TecnoSur, tienda de tecnología (12 productos)
- `http://localhost:8102` · Dulce Pilar, pastelería con recetas

Abrí cualquiera de los dos y usá la burbuja de chat. Probá "¿tenés stock de los auriculares?",
"¿hacen envíos?" y "me das la receta de la chocotorta" en los dos sitios.

Para usar Claude en lugar del modo extractivo:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/run_demo.py
```

## Modo demo (todo en un solo servidor)

```bash
SABIO_DEMO=1 uvicorn app.main:app --port 8000
```

En `http://localhost:8000` aparece una página de inicio con las dos tiendas de ejemplo
(servidas en `/demo/tecnosur/` y `/demo/dulcepilar/`, con el widget ya instalado) y el panel.
Es el modo que se usa al publicarlo. Para subirlo a internet, ver **DEPLOY.md**.

## Instalarlo en un sitio real

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
curl -X POST localhost:8000/api/sites -H 'Content-Type: application/json' \
     -d '{"url": "https://mitienda.com.ar"}'
```

La respuesta trae el `id` del sitio. En el sitio se pega, antes de `</body>`:

```html
<script src="https://TU-SERVIDOR/widget.js" data-site="ID_DEL_SITIO" data-color="#2f5bea" defer></script>
```

Con Docker: `docker compose up --build`.

## API

| Método | Ruta | Uso |
|---|---|---|
| POST | `/api/sites` | Alta de un sitio `{url, platform?, creds?, allow_general?}` y rastreo en segundo plano |
| GET | `/api/sites` / `/api/sites/{id}` | Estado, páginas, productos y perfil |
| POST | `/api/sites/{id}/recrawl` | Volver a rastrear (además se hace solo cada 24 h) |
| POST | `/api/chat` | `{site_id, message, history?}` → `{respuesta, estado, fuentes, modo}` |
| GET | `/api/sites/{id}/stats` | Consultas, tasa de resolución, preguntas sin respuesta |
| GET | `/widget.js`, `/admin` | Widget y panel |

Documentación interactiva en `http://localhost:8000/docs`.

## Pruebas y evaluación

```bash
pytest -q                     # 11 pruebas: extracción, búsqueda, alcance, modo LLM simulado, conectores, seguridad del rastreador
python eval/run_eval.py       # con la demo corriendo: 37 preguntas del sitio y 18 fuera de tema
```

Resultado actual en modo extractivo (`eval/resultados.json`): precisión 91,9%, rechazo correcto
de preguntas fuera de tema 100%, 0 respuestas inventadas, latencia mediana de unos 55 ms.

Probamos bajar el umbral de cobertura de 0,3 a 0,15: la precisión subía a 97,3% pero aparecían
5 respuestas fuera de tema (`eval/resultados_umbral_015.json`). Dejamos 0,3 porque para el
proyecto pesa más no inventar que contestar todo.

Fallas conocidas del modo extractivo: preguntas con palabras que el sitio no usa ("algo para
escuchar música sin cables") o datos que el sitio no publica ("¿abren los lunes?"). El modo con
Claude resuelve mejor las paráfrasis; el set de evaluación es el mismo para comparar.

## Estructura

```
app/        API, rastreador, extractor, índice, motor de respuestas, conectores
widget/     widget.js que se pega en el sitio del cliente
admin/      panel web
scripts/    demo, generador de sitios de ejemplo, capturas
eval/       set de evaluación y resultados
tests/      pruebas automáticas
```

## Variables de entorno

| Variable | Valor por defecto | Para qué |
|---|---|---|
| `ANTHROPIC_API_KEY` | (vacía) | Activa el modo con Claude |
| `SABIO_MODEL` | `claude-haiku-5-5` | Modelo a usar |
| `SABIO_MODE` | `auto` | `extractivo` para forzar el modo sin LLM |
| `SABIO_MIN_COVERAGE` | `0.5` | Cobertura mínima de la pregunta para responder |
| `SABIO_RECRAWL_HOURS` | `24` | Frecuencia de re-rastreo |
| `SABIO_DB` | `data/sabio.db` | Base SQLite |
| `SABIO_DEMO` | `0` | `1` sirve las tiendas de ejemplo y la página de inicio |
| `SABIO_ADMIN_TOKEN` | (vacía) | Si se define, el panel pide esta clave para cargar sitios |
| `SABIO_PUBLIC_URL` | (se detecta en Render y Railway) | Dirección pública del servidor |
| `SABIO_ALLOW_PRIVATE` | `0` | `1` permite rastrear localhost (solo para la demo local) |
