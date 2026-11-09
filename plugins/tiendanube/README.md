# SABIO en Tiendanube

## 1. Cargar la tienda en SABIO

En el panel de SABIO (`https://TU-SERVIDOR/admin`), cargá la dirección de tu tienda (por ejemplo
`https://mitienda.mitiendanube.com` o tu dominio propio) y tocá **Absorber sitio**. SABIO lee los productos
desde las páginas de la tienda (Tiendanube publica cada producto con schema.org), así que el asistente ya
funciona sin el token. Copiá la línea de instalación que aparece.

## 2. Instalar el widget

1. En el administrador de Tiendanube, entrá a **Configuración › Códigos externos**.
2. En el campo para scripts del sitio, pegá la línea de instalación:

   ```html
   <script src="https://TU-SERVIDOR/widget.js" data-site="ID_DEL_SITIO" defer></script>
   ```

3. Guardá y abrí tu tienda: aparece la burbuja de chat abajo a la derecha.

Si tu plan o tu tema no tiene esa sección, la línea también se puede pegar antes de `</body>` desde
**Tienda online › Diseño › Editar código avanzado** (en los temas que lo permiten).

Podés personalizarla con `data-color`, `data-nombre`, `data-bienvenida` y `data-posicion` (ver el README de SABIO).

## 3. Stock en vivo (opcional)

Sin token, SABIO conoce el stock que se ve en las páginas cuando las leyó (se vuelven a leer cada día). Con el
token de la API de Tiendanube, consulta el stock y el precio **en el momento** de cada pregunta.

Para obtener el token hace falta una app de Tiendanube:

1. Creá una app en el [portal de socios de Tiendanube](https://partners.tiendanube.com) con permiso de lectura
   de productos (`read_products`).
2. Instalala en tu tienda. Al autorizarla, Tiendanube devuelve un `access_token` y el `user_id`, que es el ID
   de la tienda.
3. Cargá la tienda en SABIO con esos datos. Por ahora se hace por la API, con la clave del panel:

   ```bash
   curl -X POST https://TU-SERVIDOR/api/sites \
        -H "Content-Type: application/json" -H "X-Admin-Token: TU_CLAVE_DEL_PANEL" \
        -d '{"url": "https://mitienda.com.ar", "platform": "tiendanube",
             "creds": {"store_id": "123456", "token": "ACCESS_TOKEN"}}'
   ```

   Si la tienda ya estaba cargada, eliminala desde el panel antes de volver a cargarla con el token.

El token se guarda en el servidor de SABIO y la API nunca lo devuelve (`GET /api/sites/{id}` lo omite).
Usá un token de **solo lectura**.
