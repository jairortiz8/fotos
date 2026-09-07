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

### 1.6 Marca de agua con los logos del evento

Si el evento lleva logos, hay que **crear el template y asignarlo ANTES de que
suba la primera foto**. Las fotos que entran sin el template se procesan sin
logos y hay que regenerarles el preview después.

1. Poner los archivos de logo en `apps/photos/brand_overlays/`.
2. Definir el template en `apps/photos/overlays.py` (`TEMPLATES`).
3. Agregar la opción a `BrandOverlay` en `apps/events/models.py` + migración de
   choices.
4. Asignar el template al evento: dashboard → editar evento → **Logos en las
   fotos**.

**Antes de dar por bueno un template, mirá el render.** Tres cosas que ya
salieron mal y que un test de "hay algo blanco abajo" NO detecta:

| trampa | qué pasa | cómo se ve |
|---|---|---|
| **Relleno transparente en el archivo** | Al escalar por el alto se escala el LIENZO, no el dibujo | El logo sale hasta la mitad de chico y "flotando" |
| **Antialias hasta el borde** | `getbbox()` no recorta nada (le pasa a NuGo) | Ese logo queda más grande que el resto |
| **Fila repartida con huecos iguales** | Con anchos muy distintos el del medio se corre | El logo central queda descentrado (nos dio 8,4% de desvío) |

Por eso el template lleva un **test que fija la posición y el tamaño exactos**
de cada logo (`test_septimo_calca_el_diseno_aprobado`). Al hacer uno nuevo,
copiá ese test con los números del diseño aprobado.

**Margen lateral**: 12% del ancho. Es lo que recorta Instagram al poner una foto
vertical en una story. Con menos, los logos de los extremos se pierden.

**Vertical y horizontal son composiciones distintas**: apilar dos filas en una
foto apaisada hace que el degradado se coma casi la mitad del alto. Por eso el
template define `landscape_rows` (los 5 logos en una sola fila).

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

**Para volver a prenderlos**, por API, uno por servicio:

```graphql
mutation($s:String!,$e:String!,$c:String){
  serviceInstanceDeployV2(serviceId:$s, environmentId:$e, commitSha:$c)
}
```

> **`commitSha` NO es opcional en la práctica.** Sin él, Railway vuelve a
> levantar **el último build que ese servicio ya tenía**, que puede ser de hace
> semanas. Nos pasó el 2026-09-05: prendí los workers, quedaron en un commit
> viejo que no conocía el template de logos nuevo, y la primera foto del evento
> se procesó **sin marca de agua**. El web sí estaba al día, así que el síntoma
> era confuso.

> **Un push a `main` NO redeploya los workers de forma confiable.** Redeploya el
> web, pero los workers pueden quedarse donde estaban. **Siempre verificá el
> commit**, no que el servicio esté en verde.

Verde en Railway no alcanza como prueba, y el commit tampoco: la forma real de
saber que están consumiendo la cola es preguntárselo. Con `REDIS_PUBLIC_URL` (proxy público de
Redis), un `Celery(broker=url).control.ping(timeout=8)` devuelve una respuesta
**por cada worker** que esté escuchando. Con `worker` y `worker_fast` arriba
tienen que contestar **dos**.

> **Ojo con el orden**: apagalos **después** del último push a `main`. Un push
> puede revivir el web y, a veces, algún worker.

**Qué colas atiende cada uno de verdad** (comprobado el 2026-09-06, y NO es lo
que sugieren los defaults del entrypoint):

```
celery@... colas=['celery', 'fast']   <- el liviano (previews), 4 procesos
celery@... colas=['faces']            <- el pesado (caras), 1 proceso
```

**Agregar procesos EN CALIENTE**, sin deploy ni reinicio, si una tanda grande
satura la cola de previews:

```python
app = Celery(broker=REDIS_PUBLIC_URL)
nodo = ...  # el que atiende `fast` y NO atiende `faces`
app.control.pool_grow(4, destination=[nodo])
```

Se pierde en el próximo deploy, que está bien: es para el rato del evento.

> **Al worker de caras NO se le agregan procesos.** Dos procesos cargando el
> modelo facial causaron el OOM que colgó todo el 2026-06-09. Si hace falta más
> capacidad de caras, la forma correcta es un **segundo servicio** con su propia
> memoria, no más procesos en el mismo contenedor.

**Lo que deja de funcionar con los workers apagados**:

- Procesar fotos nuevas (si alguien sube, queda trabada).
- Indexar caras nuevas.
- Los crons de retención, limpieza y backup.

---

## 4.bis Rendimiento medido (para comparar contra el próximo evento)

Números reales, no estimaciones. Sirven para saber si un evento va **bien** o
**mal** mientras está pasando.

### Séptimo x CEP · Social Run (2026-09-06)

| | |
|---|---|
| fotos | 1.553 en 45 min |
| promedio de subida | 34,5 fotos/min |
| **pico de subida** | **543 en 5 min = 108,6 fotos/min** |
| fallas de subida | **0** |
| caras detectadas | 6.667 |
| fotos sin ninguna cara | 167 (11%) — de espalda, paisaje, lejos |

**Indexado de caras** (desde que entra la foto hasta que es buscable por selfie):

| | |
|---|---|
| mediana | 11,8 min |
| 9 de cada 10 | < 21,7 min |
| peor caso | 28,2 min |

Eso con **un solo proceso** de caras. Da ~21 fotos/min de throughput.

**Previews**: no hay marca de tiempo propia (el campo se pisa al aprobar), pero
la cola llegó a 478 y se vació en ~10 min. Cota superior: la aprobación tuvo
mediana de 5,8 min desde la subida, y no se puede aprobar algo sin procesar.

> **Pendiente útil**: agregar un `processed_at` a `Photo`. Hoy la velocidad del
> preview se infiere, no se mide.

### Volumen acumulado del sistema (2026-09-07)

| evento | fotos | caras | ventana de subida |
|---|---|---|---|
| **surf-city-2026** | **19.510** | **38.784** | 30 h |
| camino-a-san-luis | 3.215 | 7.053 | 82 h |
| garmin-runners-girls-5k | 1.908 | 5.505 | 3,8 h |
| septimo-x-cep | 1.553 | 6.667 | 45 min |

**Totales**: 27.105 fotos · 58.035 caras · base de datos **588 MB** (la tabla de
caras sola son 344 MB). **Pico histórico de subida: 1.377 fotos en 5 min = 275
por minuto.**

### Cómo dimensionar el servidor con esto

El cuello de botella es **el indexado de caras**: 1 proceso ≈ 21 fotos/min y
~1,1 GB de RAM por proceso. Todo lo demás es barato al lado.

| carga | qué hace falta |
|---|---|
| Un evento tipo Séptimo (1.500 fotos) | 1 proceso de caras alcanza; lista en ~1 h |
| Un evento tipo Surf City (19.500 fotos) | 1 proceso tarda ~15 h; con 2-3 baja a 5-7 h |

Para el VPS: **8 vCPU y 16 GB** cubren Surf City con holgura (2-3 procesos de
caras + web con el modelo cargado + Postgres + Redis). Con 4 vCPU / 8 GB anda,
pero el indexado facial queda atrasado muchas horas en un evento grande.

> **vCPU dedicada, no compartida.** El reconocimiento facial usa el CPU al 100%
> durante horas seguidas; en instancias compartidas eso se estrangula.

Disco: las fotos viven en R2, así que el servidor sólo necesita espacio para el
sistema, la imagen de Docker (~3 GB) y Postgres (588 MB hoy, ~2 GB proyectado).
40-80 GB sobran.

Tráfico: ojo que la descarga de fotos se **proxea** por el servidor
(`PhotoDownloadView`), así que el tráfico de bajada de los corredores también
pasa por ahí, no directo de R2.

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
| Las fotos salen sin logos aunque el evento tiene template | El worker quedó en un commit viejo: `serviceInstanceDeployV2` sin `commitSha` revive el build anterior |
| Un logo se ve la mitad de chico que el resto | El archivo tiene relleno transparente y se escaló el lienzo, no el dibujo |
| "Ya subí fotos y la galería está vacía" | Las fotos entran en **Pendiente de aprobar**; la galería pública sólo muestra las **aprobadas** |
| "Me dijo que hice muchas búsquedas" | Límite viejo de 10/día del mismo dorsal; cada recarga contaba. Hoy: 200/h y las repetidas salen de caché y no gastan cupo |
| Fotos sin ninguna cara indexada | No siempre es atraso: si las colas están en cero, son fotos donde el modelo **no encontró caras** (de espalda, paisaje, lejos) |

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
