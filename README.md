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

1. **Absorción**: el rastreador (`app/crawler.py`) lee `sitemap.xml` (y los que declara `robots.txt`,
   con las páginas de productos primero), recorre los enlaces internos respetando `robots.txt` y su
   `Crawl-delay`, y extrae el texto útil de cada página (`app/extract.py`). Los productos salen de
   schema.org, de las etiquetas `og:`/`product:price` y de los JSON que traen las páginas adentro
   (`__NEXT_DATA__`, `window.__INITIAL_STATE__`, `<script type="application/json">`). Si detecta Shopify
   o WooCommerce, también trae el catálogo desde la API pública con stock real (`app/connectors.py`).
   Tiendanube necesita el token de la app. Si el sitio empieza a rechazar al rastreador (403, 429 o 503),
   SABIO deja de leer para no sobrecargarlo y lo avisa en el panel.
   - **Sitios hechos con JavaScript** (Angular, React, Vue…): si una página trae menos de 300 caracteres
     de texto útil o ningún producto, y tiene varios `<script>`, se vuelve a cargar con Chromium sin
     ventana (Playwright). Se espera a que termine de cargar, se lee lo que quedó armado y se toman los
     productos de las respuestas JSON de la API del propio sitio. Hay como máximo 2 páginas a la vez,
     20 s por página y 60 páginas por rastreo. Si las primeras 4 no suman nada, deja de usar el navegador.
     El navegador no puede pedir direcciones internas (localhost, redes privadas).
2. **Índice y perfil**: el contenido se divide en fragmentos y se arma un perfil automático del sitio
   con su nombre (`og:site_name`), categorías, vocabulario y datos de contacto (`app/search.py`).
   La búsqueda es **híbrida** y entiende lo que le dicen, no solo la palabra exacta:
   - **Normalización:** sin tildes, sin signos repetidos ("tenés tortas???") ni letras estiradas ("holaaa").
   - **Sinónimos y lunfardo** (`app/textutil.py`): sanguches → sándwiches, zapas → zapatillas,
     compu → computadora/notebook, celu → celular, auris → auriculares, "música sin cables" → auriculares
     inalámbricos, placa de video → VGA/GPU, mandan → envío, etc.
   - **Errores de tipeo:** distancia de edición (1 letra, o 2 en palabras largas) contra el vocabulario
     del sitio, con la misma primera y última letra: notbook → notebook, mause → mouse, maizena → maicena,
     pero libro ≠ libre.
   - **Búsqueda semántica (opcional):** embeddings multilingües (`app/semantic.py`), combinados con BM25
     por *reciprocal rank fusion*. Con Voyage AI no ocupa memoria del servidor; el modelo local
     (multilingual-e5-small) ocupa ~500 MB y no entra en el plan gratuito (ver DEPLOY.md).
   - **Reformulación con Claude (si hay `ANTHROPIC_API_KEY`):** antes de buscar, Claude Haiku 5.5 reescribe
     la pregunta en 3 formas equivalentes con las palabras que probablemente use el sitio, y se busca con todas.
   Las reformulaciones y los embeddings solo cambian el **orden** de los resultados: la evidencia para
   responder (qué parte de la pregunta está escrita en el sitio) se mide siempre contra la pregunta original.
3. **Respuesta** (`app/engine.py`):
   - **Alcance por significado:** si ninguna palabra de la pregunta, ni sus sinónimos o correcciones,
     aparece en el sitio, es fuera de alcance. Excepciones: en una tienda, las consultas de compra (stock,
     precio, envío, cuotas, pago, garantía, cambios, retiro, horario, ofertas, regalos) nunca son fuera de
     alcance; y si la búsqueda semántica encuentra un fragmento que se destaca mucho, se trata como "del
     rubro pero sin el dato". La chocotorta en una tienda de tecnología sigue siendo fuera de alcance.
   - **No inventar:** si la pregunta tiene un término importante que el sitio no menciona ("¿auriculares
     Sony?" en una tienda que vende Sonix, "¿helado de dulce de leche?" en una pastelería sin helados), o
     lo encontrado no cubre la pregunta, responde "no tengo esa información" y ofrece el contacto.
     Contestar con el resto de la pregunta sería inventar. Los embeddings nunca autorizan una respuesta
     por sí solos: medimos que "auriculares Sony" se parece más a "auriculares Sonix" que varias preguntas válidas.
   - Entre los productos se eligen primero los que nombran lo pedido en su título ("placas de video" trae
     las VGA RTX y no un gabinete que las menciona en la descripción). Las recetas y las consultas de envío,
     pago u horario se responden con la página informativa, no con la ficha de un producto.
   - Con `ANTHROPIC_API_KEY` responde Claude Haiku 5.5 con una regla estricta: usar solo el contexto
     y devolver `[SIN_INFO]` si no alcanza. Sin clave funciona en modo extractivo. (Las llamadas ya no
     mandan `temperature`: desde el 21/10/2026 la API la rechaza en todos los modelos.)
   - Cada respuesta lleva el enlace a la página de donde salió.
4. **Panel** (`/admin`): alta de sitios, línea de instalación, métricas, la lista de preguntas
   que el sitio no responde (para que el dueño sepa qué información le falta publicar) y, aparte, las
   preguntas fuera de tema. Si se leyó poco contenido, muestra un aviso y cuántas páginas se leyeron
   con navegador.

## Probarlo en 1 minuto

```bash
pip install -r requirements.txt
python -m playwright install chromium   # opcional: para leer sitios hechos con JavaScript
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
pytest -q                     # 43 pruebas: extracción (JSON-LD, og:, JSON embebido), sitios JavaScript con
                              # Playwright, sinónimos/lunfardo/tipeo, no inventar, búsqueda híbrida, Voyage,
                              # reformulación con Claude (simulada), alcance en tiendas, conectores,
                              # seguridad y freno del rastreador, panel
python eval/run_eval.py http://127.0.0.1:8000   # con la demo corriendo (python scripts/run_demo.py)
```

La prueba con Playwright se saltea si Chromium no está instalado (`python -m playwright install chromium`).
En Windows conviene pasarle `127.0.0.1` a la evaluación: con `localhost` cada pedido tarda unos 2 s extra
en resolver el nombre.

**Set de evaluación** (`eval/eval_set.json`, 100 preguntas sobre TecnoSur y Dulce Pilar):
- 37 preguntas del sitio (el set original);
- 32 coloquiales nuevas: sinónimos, lunfardo, errores de tipeo, signos repetidos ("tenés tortas???",
  "cuanto sale la compu?", "precio de la notbook", "tienen sanguches de miga?");
- 31 fuera de tema: las 18 originales y 13 nuevas **parecidas al rubro**, las más fáciles de contestar
  mal ("¿tienen auriculares Sony?", "¿tienen helado de dulce de leche?", "receta de tiramisú");
- 5 consultas de compra vagas ("¿tenés algo para regalar?").

**Antes y después** (modo extractivo, mismos sitios rastreados de cero, octubre de 2026):

| Indicador | Antes | Después (sin embeddings) | Después (embeddings locales) |
|---|---|---|---|
| Precisión, set original (37) | 89,2% | **91,9%** | 91,9% |
| Precisión, coloquiales (32) | 71,9% | **90,6%** | 90,6% |
| Rechazo correcto, fuera de tema (31) | 87,1% | **100%** | 100% |
| — de las parecidas al rubro (13) | 69,2% | **100%** | 100% |
| **Respuestas inventadas** | **4** | **0** | **0** |
| Vagas atendidas sin rechazar (5) | 40% | 100% | 100% |
| Latencia mediana / p95 | 29 / 40 ms | 19 / 39 ms | 34 / 60 ms |
| Memoria del servidor | 62 MB | 70 MB | **566 MB** |

Archivos: `eval/resultados_antes_busqueda_hibrida.json`, `eval/resultados.json` (sin embeddings, la
configuración de Render) y `eval/resultados_embeddings_locales.json`. En estos sitios de ejemplo lo que
movió los números fue la parte léxica (normalización, sinónimos, tipeo, cobertura por grupos de sinónimos
y la regla de no contestar con un término ausente). Los embeddings locales mejoraron el orden en algunos
casos ("música sin cables" trae primero los auriculares), pero no cambiaron las métricas y suman ~500 MB.
El modo con reformulación de Claude está probado con pruebas simuladas; no se midió con la API real porque
no tenemos clave.

Fallas que quedan (todas responden "no tengo esa información", ninguna inventa): "¿me lo mandan a
Mendoza?" (Mendoza no figura), "¿cámara web para zoom?", "¿abren los lunes?" y "¿atienden los domingos?"
(el sitio dice "de martes a domingo", hay que deducirlo), "¿tienen garantía?" (contesta con la página
"Quiénes somos" en lugar de "Cambios y devoluciones") y "música sin cables" (encuentra los auriculares pero
no muestra la palabra "Bluetooth" que espera la evaluación).

**Tiendas reales** (octubre de 2026, sin navegador ni embeddings, como en Render gratis, máximo 50 páginas).
De 78 candidatas verificadas, la mayoría bloquea rastreadores (403, 429, captcha) o arma todo con
JavaScript (VTEX, Magento). Estas cinco permiten rastrear y publican sus productos en el HTML o en una API:

| Tienda | Rubro | Plataforma | Páginas / productos | Stock | Envíos | Fuera de tema |
|---|---|---|---|---|---|---|
| hardcorecomputacion.com.ar | Tecnología | WooCommerce | 50 / 750 | "¿placas de video?" → 3 VGA RTX con stock y precio | "¿a Córdoba?" → sin_info | chocotorta → fuera de alcance |
| bensimon.com.ar | Ropa | Tiendanube | 50 / 76 | "¿buzos en stock?" → 3 buzos con precio | "¿al interior?" → sin_info (no publica envíos) | "¿placas de video?" → fuera de alcance |
| felfort.com.ar | Golosinas | WooCommerce | 50 / 152 | "¿bombones Marroc?" → en stock, $55.629 | "¿hacen envíos?" → "envíos a todo el país, gratis desde $70.000" | "¿zapatillas?" → fuera de alcance |
| cuspide.com | Librería | WooCommerce | 50 / 1.023 | "¿agendas 2027?" → 3 agendas con precio | "¿cuánto tarda?" → sin_info | "¿notebooks?" → fuera de alcance |
| cafemartinez.com | Café | Tiendanube | 50 / 98 | "¿café en grano?" → 3 cafés con stock | "¿a todo el país?" → sin_info (no lo publica) | "¿libros?" → fuera de alcance |

Estas pruebas encontraron problemas que el set de ejemplo no mostraba y que se corrigieron: "placas de video"
traía placas de red y después un gabinete; "¿venden libros?" en Café Martínez devolvía alfajores (la
corrección de tipeo confundía "libro" con "libre"); "¿envíos al interior?" mostraba la descripción de un
zapato con "interior de cuero"; nombres de tienda mal detectados y teléfonos falsos tomados de códigos de producto.

**Prueba con una tienda real hecha con JavaScript** (compragamer.com, Angular, octubre de 2026, máximo
50 páginas). Sin navegador, SABIO solo leía la portada: 1 página, 0 productos, y respondía "fuera de
alcance" a "¿tienen stock?". Con navegador leyó 25 páginas (17 renderizadas) y 500 productos en 56 s:
- "¿tienen stock de placas de video?" → respondida: tres placas con stock y precio.
- "¿hacen envíos a Córdoba?" → sin_info con el contacto. Córdoba no figura en el sitio y SABIO prefiere no afirmarlo.
- "me das la receta de la chocotorta" → fuera de alcance.

Después de ese rastreo el firewall del sitio empezó a responder 403. Por eso ahora el rastreador
respeta `Crawl-delay` y frena ante 403/429/503. El pico de memoria medido fue de ~1 GB (Python + Chromium
con 2 páginas), lo que no entra en el plan gratuito de Render (ver DEPLOY.md). Limitación conocida: los
productos que salen de la API de la portada enlazan a la portada, porque la API no trae la URL de cada producto.

Probamos bajar el umbral de cobertura de 0,3 a 0,15: la precisión subía a 97,3% pero aparecían
5 respuestas fuera de tema (`eval/resultados_umbral_015.json`). Dejamos 0,3 porque para el
proyecto pesa más no inventar que contestar todo.


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
| `SABIO_RENDER_JS` | `auto` | `auto`: usa navegador solo en páginas con poco contenido; `on`: siempre; `off`: nunca |
| `SABIO_RENDER_MAX` | `60` | Máximo de páginas renderizadas con navegador por rastreo |
| `SABIO_EMBEDDINGS` | `auto` | Búsqueda semántica: `auto` (Voyage si hay clave), `voyage`, `local` (~500 MB, `pip install -r requirements-embeddings-local.txt`) u `off` |
| `VOYAGE_API_KEY` | (vacía) | Clave de Voyage AI para los embeddings |
| `SABIO_VOYAGE_MODEL` | `voyage-4-lite` | Modelo de Voyage |
| `SABIO_SEM_FOCUS` | `3.5` | Cuánto tiene que destacarse un fragmento (puntaje z) para tratar una pregunta sin palabras conocidas como "del rubro" |
