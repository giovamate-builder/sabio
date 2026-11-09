# SABIO en Shopify

## 1. Cargar la tienda en SABIO

En el panel de SABIO (`https://TU-SERVIDOR/admin`), cargá la dirección de tu tienda y tocá **Absorber sitio**.
SABIO detecta Shopify solo y lee el catálogo con precio y disponibilidad desde `/products.json`, que Shopify
publica sin credenciales. Copiá la línea de instalación que aparece.

## 2. Instalar el widget en `theme.liquid`

1. En el administrador de Shopify, entrá a **Tienda online › Temas**.
2. En el tema publicado, abrí el menú **…** y elegí **Editar código**.
3. En la carpeta **layout**, abrí `theme.liquid`.
4. Buscá la etiqueta `</body>` (casi al final) y pegá justo antes:

   ```html
   <script src="https://TU-SERVIDOR/widget.js" data-site="ID_DEL_SITIO" defer></script>
   ```

5. Tocá **Guardar** y abrí tu tienda: aparece la burbuja de chat abajo a la derecha.

Podés personalizarla con `data-color`, `data-nombre`, `data-bienvenida` y `data-posicion` (ver el README de SABIO).

Si cambiás de tema, repetí el paso 2 en el tema nuevo: cada tema tiene su propio `theme.liquid`.

## Stock en vivo

No hace falta configurar nada: en cada pregunta sobre un producto, SABIO vuelve a consultar `/products.json`
(con 5 minutos de caché) para responder con el precio y la disponibilidad del momento.
