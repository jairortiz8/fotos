# Checklist para un evento nuevo

Guía operativa para levantar un evento de cero y no repetir los problemas que ya
nos pasaron. Cada punto dice **qué comprobar** y **cómo se ve cuando está mal**.

> Escrito después del Garmin Runners Girls 5K (2026-08-30), donde 736 fotos
> quedaron trabadas 20 minutos porque faltaba levantar un servicio.

---

## 1. Antes del evento

### 1.1 Los servicios tienen que estar PRENDIDOS

Entre eventos apagamos los workers para no pagar de más. **Hay que volver a
prenderlos**, y esto es lo que más fácil se olvida.

En Railway, cada servicio en **1 réplica** (no 0):

| servicio | qué hace | si está apagado |
|---|---|---|
| `fotos` (web) | sitio, subida, búsquedas | el sitio no carga |
| `worker` | reconocimiento facial (selfie) | las caras nunca se indexan |
| `worker_fast` | preview, thumbnail y OCR | **las fotos quedan en "Procesando" para siempre** |
| `beat` | cron de retención y limpieza | nada urgente, pero conviene |
| `Postgres`, `Redis` | siempre arriba | — |

**Cómo comprobarlo**: Railway → cada servicio → que diga *Active*, no *Removed*
ni 0 réplicas.

### 1.2 Las colas y quién las atiende

Este es el punto que causó el atasco. Las tareas se reparten en tres colas y
**cada cola necesita alguien que la consuma**:

| cola | tareas | la consume |
|---|---|---|
| `fast` | `process_photo`, `run_ocr_on_photo` | `worker_fast` |
| `faces` | `run_face_recognition_on_photo` | `worker` |
| `celery` | avatares, crons, todo lo demás | `worker_fast` |

Variables que definen el reparto:

- `worker.WORKER_QUEUES` = `faces`
- `worker_fast.PROCESS_TYPE` = `worker` · `WORKER_QUEUES` = `fast,celery` · `CELERY_CONCURRENCY` = `4`

> **Ojo**: el rol `worker_fast` del entrypoint tiene la cola fija en `fast` y no
> respeta `WORKER_QUEUES`. Por eso el servicio `worker_fast` corre con
> `PROCESS_TYPE=worker`: así sí respeta la variable y puede tomar `celery`.

**Cómo se ve cuando está mal**: las fotos suben bien (el fotógrafo ve "Subida")
pero se quedan en "Procesando" y nunca aparece la miniatura. Sin errores en los
logs, porque nadie está tomando la tarea.

### 1.3 Flags de funcionalidad

| variable | dónde | valor | para qué |
|---|---|---|---|
| `FACE_SEARCH_ENABLED` | web | `true` | habilita la búsqueda por selfie |
| `FACE_PROCESSING_ENABLED` | worker | `true` | indexa las caras al subir |
| `OCR_BACKEND` | worker, worker_fast | `gemini` | OCR con IA |
| `GEMINI_API_KEY` | worker, worker_fast | (la key) | sin esto el OCR cae al motor local |
| `MINOR_BLUR_ENABLED` | worker | `false` | decisión de Jair: sin blur |
| `PREVIEW_WATERMARK_ENABLED` | worker, worker_fast, web | `false` | previews sin marca de agua |

### 1.4 Crear el evento

- **Estado** `live` (Galería abierta) y **visibilidad** `public`.
- Revisar el **nombre** — se ve en la home y en lo que se comparte.
- Cargar **portada** y datos del **organizador** (nombre + Instagram).
- Revisar las fechas de retención si acordaste una permanencia distinta.

### 1.5 Links de fotógrafo

- Generar **uno por fotógrafo** desde el dashboard.
- El token se muestra **una sola vez** — copialo al generarlo. Si se pierde, hay
  que regenerar (el anterior queda revocado).
- Verificar la **fecha de vencimiento**: los de eventos pasados ya no sirven.
- **No reutilizar** links de otro evento: las fotos entrarían al evento equivocado.

---

## 2. Durante el evento

### 2.1 Probar la subida con 2 o 3 fotos

Antes de darle el link al fotógrafo, subí vos desde el celular. Comprobá que:

1. El estado pasa a **"Subida"** (verde) enseguida.
2. En un rato aparece la **miniatura real**.
3. En el dashboard la foto queda en **"Pendiente de aprobar"**.

Si se queda en "Procesando" más de unos minutos → volvé al punto 1.2.

### 2.2 Mientras suben

- Las fotos entran en **"Pendiente de aprobar"**: no se publican solas.
- Podés aprobar sin esperar a que terminen el OCR y las caras — se siguen
  agregando después, sin necesidad de re-aprobar.

### 2.3 Orden de la cola

Todas las tareas de preview entran primero y **el OCR se encola detrás**. Es
normal ver 0 dorsales hasta que los previews terminan. No es una falla.

---

## 3. Después: auditar antes de publicar

Comprobar, en este orden:

1. **Las tres colas en cero** (`fast`, `faces`, `celery`).
2. **Ninguna foto** en `processing`, `uploading` ni `processing_failed`.
3. **Ninguna foto sin** original, preview ni thumbnail.
4. **Dorsales leídos > 0** y un porcentaje razonable de fotos con dorsal.
5. **Caras indexadas > 0**, y la mayoría con visor clickeable.
6. **Prueba funcional del buscador por cara**: agarrar una cara guardada,
   buscar con ella y verificar que devuelve su propia foto primero.

### Umbral de las caras

`FACE_AVATAR_MIN_PX` (130) y `FACE_AVATAR_FLOOR_PX` (50) deciden qué caras se
ofrecen como clickeables.

Están calibrados para que convivan dos tipos de foto: primeros planos (caras de
200 px o más) y **fotos grupales** (caras de 50-60 px). Si en un evento nuevo las
fotos grupales muestran **una sola cara**, medí la distribución de tamaños: puede
que ese evento tenga caras aún más chicas y haya que bajar el piso.

---

## 4. Al terminar: apagar

Cuando ya no se suben más fotos y la auditoría pasó:

- `worker`, `worker_fast` y `beat` → **detenidos**.
- `fotos` (web), `Postgres` y `Redis` → **siguen arriba**: la galería, la
  búsqueda por dorsal y la búsqueda por cara funcionan sin workers.

**Desde el panel de Railway**: en cada servicio, el deployment activo → *Remove*.
Queda en "SIN DEPLOY" y deja de facturar cómputo. El servicio, sus variables y su
configuración quedan intactos.

**Por API** (lo que se usó acá):

```graphql
mutation($id:String!){ deploymentRemove(id:$id) }
```

> Dos caminos que NO funcionan y ya nos costaron tiempo:
> `serviceInstanceUpdate(numReplicas: 0)` lo rechaza Railway ("Invalid input",
> el mínimo es 1), y `deploymentStop` devuelve `true` pero **el servicio sigue
> corriendo**. El único que apaga de verdad es `deploymentRemove`.

**Para volver a prenderlos**: un push a `main` redeploya los tres (todos trackean
esa rama), o *Redeploy* en cada servicio desde el panel. No hay que reconfigurar
nada.

**Lo que deja de funcionar con los workers apagados**:

- Procesar fotos nuevas (si alguien sube, queda trabada).
- Indexar caras nuevas.
- Los crons de retención, limpieza y backup.

---

## 5. Errores que ya nos pasaron

| síntoma | causa real |
|---|---|
| Fotos eternamente en "Procesando" | `worker_fast` sin desplegar: nadie consumía la cola `fast` |
| "El OCR no funciona", 0 dorsales | El OCR estaba encolado **detrás** de los previews; no era una falla |
| Foto de grupo con una sola cara clickeable | Umbral de 130 px calibrado para primeros planos; las caras del grupo miden ~59 px |
| Las caras tapaban la foto en el lightbox | Las tiras se partían en varias filas y la barra crecía sobre la imagen |
| Marca de agua no deseada | Flag `PREVIEW_WATERMARK_ENABLED`; hay que **regenerar** los previews ya hechos |
| La fecha del evento "se perdía" al editar | Formato del input, no la base — la fecha siempre estuvo bien |
| "Ya apagué los workers" y seguían corriendo | `numReplicas: 0` lo rechaza la API y `deploymentStop` miente: hay que usar `deploymentRemove` |

> La franja con logos al pie de algunas fotos **no es nuestra**: viene quemada en
> el archivo original del fotógrafo. No se puede quitar desde el sistema.

---

## 6. Comandos útiles

Regenerar previews de un evento (por ejemplo tras cambiar el watermark), **sin
tocar el estado de aprobación**:

```python
photos.regenerate_event_thumbnails(event_id, include_preview=True)
```

Regenerar los avatares de caras de una foto (idempotente, saltea los hechos):

```python
photos.generate_face_avatars(photo_id)
```

Re-encolar el reconocimiento facial de fotos aprobadas sin indexar:

```python
photos.reindex_missing_faces(days=2, limit=100)
```
