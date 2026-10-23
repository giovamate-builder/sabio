# Publicar SABIO en internet y mostrarlo

## Opción recomendada: Render (gratis, unos 10 minutos)

1. Subí esta carpeta a un repositorio de GitHub (puede ser privado).
2. Entrá a https://render.com con tu cuenta de GitHub.
3. **New › Blueprint** y elegí el repositorio. Render lee el archivo `render.yaml` y arma todo solo.
4. Tocá **Deploy**. Cuando termine, te da una dirección del tipo `https://sabio-xxxx.onrender.com`.
5. Abrí esa dirección: aparece la página de inicio con las dos tiendas de ejemplo y el panel.

Variables opcionales (en Render: el servicio › Environment):

| Variable | Para qué |
|---|---|
| `ANTHROPIC_API_KEY` | Activa las respuestas redactadas por Claude. Sin esto funciona igual, en modo extractivo. |
| `SABIO_ADMIN_TOKEN` | Clave para que nadie más pueda cargar sitios desde el panel. Recomendado si compartís el link. |
| `SABIO_RENDER_JS` | `off` en el plan gratuito; `auto` con 2 GB o más (ver abajo). |
| `VOYAGE_API_KEY` | Activa la búsqueda semántica con Voyage AI (ver abajo). Sin esto, SABIO busca por palabras, sinónimos y errores de tipeo. |

### Sitios hechos con JavaScript y memoria

La imagen de Docker trae Chromium (Playwright) para leer tiendas armadas con JavaScript, como
Compra Gamer. Pero leer con navegador usa cerca de **1 GB de memoria** (medido con 2 páginas en paralelo),
y el plan gratuito de Render tiene **512 MB**. Por eso `render.yaml` deja `SABIO_RENDER_JS=off`: SABIO
funciona igual con los sitios que publican su contenido en el HTML, y en el panel avisa cuando un sitio
se leyó con poco contenido.

Para activarlo hace falta un plan con más memoria. **Starter (7 USD/mes) no alcanza**, porque también
tiene 512 MB. El más barato que alcanza es **Standard: 2 GB de RAM y 1 CPU, 25 USD/mes**. Además no se
duerme. Para pasarse:
1. En Render: servicio **sabio** › **Settings** › **Instance Type** › **Standard**.
2. En `render.yaml`, cambiá `plan: free` por `plan: standard` y `SABIO_RENDER_JS` de `"off"` a `"auto"`,
   y hacé push. Render vuelve a publicar solo.
3. En el panel, **Volver a rastrear** los sitios hechos con JavaScript.

### Búsqueda semántica (embeddings) y memoria

SABIO entiende sinónimos, lunfardo y errores de tipeo sin usar memoria extra. La búsqueda semántica con
embeddings es opcional, y medimos dos formas de usarla:

| Opción | Memoria del servidor | Costo | Entra en Render gratis |
|---|---|---|---|
| Sin embeddings (por defecto) | ~70 MB | gratis | Sí |
| Modelo local multilingual-e5-small (ONNX, cuantizado) | **~566 MB** | gratis | **No** (512 MB) |
| API de Voyage AI, modelo `voyage-4-lite` | ~70 MB | 0,02 USD por millón de tokens, con 200 millones gratis | Sí |

El modelo local pesa 118 MB en disco, pero su tabla de vocabulario (250 mil palabras) se carga en float32 y
ocupa 384 MB: ninguna opción de onnxruntime lo baja. Por eso en Render conviene Voyage. Indexar un sitio de
50 páginas son unos 100 mil tokens: menos de un centavo de dólar, y en la práctica gratis con los 200
millones de tokens incluidos. Para activarlo:
1. Creá una cuenta en https://www.voyageai.com y generá una API key.
2. En Render: servicio **sabio** › **Environment** › `VOYAGE_API_KEY` = la clave › **Save**.
3. Volvé a rastrear los sitios desde el panel para que se calculen los vectores. `/api/health` muestra
   `"embeddings": "voyage:voyage-4-lite"`.

En la evaluación, los embeddings no cambiaron las métricas en los sitios de ejemplo: lo que más mejoró
fue la parte por palabras. Ver la tabla "Antes y después" en el README.

### Tiendas reales para la demo

Verificamos que estas tiendas permiten rastrear (`robots.txt`), no bloquean y publican sus productos sin
JavaScript. Las tres primeras son las que mejor funcionaron y las cargamos en Render:
- **hardcorecomputacion.com.ar** (tecnología, WooCommerce): "¿tienen stock de placas de video?"
- **felfort.com.ar** (golosinas, WooCommerce): "¿tienen bombones Marroc?", "¿hacen envíos?"
- **bensimon.com.ar** (ropa, Tiendanube): "¿tenés buzos en stock?"
- cuspide.com (librería) y cafemartinez.com (café) también funcionan.

Ojo: en el plan gratuito, los sitios cargados desde el panel se borran cuando el servicio se reinicia o
se vuelve a publicar. Hay que volver a cargarlos desde `/admin` antes de mostrarlos.

**Ojo con el plan gratuito:** el servicio se duerme a los 15 minutos sin uso y tarda cerca de un minuto en
despertar. Abrí el link un par de minutos antes de mostrarlo. Además, los sitios que cargues desde el panel
se borran cuando el servicio se reinicia; las dos tiendas de ejemplo se vuelven a cargar solas.

## Alternativa: Railway

1. Instalá la CLI (`npm i -g @railway/cli`) y hacé `railway login`.
2. En esta carpeta: `railway init` y después `railway up`. Usa el `Dockerfile` (ya trae el modo demo activado).
3. En el panel de Railway: Settings › Networking › Generate Domain.

## Sin publicar nada: tu compu + un túnel

```bash
pip install -r requirements.txt
SABIO_DEMO=1 uvicorn app.main:app --port 8000
# en otra terminal, para tener un link público temporal:
npx cloudflared tunnel --url http://localhost:8000
```

## Instalarlo en una página web real

1. Con SABIO publicado, entrá a `/admin`, cargá la dirección del sitio y tocá **Absorber sitio**.
2. Copiá la línea que aparece:

```html
<script src="https://sabio-xxxx.onrender.com/widget.js" data-site="ID_DEL_SITIO" defer></script>
```

3. Pegala antes de `</body>`:
   - **HTML propio:** directamente en cada página (o en la plantilla común).
   - **WordPress / WooCommerce:** con un plugin de "insertar código" (por ejemplo WPCode), en el pie del sitio.
   - **Tiendanube:** en la sección de códigos externos o scripts de la configuración de la tienda.
   - **Shopify:** Tienda online › Temas › Editar código › `theme.liquid`, antes de `</body>`.
   - **Wix:** Configuración › Código personalizado, en el pie del cuerpo.

Opcionales en la misma línea: `data-color="#c2410c"`, `data-title="Asistente de Mi Tienda"`, `data-position="left"`.

## Guion para mostrarlo en clase (5 minutos)

1. Página de inicio: qué es SABIO en una frase.
2. **TecnoSur**: "¿tenés stock de los auriculares Sonix?" → stock, precio y link.
3. Misma tienda: "me das la receta de la chocotorta" → la rechaza y ofrece el contacto.
4. **Dulce Pilar**: la misma pregunta → da la receta y cita la página.
5. **Panel**: la línea de instalación, las métricas y las preguntas que el sitio no responde.
6. Cierre: resultados del set de evaluación (`eval/resultados.json`): 91,9% de precisión, 100% de rechazo
   de preguntas fuera de tema y 0 respuestas inventadas.
