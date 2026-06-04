# Performance — RunFoto

Notas de rendimiento medidas a lo largo de las fases. Escala objetivo (año 1):
15-20 eventos/año, hasta 4.000 fotos por evento, ~$20/mes.

## Tiempos medidos

| Operación | Tiempo | Fase | Nota |
|---|---|---|---|
| OCR de dorsales (Paddle + fallback Easy) | ~0.5–2 s/foto | 2 | async en worker |
| Extracción de embedding facial (buffalo_l, CPU) | ~0.18 s/foto | 4 | async en worker |
| Búsqueda por selfie (pgvector HNSW) | ~10 ms | 4 | `Index Scan using face_embedding_hnsw_cos` |
| Búsqueda por dorsal (cacheada en Redis 5 min) | <50 ms | 3 | IDs en cache, no objetos |
| `enforce_event_retention_policy` | ~50 ms | 6 | filtros + updates + audit; corre 1×/noche |
| `delete_event_photos_permanently` (60 fotos) | ~1 s | 6 | + tiempo de borrado en R2 con fotos reales |

Estimación para un evento grande (4.000 fotos): el borrado permanente baja a R2
en lotes de 1.000 keys (~4 requests de `delete_objects`) + un `DELETE` masivo en
DB. Corre de noche en un worker, sin impactar requests de usuarios.

## Optimizaciones ya presentes

- **Búsqueda por dorsal cacheada** 5 min en Redis (IDs, no objetos — para no
  cachear URLs firmadas).
- **`select_related` / `prefetch_related`** en galerías y cola de aprobación
  (cero N+1; verificado con Django Debug Toolbar en dev).
- **Índice HNSW** de pgvector para la búsqueda facial (vs scan secuencial).
- **Paginación** a 60 fotos (galería) / 20 (cola de aprobación).
- **WhiteNoise** con `CompressedManifestStaticFilesStorage` (cache-busting + gzip/brotli).
- **CONN_MAX_AGE=60** (conexiones de DB persistentes).

## Stress test (pendiente / opcional)

El stress test con `locust` (50 usuarios concurrentes, 5 min) NO se corrió todavía
(es opcional y `locust` no se agregó como dependencia para no inflar la imagen).
Cuando haya tráfico real o antes de un evento grande, vale la pena:

- Simular: landing → búsqueda por dorsal → lightbox → descarga de ZIP.
- Verificar: p95 < 1 s, rate limits efectivos, sin crecimiento de queries (cache OK),
  sin memory leaks.

Dado el volumen objetivo (un evento a la vez, picos de búsquedas el día de la
carrera), la prioridad real es la RAM del servicio web para la búsqueda facial
(ver `docs/runbook.md` → Incidentes), no la concurrencia de requests.
