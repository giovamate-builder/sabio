# Fechas reales — SABIO

Fechas y horas de cada commit, sacadas de `git log` (hora de Argentina, UTC-3), para comparar el Gantt
planificado contra el real. El inicio de cada bloque es el commit anterior; el del Bloque 1 es la
creación de la rama `mejoras-final` (sacada de `git reflog`). El intervalo incluye el tiempo de espera de
la aprobación del equipo entre bloques.

## Trabajo anterior (rama `main`)

| Commit | Fecha y hora | Cambio |
|---|---|---|
| `9858439` | 2026-10-23 10:14:19 | SABIO: versión inicial lista para Render |
| `ee13697` | 2026-10-23 12:03:17 | Leer tiendas hechas con JavaScript y mejorar el control de alcance |
| `d4a8eea` | 2026-10-23 13:22:05 | Búsqueda híbrida: sinónimos, lunfardo, errores de tipeo y embeddings sin inventar |

## Bloques de noviembre (rama `mejoras-final`)

Rama creada desde `main` (`d4a8eea`) el 2026-11-09 18:17:15.

| Bloque | Commit | Inicio | Fin (commit) | Duración |
|---|---|---|---|---|
| Bloque 1: estabilidad del rastreo | `2c26b69` | 2026-11-09 18:17:15 | 2026-11-09 18:29:54 | 12 min 39 s |
| Bloque 2: seguridad del panel | `233a2d7` | 2026-11-09 18:29:54 | 2026-11-09 18:33:21 | 3 min 27 s |
| Bloque 3: calidad de respuestas | `b9e9cd8` | 2026-11-09 18:33:21 | 2026-11-09 18:38:48 | 5 min 27 s |
| Bloque 4: página /presentacion | `928833a` | 2026-11-09 18:38:48 | 2026-11-09 18:42:07 | 3 min 19 s |
| Bloque 5: planes y límites de uso | `c115e0f` | 2026-11-09 18:42:07 | 2026-11-09 18:47:01 | 4 min 54 s |
| Bloque 6: satisfacción y reporte | `39074fb` | 2026-11-09 18:47:01 | 2026-11-09 18:51:07 | 4 min 06 s |
| Bloque 7: widget personalizable y derivación a WhatsApp | `6da6e6c` | 2026-11-09 18:51:07 | 2026-11-09 18:54:01 | 2 min 54 s |
| Bloque 8: integraciones y legales | `084fd5b` | 2026-11-09 18:54:01 | 2026-11-09 18:59:32 | 5 min 31 s |

El commit de cierre que agrega este archivo no figura en la tabla. Su fecha se obtiene con:

```bash
git log -1 --date=format:'%Y-%m-%d %H:%M:%S' --format='%h %ad %s'
```

Para regenerar la tabla completa:

```bash
git log --reverse --date=format:'%Y-%m-%d %H:%M:%S %z' --format='%h|%ad|%s'
```
