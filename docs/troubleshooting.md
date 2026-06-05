# Troubleshooting — problemas comunes de RunFoto

Lista de problemas reales que aparecieron durante la construcción, con el formato
**síntoma → causa → solución**. Para incidentes de operación más amplios (cómo
restaurar un backup, manejar una filtración de credenciales, etc.) mirá
`docs/runbook.md`. Para deploy desde cero, `docs/deployment.md`.

---

## La búsqueda por selfie da 500 en producción (no en local)

**Síntoma**: en Railway, hacer POST de un selfie devuelve `500` casi inmediato
(~0.8 s). En local funciona bien.

**Causa**: `cv2` (OpenCV) no puede importar por falta de librerías de sistema.
En los logs aparece `ImportError: libxcb.so.1: cannot open shared object file`.
InsightFace arrastra `opencv-python` (versión completa, no la headless) como
dependencia transitiva, y su `.so` necesita libGL + GLib + X11, que la imagen
slim de Python no trae por defecto.

**Solución**: el `Dockerfile` (runtime stage) tiene que instalar estas libs:

```
libgl1 libglib2.0-0 libgomp1 libxcb1 libsm6 libxext6 libxrender1
```

Ya están en el `Dockerfile` actual. Si agregás otra dependencia ML que use cv2,
ya quedan cubiertas. Diagnóstico rápido: `railway logs | grep -i "shared object"`.

---

## OOM / 502 al cargar el modelo facial (`buffalo_l`) con 1 GB de RAM

**Síntoma**: la búsqueda por selfie tumba el sitio: aparece un `502` y en los
logs `Worker was sent SIGKILL! Perhaps out of memory?`. A veces voltea todo el
sitio unos segundos (no sólo la búsqueda).

**Causa**: la inferencia facial corre **síncrona en el proceso web** (decisión de
privacidad: la biometría nunca toca Celery/Redis, ADR 0006). Cargar `buffalo_l`
necesita **~1.1 GB** de RAM aún optimizado (1 worker + sólo los sub-modelos
detection/recognition/genderage). El servicio web está **capado a 1 GB**, así que
cargar el modelo provoca un OOM que mata el único worker de gunicorn.

**Solución (mitigación actual)**: el flag **`FACE_SEARCH_ENABLED=false`** en prod
corta **antes** de tocar el modelo y muestra una página 503 amable; el tab "Por
selfie" se oculta. La búsqueda por dorsal (método principal) no se ve afectada.

**Para reactivar la búsqueda por selfie**, elegí una:

1. **Subir la RAM** del servicio web a **≥2 GB** (Railway → servicio → Settings, o
   `railway scale`) y poner `FACE_SEARCH_ENABLED=true`. La RAM se factura por uso
   real (idlea en ~150 MB, sube ~1.1 GB sólo durante una búsqueda), así que el
   costo extra es chico. **Es la opción recomendada.**
2. **Cambiar a `buffalo_s`** (modelo más liviano) en `apps/ml/face_recognition.py`
   (`MODEL_NAME`) — entra en 1 GB pero baja algo la precisión; hay que recalibrar
   los umbrales con `python manage.py tune_threshold`.
3. **Mover la inferencia a un microservicio** aparte con su propia RAM.

El matching, el umbral y el blur de menores ya están verificados (en local); lo
único que falta para prod es la RAM.

---

## El primer selfie tarda 30–60 s o da 502 (pero después anda)

**Síntoma**: la primera búsqueda por selfie después de un deploy/reinicio tarda
muchísimo o da un `502`; las siguientes son rápidas.

**Causa**: el modelo `buffalo_l` (~280 MB) se está **descargando en caliente**
porque el pre-cache de build-time falló (el host del modelo estaba caído ese día).

**Solución**: mirá los logs del build → si ves `WARN: pre-cache de buffalo_l
falló`, el runtime lo baja igual (cubierto por `--timeout 120` en gunicorn). No es
bloqueante. Re-deployar cuando el host del modelo vuelva lo vuelve a cachear en la
imagen. (Esto es independiente del problema de RAM de arriba.)

---

## Los crons de retención / cleanup / backup no corren en producción

**Síntoma**: los eventos no avanzan de estado solos, los embeddings viejos no se
borran a los 90 días, los ZIPs expirados no se limpian, el backup diario a R2 no
aparece.

**Causa**: **el servicio `beat` de Celery no existe todavía en Railway**. El
`CELERY_BEAT_SCHEDULE` está definido en el código (`config/settings/base.py`),
pero sin un proceso `beat` corriendo, nadie dispara los crons.

**Solución**: crear el servicio `beat` en Railway (y el `worker`, que es quien
ejecuta las tasks que el beat agenda). Ver `docs/deployment.md` → Paso 7.

Mientras tanto, podés forzar un cron a mano:

```bash
railway run python manage.py shell
```
```python
from apps.privacy.tasks import enforce_event_retention_policy
enforce_event_retention_policy()   # corre síncrono en el shell
```

---

## Las fotos suben pero quedan en estado "processing" para siempre

**Síntoma**: el fotógrafo sube fotos correctamente, pero nunca aparecen para
aprobar; quedan en `status=processing`. No se generan preview/thumbnail ni se
detectan dorsales.

**Causa**: **el servicio `worker` de Celery no existe en Railway**. El upload crea
el `Photo` y dispara la task `process_photo`, pero sin un worker corriendo la task
nunca se ejecuta.

**Solución**: crear el servicio `worker` en Railway (ver `docs/deployment.md` →
Paso 7). En local, asegurate de tener el worker levantado:

```bash
celery -A config worker --loglevel=info
```

(o `docker compose up`, que ya incluye `worker` y `beat`).

---

## `/healthz` devuelve `"degraded"` o `"down"`

**Síntoma**: el endpoint de salud profundo `/healthz` no devuelve `"ok"`.

**Causa y solución según el caso**:

- **`status: "ok"` (200)**: todo bien.
- **`status: "degraded"` (200)**: DB y Redis están OK, pero algún check
  **informativo** falla. **Lo más común es `celery_workers.workers: 0`** → no hay
  worker corriendo. **En el estado actual de prod esto es ESPERADO** (el worker no
  está creado todavía). También puede ser `r2.configured: false` en dev (sin
  credenciales). No tumba el deploy: por eso el probe de Railway usa
  `/healthz/lite`, no `/healthz`.
- **`status: "down"` (503)**: falló DB o Redis (lo crítico). Revisá que los
  servicios `Postgres`/`Redis` estén arriba y que `DATABASE_URL`/`REDIS_URL`
  apunten bien.

En resumen: `degraded` por `workers: 0` es normal hasta crear el `worker`; un
`down` sí es un problema real de DB/Redis.

---

## Comentarios `{# ... #}` multilínea se renderizan como texto en la página

**Síntoma**: en una página aparece texto suelto que claramente era un comentario
del template.

**Causa**: en Django, la sintaxis `{# ... #}` es para comentarios de **una sola
línea**. Si lo abrís en una línea y lo cerrás en otra, Django no lo trata como
comentario y lo imprime como texto.

**Solución**: usá `{% comment %} ... {% endcomment %}` para comentarios de varias
líneas. (Se arreglaron 3 casos así en Fase 3.)

---

## Alpine.js no reacciona: selección múltiple / lightbox / drawer "muertos"

**Síntoma**: la interactividad de Alpine no funciona (no se pueden seleccionar
fotos, el bottom sheet de descarga no abre, el menú/drawer del dashboard no
responde, el lightbox no navega). En los screenshots todo "se ve bien", pero al
usarlo no pasa nada.

**Causa (dos posibles, ambas reales en este proyecto)**:

1. **Hash SRI incorrecto**: Alpine se carga desde unpkg con
   `integrity="sha384-..."`. Si el hash no coincide con el archivo real, el
   navegador **se niega a ejecutar el script** y Alpine nunca arranca,
   silenciosamente. Esto pasó: el hash de Alpine estuvo mal desde Fase 3 y no se
   detectó porque las verificaciones eran con screenshots (render estático, que no
   prueba interactividad).
2. **CSP sin `'unsafe-eval'`**: el build estándar de Alpine evalúa sus directivas
   (`x-data`, `x-show`, `@click`, ...) con `new Function()`. Sin `'unsafe-eval'`
   en `script-src`, el navegador bloquea toda la interactividad y la consola se
   llena de `Alpine Expression Error: ... 'unsafe-eval'`.

**Solución**:
- Verificá que el `integrity` de Alpine en `base.html` sea el correcto para la
  versión exacta que se carga.
- Verificá que `CONTENT_SECURITY_POLICY` (en `config/settings/base.py`) tenga
  `'unsafe-eval'` en `script-src`. Ya está.
- **Importante**: tras tocar CSP o SRI, verificá en un **navegador real** (no sólo
  screenshots) que Alpine inicializa y reacciona. Revisá la consola del navegador.

> A futuro (hardening, ADR 0009): auto-hospedar HTMX y Alpine en `static/` elimina
> la dependencia de unpkg y el mantenimiento manual de hashes SRI (origen del
> bug). Migrar al build `@alpinejs/csp` permitiría quitar `'unsafe-eval'`.

---

## El backup `pg_dump` falla en producción

**Síntoma**: la task `backup_database` (o `python manage.py backup_db`) no genera
el dump en prod; en local sí funciona.

**Causa**: `pg_dump` necesita ser de versión **≥** a la del servidor. Railway corre
**Postgres 18**, pero la imagen Docker **no trae `postgresql-client-18`** (no se
agregó el repo PGDG para no arriesgar la estabilidad de los deploys — ADR 0010).
Además, el `beat` que dispara la task tampoco corre aún en prod.

**Solución**: el backup en prod hoy lo cubre el **primario = snapshots automáticos
de Railway** (esa es la fuente de verdad para restaurar; ver `docs/runbook.md`).
Para habilitar el dump secundario a R2 en prod hace falta (1) agregar
`postgresql-client-18` a la imagen y (2) que corran `worker` + `beat`.

---

## Tests fallan con `relation ... does not exist`

**Síntoma**: al correr `pytest` aparece un error de que una tabla/relación no
existe.

**Causa**: la base de datos local no está migrada.

**Solución**:

```bash
python manage.py migrate
```

Y asegurate de tener la extensión `vector` creada en la DB local:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

---

## `cv2` / `libGL.so.1` al importar en local (mac/Linux)

**Síntoma**: importar InsightFace/cv2 en tu máquina local falla por una lib del
sistema faltante.

**Causa**: faltan librerías de sistema que OpenCV necesita (en Docker ya están en
el `Dockerfile`; en tu máquina hay que instalarlas).

**Solución**: en macOS, instalá con `brew` lo que falte. En Linux, las mismas libs
que lista el `Dockerfile` (`libgl1`, `libglib2.0-0`, etc.).

---

## La búsqueda por dorsal no refleja fotos recién aprobadas/rechazadas

**Síntoma**: aprobaste o rechazaste fotos pero la búsqueda por dorsal sigue
mostrando el resultado viejo.

**Causa**: las búsquedas por dorsal se cachean **5 minutos** en Redis
(`search:bib:<event_id>:<DORSAL>`).

**Solución**: esperá los 5 minutos, o invalidá el cache de ese dorsal a mano:

```python
from django.core.cache import cache
cache.delete("search:bib:42:1042")   # evento 42, dorsal 1042
```

Detalle completo en `docs/runbook.md` → "Cómo regenerar el cache de búsquedas".

---

## La CSP rompe algo en el navegador

**Síntoma**: un recurso (script, imagen, fuente, fetch) no carga y la consola del
navegador muestra un error de Content Security Policy.

**Causa**: el recurso viene de un origen que la CSP no permite.

**Solución**: revisá `CONTENT_SECURITY_POLICY` en `config/settings/base.py` y la
consola del navegador (te dice exactamente qué directiva bloqueó qué). Los orígenes
permitidos hoy: propio (`'self'`), `unpkg.com` (HTMX/Alpine), `data:` (QR e
imágenes embebidas), `*.r2.cloudflarestorage.com` (previews/thumbnails) y el
endpoint de Sentry. Si agregás un recurso de otro origen, hay que sumarlo a la
directiva correspondiente. Ver ADR 0009.
