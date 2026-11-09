=== SABIO Chat ===
Contributors: equiposabio
Tags: chat, asistente, woocommerce, tienda, preguntas frecuentes
Requires at least: 5.8
Tested up to: 6.8
Requires PHP: 7.4
Stable tag: 1.0.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Agrega el asistente SABIO a tu tienda: responde a tus clientes solo con la información publicada en tu sitio.

== Description ==

SABIO lee tu sitio (productos, precios, stock, envíos, medios de pago y preguntas frecuentes) y responde a los
visitantes únicamente con lo que está publicado. Si un dato no está en tu sitio, lo dice y ofrece tu contacto
en lugar de inventar una respuesta.

En tiendas WooCommerce, SABIO lee además el catálogo con stock real desde la API pública de WooCommerce
(Store API), sin configurar nada.

Este plugin solo inserta la línea del widget en el pie de las páginas. El asistente corre en tu servidor SABIO.

== Installation ==

1. En el panel de SABIO (`https://TU-SERVIDOR/admin`), cargá la dirección de tu tienda y tocá **Absorber sitio**.
2. Copiá el ID del sitio: es el valor de `data-site` en la línea de instalación (por ejemplo `s_1a2b3c4d5e`).
3. Subí la carpeta `sabio-chat` a `wp-content/plugins/` (o comprimila en un .zip y usá **Plugins › Añadir nuevo › Subir plugin**).
4. Activá **SABIO Chat** en **Plugins**.
5. En **Ajustes › SABIO Chat**, completá la URL del servidor y el ID del sitio, y guardá.
6. Abrí tu tienda: aparece la burbuja de chat abajo a la derecha.

== Frequently Asked Questions ==

= ¿El widget usa cookies o pide datos a mis clientes? =

No. No usa cookies ni pide datos personales. Ver `https://TU-SERVIDOR/privacidad`.

= ¿Cómo cambio el color o el título? =

Por ahora el plugin inserta la línea básica. Para personalizarla (`data-color`, `data-nombre`,
`data-bienvenida`, `data-posicion`) podés pegar la línea a mano con un plugin de código en el pie, como se
explica en el README de SABIO.

= No aparece la burbuja =

Revisá que la URL del servidor no tenga la barra final y que el ID del sitio sea el del panel. Si usás un plugin
de caché, vaciala después de guardar los ajustes.

== Changelog ==

= 1.0.0 =
* Primera versión: página de ajustes y widget en el pie del sitio.
