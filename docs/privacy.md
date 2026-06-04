# Manejo de datos biométricos — RunFoto

> Documento técnico de cómo RunFoto procesa datos faciales. Complementa la
> página pública `/privacidad/`. Audiencia: el admin y cualquier auditoría.

## Principios (CLAUDE.md §3 — no negociables)

1. **El selfie del usuario NUNCA se guarda.** Ni el archivo ni su embedding.
   Se procesa en memoria durante el request HTTP y se descarta.
2. **El embedding del selfie NUNCA toca Celery/Redis.** La búsqueda por selfie
   y el borrado de datos son **síncronos**: extraen el embedding en RAM, hacen
   la query pgvector, y responden. A las tasks (borrado pesado) sólo se les
   pasan `photo_ids`, que no son biométricos.
3. **Nunca se loggea un embedding completo.** Sólo metadatos: "embedding
   extracted dims=512", contadores, hashes de IP.
4. **Nunca se expone un embedding por JSON al cliente.**
5. **IP siempre anonimizada/hasheada** antes de cualquier persistencia.

## Qué se guarda y dónde

| Dato | Dónde | Cuánto tiempo |
| --- | --- | --- |
| Embeddings de caras de las fotos del evento | `photos_faceembedding` (Postgres + pgvector) | 90 días desde el último match |
| Bounding box de cada cara | `photos_faceembedding.bbox` (JSON) | igual que el embedding |
| Edad estimada / flag `is_minor` | `photos_faceembedding` | igual |
| Selfie de búsqueda | **en ningún lado** | 0 (se descarta tras el request) |
| Embedding del selfie | **en ningún lado** | 0 (vive en RAM durante el request) |
| IP del buscador | hasheada (sha256) en logs/rate-limit | TTL del rate-limit (horas) |

## Flujo: búsqueda por selfie

1. Usuario sube selfie → `SelfieSearchView.post` (síncrono).
2. `embedding_from_bytes(selfie.read())` extrae el embedding EN MEMORIA.
3. `search_faces_by_similarity` hace la query pgvector (cosine, umbral 0.55).
4. Se actualiza `last_matched_at` de los embeddings que matchearon (retención).
5. Se renderizan los resultados. El embedding del selfie sale de scope.
6. **Nada del selfie se persiste.** Verificado por
   `tests/public/test_selfie_search.py::test_selfie_search_does_not_persist_query_embedding`.

## Flujo: borrado de datos (`/privacidad/borrar-mis-datos/`)

1. Usuario sube selfie + marca la confirmación.
2. `DeleteMyDataView.post` (síncrono) extrae el embedding EN MEMORIA.
3. `find_matching_photo_ids` busca en TODOS los eventos (umbral 0.62, estricto).
4. Obtiene `photo_ids`; el embedding sale de scope.
5. Dispara `delete_photos_for_request(deletion_id, photo_ids)` — sólo IDs.
6. La task borra: embeddings → bibs → archivos R2 (original+preview+thumb) →
   registros `Photo`. Crea `AuditLog` con la acción `privacy.data_deleted`.

## Detección de menores

- Caras estimadas **< 16 años** → `is_minor=True` → blur gaussiano automático
  en el preview y thumbnail (radius 30, +20% de margen sobre el bbox). El
  **original NO se toca** (vive en R2 sin blur; sólo el admin lo ve).
- Caras estimadas **< 22 años** → `Photo.needs_minor_review=True` → el admin
  revisa en la cola de aprobación (Fase 5).
- Si el blur falla, la foto pasa a `processing_failed` y **no se aprueba**
  (regla: nunca publicar una foto de menor sin blur).
- El embedding del menor SÍ se guarda (sin blur) para que el menor o su familia
  puedan encontrarlo y borrarlo.

Ver umbrales y racional en `docs/adr/0006-face-recognition-threshold.md`.

## Retención automática (90 días)

- `privacy.cleanup_old_embeddings` (Celery beat, diario 3 AM).
- Borra embeddings con `last_matched_at` > 90 días, o (si nunca matchearon)
  `created_at` > 90 días.
- Registra `AuditLog` con `privacy.embeddings_cleanup` y el conteo borrado.
- **No se desactiva sin migración explícita + aprobación de Jair** (CLAUDE.md).

## Auditoría

Toda acción sensible queda en `core_auditlog` (append-only, no editable desde
el admin):
- `privacy.data_deleted` — un borrado por selfie se completó.
- `privacy.embeddings_cleanup` — corrió el cron de retención.

## Pruebas de consentimiento

Antes de tener clientes reales, las pruebas se hicieron con **caras GAN
sintéticas** (personas que no existen — sin problemas de consentimiento ni
copyright). Cuando se pruebe con personas reales, debe ser **con su
consentimiento explícito**. Nunca usar datasets de caras pirateados.

## Retención de datos (consolidado, Fase 6)

Toda la maquinaria de retención corre en crons de Celery beat (ver runbook).

| Dato | Retención | Cómo se aplica |
|---|---|---|
| Embeddings faciales | 90 días desde el último uso | `cleanup_old_embeddings` (3 AM) |
| Fotos de un evento | ~365 días + 30 de gracia | `enforce_event_retention_policy` → `delete_event_photos_permanently` |
| Audit logs | 2 años | `cleanup_old_audit_logs` (mensual) |
| Links de fotógrafo | se inactivan al vencer (no se borran) | `cleanup_expired_photographer_links` |
| IP en AuditLog | indefinida, **anonimizada** (último octeto a 0) | `anonymize_ip` al guardar |
| IP para rate limiting | no se guarda cruda; **hash con salt diaria** | `hash_ip` (el hash cambia cada día → no se puede correlacionar) |
| Selfie de búsqueda/borrado | **no se guarda** — en memoria y se descarta | síncrono en la vista |

Eventos con `permanent_archive=True` quedan exentos de TODO el borrado automático.
El registro del `Event` nunca se borra (queda `status=deleted` para historial),
solo sus fotos/embeddings/bibs.
