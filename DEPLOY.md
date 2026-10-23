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
