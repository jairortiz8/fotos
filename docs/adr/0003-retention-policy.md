# ADR 0003 — Política de retención escalonada de eventos

- **Fecha**: 2026-05-21
- **Estado**: Aceptado
- **Decisores**: Jair (super admin / único stakeholder)

## Contexto

RunFoto opera con un modelo "fotos gratuitas para corredores": los originales viven en Cloudflare R2 (~3-5 MB cada uno) y un evento típico tiene hasta 4.000 fotos, o sea 12-20 GB. Año 1 esperamos 15-20 eventos = 200-400 GB acumulados. Sin política de retención, ese costo crece linealmente y nunca se libera.

Pero **borrar todo a fecha fija** (ej. 30 días) tampoco sirve:

- Muchos corredores buscan sus fotos semanas o meses después.
- Los corredores frecuentes vuelven al sitio meses después con el dorsal en mente buscando una foto puntual.
- A los 6 meses la galería completa ya casi no interesa, pero la búsqueda dirigida por dorsal sí.
- A los 12 meses ya prácticamente nadie pide nada, pero a veces aparece un caso ("¿me podés mandar la foto del año pasado?") que justifica que el admin tenga acceso.
- Después de 1 año el costo de storage supera el valor.

## Decisión

Introducimos una política de retención **escalonada** con 4 ventanas temporales. El evento atraviesa estados que **reducen progresivamente la visibilidad pública** sin borrar las fotos hasta el último escalón.

| Tiempo desde la fecha del evento | Estado                     | Galería pública | Búsqueda pública | Admin |
| -------------------------------- | -------------------------- | --------------- | ---------------- | ----- |
| 0–90 días                        | `live` → `public_closed`   | ✅              | ✅               | ✅    |
| 91–180 días                      | `searchable_only`          | ❌              | ✅               | ✅    |
| 181–365 días                     | `archived`                 | ❌              | ❌               | ✅    |
| 366+ días                        | `pending_deletion` → `deleted` | ❌          | ❌               | ❌    |

Cada cutoff es **configurable por evento** mediante tres campos en el modelo `Event`:

- `public_until: DateTimeField` — default `event.date + 90 días`
- `searchable_until: DateTimeField` — default `event.date + 180 días`
- `archive_until: DateTimeField` — default `event.date + 365 días`

Y una bandera escape:

- `permanent_archive: BooleanField` — si está `True`, el evento NUNCA cambia de estado por retención. Para casos especiales (organizador que paga por archivo permanente, evento histórico marcado por el admin como referencia, etc.).

## Cron jobs (Celery beat)

Implementados en Fase 6 (privacidad + retención). El admin verá próximos cambios de estado en el dashboard.

| Tarea                          | Frecuencia | Qué hace                                                                                          |
| ------------------------------ | ---------- | ------------------------------------------------------------------------------------------------- |
| `events.retention.transition`  | Diario     | Para cada evento, recalcula `status` según `public_until`/`searchable_until`/`archive_until`.     |
| `events.retention.delete`      | Diario     | Eventos con `archive_until` pasado → status `pending_deletion`. Borra archivos R2 y marca `deleted`. |
| `embeddings.cleanup_inactive`  | Diario     | Borra `FaceEmbedding` con `last_matched_at` > 90 días (regla independiente de la del evento).     |

## Razones

### Por qué escalonada (vs cutoff único)

- Las búsquedas dirigidas (un corredor con su dorsal en la mente) son baratas: una query SQL contra el índice de `Bib.number`. Mantenerlas activas 6 meses cuesta cero comparado con servir la galería entera.
- La galería pública es lo costoso (paginación, thumbnails servidos, scraping). Cerrarla pronto reduce carga y mantiene la app rápida.
- El admin necesita acceso retroactivo para casos puntuales — pero solo el admin, no el público.
- Borrar a 12 meses libera storage de R2 (~12-20 GB/evento). Acumulado: ~200-400 GB/año recuperados.

### Por qué configurable por evento

- Un evento "premium" donde el organizador pagó por archivo permanente → `permanent_archive=True`.
- Un evento de prueba que queremos limpiar a los 30 días → cambiar `public_until` manualmente.
- Un evento histórico que el admin quiere mantener archived sin que se borre → `permanent_archive=True` después de archived.

### Por qué metadata persiste en `deleted`

Cuando un evento pasa a `deleted`, las fotos físicas y embeddings se borran de R2 y de la DB. Pero el registro de `Event` (con `name`, `date`, `slug`, counters) queda en la DB para:

- Referencia histórica ("¿qué eventos hubo en 2026?").
- Auditoría legal si en el futuro hay un reclamo sobre datos antiguos.
- Métricas agregadas del producto (cuántos eventos / fotos / fotógrafos hubo cada año).

El usuario nunca ve estos registros; solo el admin.

## Implementación en Fase 1

- 8 valores en `Event.status` choices.
- 3 campos `*_until` con defaults calculados en `save()`.
- Métodos helpers: `is_public()`, `is_searchable()`, `is_archived()`, `days_until_archive()`.
- El test suite verifica que cada cutoff funcione correctamente, incluyendo el bypass de `permanent_archive`.
- **La transición automática** (el cron) **NO se implementa todavía** — eso es Fase 6. En Fase 1 los estados se cambian manualmente desde el admin.

## Alternativas consideradas y descartadas

- **Cutoff único a 90 días**: pierde el valor de búsquedas dirigidas posteriores.
- **Mantener todo para siempre**: insostenible económicamente.
- **Migrar a almacenamiento "frío" (Glacier-like) a los 6 meses**: R2 no tiene tiers fríos; mover a otro proveedor agrega complejidad y costo del que no ganamos lo suficiente para esta escala.
- **Backups inmutables periódicos**: sí los queremos eventualmente (Fase 6+), pero ortogonal a la política de visibilidad pública.

## Consecuencias

### Positivas
- Storage controlado en el largo plazo.
- Privacidad: las fotos no quedan accesibles públicamente por siempre.
- Costo predecible: con 20 eventos/año, el storage en estado estacionario se estabiliza alrededor de los GB de los últimos 12 meses.

### Negativas / riesgos
- Si un corredor querido pide una foto a los 14 meses y ya está borrada, no se puede recuperar. Mitigación: aviso 30 días antes del borrado físico (Fase 6).
- Complejidad operativa: el admin tiene que entender los estados. Mitigación: documentado en `docs/runbook.md` y en el admin con tooltips.
- Posible inconsistencia si una task falla a mitad de un evento (algunas fotos borradas, otras no). Mitigación: tasks idempotentes y transaccionales por evento.
