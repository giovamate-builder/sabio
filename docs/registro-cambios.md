# Registro de cambios — SABIO

Cada cambio indica qué se hizo, por qué, su impacto en el alcance y su estado. Los commits y sus fechas
están en `docs/fechas-reales.md`. Los resultados de la evaluación antes de los bloques de noviembre están en
`docs/linea-base.json` y los finales en `eval/resultados.json`.

Regla aplicada en todos los bloques: el asistente nunca inventa. Después de cada bloque se corrió `pytest -q`
(en verde) y `eval/run_eval.py` (respuestas inventadas = 0 y rechazo correcto = 1,0). Los casos existentes de
`eval/eval_set.json` no se modificaron; solo se agregaron casos.

## Cambios de alcance anteriores (octubre de 2026)

### C-01 · Publicación inicial en Render — `9858439`
- **Qué:** versión inicial del asistente (FastAPI + widget), con búsqueda por palabras (BM25), modo demo y
  despliegue en el plan gratuito de Render con `render.yaml`.
- **Impacto en el alcance:** línea de partida.
- **Estado:** publicado.

### C-02 · Lectura de tiendas hechas con JavaScript — `ee13697`
- **Qué:** si una página trae poco contenido, se vuelve a cargar con un navegador sin ventana (Playwright)
  y se leen los productos de los JSON que trae la página. También se agregó el freno del rastreo ante
  bloqueos (403/429/503) y el respeto de `Crawl-delay`.
- **Por qué:** tiendas reales como Compra Gamer (Angular) se leían vacías: 1 página y 0 productos.
- **Impacto en el alcance:** ampliación. Con el navegador, Compra Gamer pasó a 25 páginas y 500 productos.
  El navegador usa cerca de 1 GB y no entra en el plan gratuito, así que en Render quedó desactivado
  (`SABIO_RENDER_JS=off`); ver `docs/riesgos-materializados.md`.
- **Estado:** publicado, con el navegador desactivado en Render.

### C-03 · De BM25 a búsqueda híbrida con embeddings — `d4a8eea`
- **Qué:** la búsqueda pasó de solo BM25 a una búsqueda híbrida: normalización (tildes, signos repetidos),
  diccionario de sinónimos y lunfardo, corrección de errores de tipeo, embeddings multilingües opcionales
  combinados con BM25 por *reciprocal rank fusion* y reformulación de la pregunta con Claude Haiku cuando hay
  clave. El control de alcance pasó a ser por significado sin perder la regla de no inventar.
- **Por qué:** el asistente solo entendía la palabra exacta. "Sanguches", "zapas", "compu" o "tenés
  tortas???" no encontraban lo que el sitio sí tenía, y el set ampliado mostró 4 respuestas inventadas.
- **Impacto en el alcance:** cambio de alcance. Se sumó la búsqueda semántica, pero el modelo local
  (multilingual-e5-small) llevó el servidor a 566 MB y no entra en 512 MB, así que en Render se usa la API
  de Voyage AI cuando hay clave, o solo la parte léxica. Resultado: precisión 89,2% → 91,9%, coloquial
  71,9% → 90,6%, inventadas 4 → 0. También se corrigió que las llamadas a Claude mandaban `temperature`, que
  la API rechaza desde el 21/10/2026.
- **Estado:** publicado (sin embeddings en Render hasta cargar `VOYAGE_API_KEY`).

## Bloques de noviembre de 2026 (rama `mejoras-final`)

### Bloque 1 (P1) · Estabilidad del rastreo — `2c26b69`
- **Qué:**
  - límite de páginas configurable (`SABIO_MAX_PAGES`, 300 por defecto, 60 en Render), que también acota
    el `max_pages` del pedido;
  - tiempo máximo por rastreo (`SABIO_CRAWL_TIMEOUT_S`, 180 s), conservando lo leído;
  - un solo rastreo a la vez, con 409, compartido con el re-rastreo automático;
  - al arrancar, los sitios trabados en "rastreando" pasan a "error";
  - `DELETE /api/sites/{id}` y botón "Eliminar sitio" en el panel (los sitios de ejemplo responden 403);
  - para la memoria: tope de 2 MB por página, 50 mil caracteres de texto por página, solo enlaces de
    contacto guardados, cola de pendientes acotada y rastreo limitado a la carpeta de la dirección inicial.
- **Por qué:** el servidor se cayó rastreando apple.com/la/mac (ver `docs/riesgos-materializados.md`); los
  sitios quedaban trabados y no se podían borrar.
- **Impacto en el alcance:** sin cambio de funcionalidad visible para el visitante; agrega el borrado de
  sitios. Decisiones tomadas con el equipo: un rastreo cortado por tiempo responde con lo leído; el rastreo
  queda dentro de la carpeta inicial.
- **Estado:** terminado en la rama, sin publicar. 51 pruebas; evaluación igual a la línea de base.

### Bloque 2 (P1) · Seguridad del panel — `233a2d7`
- **Qué:** la clave del panel se exige también para ver sitios y métricas, y se compara con
  `hmac.compare_digest`. Sin `SABIO_ADMIN_TOKEN`, el panel queda deshabilitado salvo con `SABIO_ENV=dev`, con
  un aviso en el log. `/api/chat`, `/widget.js` y `/api/health` siguen públicos. El panel pide la clave una
  vez y muestra los errores de conexión.
- **Por qué:** sin clave cualquiera cargaba sitios, y aun con clave la lista de sitios y las métricas (con
  conversaciones) eran públicas.
- **Impacto en el alcance:** ajuste. Se deshabilitó también la lectura sin clave (más estricto que lo
  pedido) para no exponer conversaciones.
- **Estado:** terminado en la rama. 65 pruebas; evaluación igual a la línea de base.

### Bloque 3 (P1) · Calidad de respuestas — `b9e9cd8`
- **Qué:**
  - preguntas generales ("¿qué venden?") responden con la descripción, las categorías y 5 productos del
    sitio, con enlace al inicio;
  - envíos a un destino que el sitio no nombra muestran la página de envíos aclarando que ese destino no
    figura, más el contacto;
  - se quitan las líneas repetidas en más del 60% de las páginas (sitios de 5 páginas o más);
  - todas las fuentes salen como URL absoluta.
- **Por qué:** "¿qué venden?" pedía más detalle, "¿me lo mandan a Córdoba?" no mostraba la información de
  envíos, las respuestas empezaban con el eslogan del sitio y las fuentes mezclaban rutas relativas y absolutas.
- **Impacto en el alcance:** mejora de calidad dentro del alcance. Se agregaron 9 casos a la evaluación.
  Precisión del set original 91,9% → 94,6%; negocio y envíos 100%.
- **Estado:** terminado en la rama. 78 pruebas.

### Bloque 4 (P1) · Página /presentacion — `928833a`
- **Qué:** página para proyector con TecnoSur y Dulce Pilar lado a lado, preguntas preparadas, etiqueta de
  color por estado, fuente y tiempo de cada respuesta, y tarjetas con los resultados de la evaluación leídos
  de `GET /api/eval`. Las sesiones internas (`presentacion`, `eval`, `verificacion`) no cuentan en las
  métricas del panel.
- **Por qué:** mostrar el proyecto en vivo sin depender de abrir cada tienda.
- **Impacto en el alcance:** ampliación (entregable de presentación).
- **Estado:** terminado en la rama. 82 pruebas.

### Bloque 5 (P2) · Planes y límites de uso — `c115e0f`
- **Qué:** planes emprendedor (500 conversaciones/mes), pyme (2.000) y pro (8.000), con migración de la base
  que conserva los datos. Uso del mes en hora de Argentina, avisos al 80% y al 100%, cambio de plan con
  clave y, al 100%, el contacto del negocio en lugar del asistente.
- **Por qué:** modelo de negocio del proyecto.
- **Impacto en el alcance:** ampliación. Decisión propia informada al equipo: una conversación ya empezada
  en el mes puede terminar aunque se llegue al límite.
- **Estado:** terminado en la rama. 89 pruebas.

### Bloque 6 (P2) · Satisfacción y reporte — `39074fb`
- **Qué:** botones 👍/👎 en el widget, `POST /api/feedback` (un voto por mensaje, validando sitio y
  conversación), % de respuestas útiles en las métricas y reporte mensual en CSV con botón en el panel.
- **Por qué:** medir la satisfacción y darle al dueño un reporte para decidir qué publicar.
- **Impacto en el alcance:** ampliación. Se agregó la validación de la conversación en el voto (no estaba
  pedida) porque los identificadores de mensaje son correlativos.
- **Estado:** terminado en la rama. 92 pruebas.

### Bloque 7 (P2) · Widget personalizable y derivación — `6da6e6c`
- **Qué:** atributos `data-color`, `data-nombre`, `data-bienvenida` y `data-posicion` (siguen funcionando los
  anteriores) y botón "Hablar por WhatsApp" cuando el asistente no tiene la respuesta.
- **Por qué:** que cada negocio adapte el widget y no pierda la consulta cuando el sitio no tiene el dato.
- **Impacto en el alcance:** ampliación. El botón de WhatsApp también aparece al alcanzar el límite del plan.
- **Estado:** terminado en la rama. 96 pruebas.

### Bloque 8 (P2) · Integraciones y legales — `084fd5b`
- **Qué:** plugin mínimo de WordPress/WooCommerce, instructivos de Tiendanube y Shopify, páginas
  `/terminos` y `/privacidad` en el marco de la Ley 25.326, borrado automático de conversaciones pasados
  `SABIO_RETENCION_DIAS` (365) y enlace "Privacidad" en el widget.
- **Por qué:** facilitar la instalación en las plataformas más usadas y cumplir con la información que exige
  la ley de datos personales.
- **Impacto en el alcance:** ampliación. Se implementó el borrado automático para que lo que dice la página
  de privacidad sea verdad.
- **Estado:** terminado en la rama. 103 pruebas. **Pendiente:** el plugin de WordPress no se probó en una
  instalación real (no había PHP disponible) y los textos legales deben ser revisados por alguien con
  formación en derecho antes de darlos por definitivos.

## Estado general

Los 8 bloques están en la rama `mejoras-final`, sin push ni merge a `main`. Render despliega solo desde
`main`, así que nada de esto está publicado todavía.
