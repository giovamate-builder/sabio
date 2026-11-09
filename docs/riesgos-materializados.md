# Riesgos materializados — SABIO

## R-01 · Caída del servidor por falta de memoria al rastrear un sitio grande

**Riesgo identificado:** el servidor corre en el plan gratuito de Render, con **512 MB de memoria**. Un
proceso que pase ese límite es cortado por la plataforma y el servicio se reinicia.

**Cuándo se materializó:** noviembre de 2026, al cargar `https://www.apple.com/la/mac` desde el panel del
sitio publicado. El servidor se cayó durante el rastreo.

**Causa.** La caída no se volvió a reproducir a propósito, para no cargar de nuevo a Apple. El análisis del
código de ese momento (commit `d4a8eea`) muestra varias causas que se suman:
1. **Sin límite de tiempo** para el rastreo completo; solo había 15 s por pedido.
2. **Hasta 300 páginas** por rastreo, y el número llegaba en el pedido sin tope (se podía pedir más).
3. **Se recorría todo el dominio**: la ruta `/la/mac` se ignoraba y el rastreo seguía por todo apple.com,
   que tiene miles de páginas.
4. **Todo en memoria hasta el final**: el texto completo y la lista de enlaces de cada página leída se
   guardaban hasta terminar, y recién ahí se armaba el índice. La cola de direcciones pendientes no tenía
   tope.
5. **Sin límite de tamaño por página**: cada respuesta se leía entera, con hasta 6 páginas procesadas a la vez.
6. **Varios rastreos podían correr en paralelo**, incluido el re-rastreo automático de cada 24 h.

**Impacto:**
- El servicio quedó fuera de línea hasta que Render lo reinició (en el plan gratuito, cerca de un minuto).
- La base de datos del plan gratuito vive en `/tmp`, que no sobrevive a un reinicio. Las tiendas reales
  cargadas para la demo (Felfort, Bensimon y Café Martínez) ya no estaban el 9/11; solo quedaban los dos
  sitios de ejemplo, que se recargan solos. No se puede afirmar que se perdieron por esta caída en
  particular, pero es el comportamiento esperado ante cualquier reinicio.
- Con una base persistente, el sitio habría quedado trabado en "rastreando" después del reinicio, sin poder
  borrarse.

**Respuesta (Bloque 1, commit `2c26b69`):**
- Límite de páginas por rastreo configurable (`SABIO_MAX_PAGES`), que en Render es 60 y que el pedido ya no
  puede superar.
- Tiempo máximo por rastreo (`SABIO_CRAWL_TIMEOUT_S`, 180 s). Si se pasa, el sitio queda en "error" con un
  mensaje claro y se conserva lo leído.
- Un solo rastreo a la vez en todo el servidor (409 si hay otro), compartido con el re-rastreo automático.
- Tope de 2 MB por página (lectura por partes), 50 mil caracteres de texto por página, solo se guardan los
  enlaces de contacto y la cola de pendientes está acotada.
- El rastreo queda dentro de la carpeta de la dirección inicial (`apple.com/la/mac` → `/la/`).
- Al arrancar, los sitios que quedaron en "rastreando" pasan a "error" con el mensaje "El rastreo se
  interrumpió, volvé a rastrear", y los sitios se pueden eliminar desde el panel.

**Verificación:** 8 pruebas automáticas cubren el corte por tiempo (con y sin contenido útil), el límite de
páginas, el rastreo concurrente, el arranque con un sitio trabado, el borrado, el límite a la carpeta
inicial y una página de unos 8 MB. La memoria del servidor en la evaluación pasó de 70 a 72 MB.

**Riesgo residual:**
- Las medidas no se probaron todavía contra un sitio grande real en Render.
- La base en `/tmp` sigue perdiéndose en cada reinicio; una base persistente requiere un disco pago en Render.

**Lección:** en un entorno de 512 MB, todo proceso que dependa de un sitio externo necesita límites de
tiempo, tamaño y cantidad desde el diseño, no después de la primera caída.

## Riesgos relacionados con la memoria que se detectaron antes de materializarse

| Fecha | Qué se midió | Decisión |
|---|---|---|
| Octubre de 2026 | Leer sitios con navegador (Chromium) usa cerca de 1 GB | Navegador desactivado en Render (`SABIO_RENDER_JS=off`); requiere un plan de 2 GB |
| Octubre de 2026 | El modelo local de embeddings lleva el servidor a 566 MB | En Render se usa la API de Voyage AI o solo la búsqueda léxica |

## Otros riesgos materializados

| Riesgo | Qué pasó | Respuesta |
|---|---|---|
| Bloqueo del rastreador por el sitio | Compra Gamer respondió 403 después de un rastreo con navegador, y Hardcore Computación rechaza las IP de Render (403) | Freno ante 403/429/503, respeto de `Crawl-delay`, aviso en el panel; no se intenta esquivar el bloqueo |
| Cambio de la API externa | Desde el 21/10/2026 la API de Claude rechaza `temperature`, y el modo con Claude dejó de funcionar | Se quitó el parámetro (commit `d4a8eea`) |
