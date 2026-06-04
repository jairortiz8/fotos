# Runbook operacional — RunFoto

> Este archivo crece fase a fase.

## Tabla de contenido

- [Acceso a producción](#acceso-a-producción)
- [Cómo deployar](#cómo-deployar)
- [Cómo levantar el stack local](#cómo-levantar-el-stack-local)
- [Cómo crear un link de upload de fotógrafo (manual, Fase 2)](#cómo-crear-un-link-de-upload-de-fotógrafo-manual-fase-2)
- [Setup inicial de Cloudflare R2](#setup-inicial-de-cloudflare-r2)
- [Backups](#backups)
- [Rotación de credenciales](#rotación-de-credenciales)
- [Incidentes comunes](#incidentes-comunes)

---

## Acceso a producción

- **Railway**: <https://railway.app> · proyecto `vibrant-communication` · 3 servicios (`fotos` web, `Postgres`, `Redis`).
- **Cloudflare R2**: <https://dash.cloudflare.com> · buckets `runfoto-dev` y `runfoto-prod` (ver [Setup inicial de Cloudflare R2](#setup-inicial-de-cloudflare-r2)).
- **GitHub**: <https://github.com/jairortiz8/fotos>.
- **Sentry**: `<pendiente, llega en Fase 6>`.
- **Site público**: <https://fotos-production-9304.up.railway.app>.
- **Dashboard admin** (Fase 5, uso diario): <https://fotos-production-9304.up.railway.app/dashboard/> · login con la cuenta super admin.
- **Django admin** (fallback de emergencia): `/admin/django/`.

## Cómo deployar

Hoy todavía no hay deploy automático. Cuando se conecte Railway al repo,
el flujo será:

1. Mergear PR en `main`.
2. GitHub Actions corre `ruff`, `mypy`, `pytest`. Tiene que estar en verde.
3. Railway detecta el push a `main` y dispara el build con el `Dockerfile`.
4. El servicio `web` ejecuta `python manage.py migrate --noinput` antes de
   arrancar `gunicorn`.
5. Los servicios `worker` y `beat` reciben la misma imagen pero arrancan
   con comandos distintos (`celery -A config worker` / `celery -A config beat`).

## Usar el dashboard admin (Fase 5)

El dashboard custom (`/dashboard/`) es la herramienta de uso diario. Login con la
cuenta super admin; la sesión dura 12 h. **Toda acción queda en el Audit Log.**

### Flujo típico de un evento

1. **Crear evento**: sidebar → `+ Nuevo evento` → nombre, fecha, visibilidad.
   Las fechas de retención se autocalculan (90/180/365); dejalas vacías salvo
   que quieras override.
2. **Generar link de upload**: en el evento → `+ Generar link` → nombre del
   fotógrafo + días de expiración. Se muestra **una sola vez** la URL con el
   token, un QR descargable y un botón "Copiar p/ WhatsApp" con el mensaje
   pre-armado. Mandáselo al fotógrafo por WhatsApp.
3. **Aprobar fotos**: sidebar → `Aprobación` (badge con el pendiente). 
   - Grilla con multi-select. Seleccioná varias (click en el checkbox) y usá la
     barra de **Aprobar / Rechazar en bloque** (máximo 100 por vez).
   - O usá **atajos de teclado** sobre la foto enfocada: `A` aprobar, `R`
     rechazar, `←/→` navegar, `Space` seleccionar, `Enter` abrir el detalle,
     `Esc` limpiar selección.
   - En el detalle (drawer): ves EXIF, podés **agregar/quitar dorsales** a mano
     y aprobar/rechazar; al aprobar te carga la siguiente pendiente.
4. Las fotos aprobadas aparecen al instante en la galería pública del evento.

### Revocar o regenerar un link

Sidebar → `Fotógrafos` → fila del fotógrafo → **Revocar** (pide confirmación; el
link deja de funcionar al instante) o **Regenerar** (crea un token nuevo e
invalida el viejo — útil si el fotógrafo perdió el link).

### Investigar una queja con el Audit Log

Sidebar → `Audit log`. Filtrá por acción (ej. `photo.rejected`,
`photographer_link.revoked`), por tipo de objetivo o por rango de fechas. Es de
**solo lectura** — no se puede borrar ni editar. Útil para responder "¿quién
borró/aprobó/revocó esto y cuándo?".

### Si el dashboard falla

Usá el Django admin de emergencia en `/admin/django/` para editar cualquier
registro a mano (misma cuenta de login).

## Cómo levantar el stack local

Ver `README.md` para el setup completo. Resumen:

```bash
# Una sola vez
brew install python@3.12 postgresql@16 pgvector redis
brew services start postgresql@16
brew services start redis
createdb runfoto
psql runfoto -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Cada vez que abrís el proyecto
source .venv/bin/activate
python manage.py migrate
python manage.py runserver
```

Alternativa con Docker (cuando Docker Desktop esté instalado):

```bash
docker compose up
```

## Cómo crear un link de upload de fotógrafo (manual, Fase 2)

Mientras la UI del admin para generar links no llegue (Fase 5), se crean por
Django shell. Local:

```bash
python manage.py shell
```

```python
from apps.events.models import Event
from apps.photographers.models import PhotographerLink

event = Event.objects.get(slug="maraton-antigua-2026")
link, raw_token = PhotographerLink.generate_token_and_create(
    event,
    name="Lucia Pérez",
    email="lucia@ejemplo.com",
    phone="+502 5123 4567",
    photo_limit=200,           # opcional
    expires_in_days=45,        # opcional; default 30 después del evento
)
print(f"URL para mandar por WhatsApp: https://<dominio>/u/{raw_token}/")
print(f"Token plano (sólo se ve UNA vez): {raw_token}")
```

El `token_hash` queda en DB; el plano sólo se ve en ese print. Si el fotógrafo
lo pierde, hay que **regenerar** (no se puede recuperar).

En producción (Railway):

```bash
railway service link fotos
railway run python manage.py shell
# (mismo snippet)
```

### Revocar un link

```python
link = PhotographerLink.objects.get(id=42)
link.revoke(reason="upload masivo sin permiso")
```

Queda registrado en `AuditLog` automáticamente.

---

## Setup inicial de Cloudflare R2

> **Cuándo aplicar**: una sola vez al empezar (o cuando renovamos credentials).

### 1. Crear cuenta Cloudflare (si no tenés)

1. Andá a https://dash.cloudflare.com/sign-up
2. Email + password. No hace falta tarjeta de crédito para el free tier de R2.
3. Verificá el email.

### 2. Habilitar R2

1. En el dashboard de Cloudflare, sidebar izquierdo → **R2 Object Storage**.
2. Click **"Enable R2"** (es free hasta 10 GB de storage y 1M class A ops/mes —
   más que suficiente para arrancar).
3. Cloudflare te pide aceptar términos. OK.

### 3. Crear los buckets

Vamos a usar dos buckets para separar dev de prod:

1. Click **"Create bucket"**.
2. **Bucket name**: `runfoto-dev`
3. **Location**: `Eastern North America (ENAM)` (o el más cercano a Guatemala).
4. **Default storage class**: `Standard`.
5. Click **"Create bucket"**.
6. **Repetir** para `runfoto-prod`.

### 4. Crear un API Token con permisos sobre los buckets

R2 usa "API tokens" estilo S3, no las API keys generales de Cloudflare.

1. En la sección R2 del dashboard, sidebar → **"R2 API Tokens"** (también
   accesible desde "Manage API tokens" en la página de R2).
2. Click **"Create API token"**.
3. **Token name**: `runfoto-backend`
4. **Permissions**: `Object Read & Write` (lectura + escritura — necesitamos
   subir y borrar).
5. **Specify bucket(s)**: seleccioná `runfoto-dev` **y** `runfoto-prod`. Eso
   limita el token a SOLO esos dos buckets — si alguien filtra el token, no
   compromete otros buckets de la cuenta.
6. **TTL**: dejá `Forever` (rotamos manualmente si hace falta).
7. Click **"Create API Token"**.
8. **Pantalla crítica**: Cloudflare te muestra **una sola vez**:
   - **Access Key ID** (string corto)
   - **Secret Access Key** (string largo)
   - **Endpoint** (URL tipo `https://<account-id>.r2.cloudflarestorage.com`)
   - Hay 3 endpoints: **S3 API**, **EU jurisdiction**, **FedRAMP**. Usá el
     primero (**S3 API endpoint**, sin sufijo `-eu`).
   - Tomá screenshot o copiá los tres valores a tu password manager **ya** —
     después no se pueden ver de nuevo.

### 5. Compartirme las credentials (cuando estés listo)

Cuando tengas los 4 valores, pasámelos en este orden (yo los voy a meter en
`.env` local y en Railway secrets — nunca en código):

```
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_BUCKET_NAME=runfoto-dev
R2_BUCKET_NAME_PROD=runfoto-prod
```

### 6. (Opcional, después) Dominio público para servir thumbnails sin firmar

Para Fase 3+ podemos enchufar un dominio custom a un bucket. Por ahora todo
sirve via URLs firmadas (15 min de expiración) y no expone el bucket
públicamente.

---

## Cómo regenerar el cache de búsquedas (Fase 3)

Las búsquedas por dorsal se cachean 5 minutos en Redis con la key
`search:bib:<event_id>:<DORSAL>`. Si aprobás/rechazás fotos y querés que las
búsquedas reflejen el cambio **ya** (sin esperar los 5 min):

```bash
# Borrar el cache de un dorsal puntual
railway run python manage.py shell
```
```python
from django.core.cache import cache
cache.delete("search:bib:42:1042")   # evento 42, dorsal 1042
```

O para limpiar TODO el cache (también resetea rate limits — usar con cuidado):
```python
from django.core.cache import cache
cache.clear()
```

> Nota: `cache.clear()` borra también los contadores de rate limiting. En
> producción, preferí borrar keys puntuales.

## Cómo aprobar fotos para que aparezcan en la galería

Las fotos suben en `status=pending_review`. La galería pública sólo muestra
`approved`. Para aprobar:

- **Vía admin**: `/admin/photos/photo/` → seleccionar → no hay action bulk
  todavía (llega en Fase 5). Por ahora, editar cada foto y cambiar el estado.
- **Vía shell** (bulk):
```python
from apps.photos.models import Photo, PhotoStatus
from django.utils import timezone
Photo.objects.filter(event__slug="mi-evento", status="pending_review").update(
    status=PhotoStatus.APPROVED, approved_at=timezone.now(), approved_by_admin=True
)
```
Después actualizá el contador del evento:
```python
from apps.events.models import Event
e = Event.objects.get(slug="mi-evento")
e.photo_count = e.photos.filter(status="approved").count()
e.save()
```

## Cómo procesar una solicitud manual de borrado (Fase 4)

Normalmente el usuario lo hace solo en `/privacidad/borrar-mis-datos/`. Si
alguien lo pide por otro canal (WhatsApp, email) y tenés una foto suya:

```bash
railway run python manage.py shell
```
```python
from apps.ml.face_recognition import embedding_from_bytes
from apps.privacy.views import find_matching_photo_ids
from apps.privacy.models import DataDeletionRequest, DeletionStatus
from apps.privacy.tasks import delete_photos_for_request

emb = embedding_from_bytes(open("/ruta/foto.jpg", "rb").read())
ids = find_matching_photo_ids(emb.tolist())
print(f"{len(ids)} fotos matchean")
d = DataDeletionRequest.objects.create(
    requester_ip_hash="manual", status=DeletionStatus.PROCESSING, matched_photo_count=len(ids)
)
delete_photos_for_request.delay(d.id, ids)   # requiere worker corriendo
```

## Cómo volver a un threshold anterior si hay quejas (Fase 4)

Los umbrales son constantes en código (no DB):
- Búsqueda: `SIMILARITY_THRESHOLD` en `apps/search/views.py`.
- Borrado: `DELETION_THRESHOLD` en `apps/privacy/views.py`.
- Menores: `MINOR_BLUR_AGE` / `MINOR_REVIEW_AGE` en `apps/photos/tasks.py`.

Para revertir: editá la constante, commit, push, redeploy. **No requiere
migración ni reprocesar embeddings** (el umbral se aplica en query-time).

Para calibrar con datos reales:
```bash
python manage.py tune_threshold --selfie s.jpg --positives pos/ --negatives neg/
```

## Crons de retención y cleanup (Fase 6)

Corren en el servicio `beat` (Celery beat). **Recordá: el worker + beat todavía
no existen en Railway** (pendiente) — hasta crearlos, estos crons NO corren en
prod. Horarios (`CELERY_BEAT_SCHEDULE` en `config/settings/base.py`):

| Task | Horario | Qué hace |
|---|---|---|
| `enforce_event_retention_policy` | 02:00 diario | avanza estados de eventos según fechas |
| `cleanup_old_embeddings` | 03:00 diario | borra embeddings inactivos > 90 días |
| `cleanup_expired_photographer_links` | 04:00 diario | marca inactivos los links vencidos |
| `cleanup_failed_processing` | cada 6 h | marca failed fotos atascadas > 1 h |
| `cleanup_expired_zips` | cada hora (:15) | borra ZIPs vencidos de R2 |
| `backup_database` | 01:00 diario | pg_dump → R2 (ver ADR 0010) |
| `cleanup_orphaned_r2_objects` | Domingo 05:00 | detecta objetos huérfanos en R2 |
| `cleanup_old_audit_logs` | día 1 del mes 06:00 | borra audit logs > 2 años |

**Forzar un cron a mano** (ej. para probar la retención sin esperar a las 2 AM):
```bash
railway run python manage.py shell
```
```python
from apps.privacy.tasks import enforce_event_retention_policy
enforce_event_retention_policy()   # corre síncrono en el shell
```

## Backups y recuperación

**Estrategia (ADR 0010):**
- **PRIMARIO — snapshots de Railway**: el servicio Postgres de Railway hace
  snapshots automáticos. Es la fuente de verdad para restaurar.
- **SECUNDARIO — dump a R2**: `backup_database` (beat 1 AM) sube un `pg_dump`
  gzipeado a `runfoto-prod/backups/db/`. Hoy requiere `postgresql-client-18` en
  la imagen (pendiente; ver ADR 0010). Backup manual: `python manage.py backup_db`.

**Restaurar desde un snapshot de Railway:**
1. Railway → proyecto → servicio `Postgres` → pestaña **Backups/Snapshots**.
2. Elegí el snapshot por fecha → **Restore** (Railway crea una DB nueva o
   restaura sobre la actual según la opción).
3. Verificá con `railway run python manage.py shell` → contar eventos/fotos.
4. Re-deployar el servicio web si hace falta que tome la DB restaurada.

**Restaurar desde el dump de R2** (si Railway no estuviera disponible):
```bash
# bajar el último dump de R2 (vía dashboard de Cloudflare o boto3) y:
gunzip runfoto_backup.sql.gz
psql "$DATABASE_URL" < runfoto_backup.sql
```

## Manejar un incidente de seguridad

1. **Contené**: si se filtró una credencial (R2, SECRET_KEY, DB), rotala YA
   (ver "Rotación de credenciales") y redeployá.
2. **Revocá accesos**: cambiá el password del super admin desde
   `/dashboard/configuracion/`. Revocá links de fotógrafo sospechosos.
3. **Investigá con el Audit Log**: `/dashboard/audit-log/` — filtrá por acción y
   fecha para ver qué pasó y cuándo.
4. **Revisá Sentry**: errores anómalos (picos de 500, rate-limit) suelen aparecer ahí.
5. **Documentá** el incidente acá abajo (síntoma → causa → fix) para la próxima.

## Investigar una foto reportada (alguien pide que la bajemos)

1. Pedile a la persona que use `/privacidad/borrar-mis-datos/` (sube un selfie,
   se borran sus fotos de todos los eventos). Es lo más rápido y no necesita admin.
2. Si no puede (no aparece bien en el selfie, etc.): buscá la foto en el dashboard
   (evento → tab Fotos), abrí el detalle y rechazala/borrala. Queda en el Audit Log.
3. Para menores: el preview ya se blurea automático (Fase 4). Si piden borrado
   total, borrá la foto original desde el dashboard.

## Escalar si crece el tráfico

- **Vertical (lo primero)**: subí RAM/CPU del servicio `fotos` en Railway. La
  búsqueda facial necesita ≥2 GB para `buffalo_l` (ver Incidentes).
- **Workers**: agregá más concurrencia al `worker` (`--concurrency=N`) o un
  segundo worker para el procesamiento de uploads (OCR + caras) en eventos grandes.
- **DB**: si las queries se ponen lentas, PgBouncer (Railway lo ofrece) o subir
  el plan de Postgres. Hoy `CONN_MAX_AGE=60` alcanza.
- **Horizontal (web)**: Railway permite múltiples réplicas del servicio web; el
  estado vive en Postgres/Redis/R2, así que el web es stateless y escala bien.

## Rotación de credenciales

> Documentar acá:
> - Cuándo rotar `SECRET_KEY` (nunca durante la vida normal; sólo si se
>   filtra).
> - Cómo rotar las credenciales de R2 (generar nuevo par en Cloudflare,
>   actualizar Railway secrets, redeploy).
> - Cómo rotar el password del super admin.

## Incidentes comunes

> Se llena fase a fase con cosas reales que pasen. Por ahora, vacío.

### Sintoma → Causa probable → Cómo arreglar

- **Búsqueda por selfie devuelve 500 inmediato (~0.8s) en prod** → `cv2` no
  puede importar por falta de libs de sistema (`ImportError: libxcb.so.1: cannot
  open shared object file`). InsightFace arrastra `opencv-python` (full, no
  headless) que necesita libGL + GLib + X11. → Verificar que el `Dockerfile`
  (runtime stage) instale `libgl1 libglib2.0-0 libgomp1 libxcb1 libsm6 libxext6
  libxrender1`. Si agregás otra lib ML que use cv2, ya están. Diagnóstico:
  `railway logs | grep -i "shared object"`.

- **Primer selfie tarda ~30-60s o da 502** → el modelo `buffalo_l` (~280 MB) se
  está descargando en caliente porque el pre-cache de build-time falló (host del
  modelo caído ese día). → Mirá los logs de build: `WARN: pre-cache de buffalo_l
  falló`. El runtime lo baja igual (cubierto por `--timeout 120`). Re-deployar
  cuando el host del modelo vuelva lo vuelve a cachear. No es bloqueante.

- **Búsqueda por selfie deshabilitada en prod (`503 no disponible`)** → es a
  propósito, vía `FACE_SEARCH_ENABLED=false`. **Por qué**: la inferencia facial
  es síncrona en el proceso web (por privacidad, ADR 0006); cargar `buffalo_l`
  necesita **~1.1 GB** de RAM aún optimizado (1 worker + sólo los sub-modelos
  detection/recognition/genderage). El servicio `fotos` está **capado a 1 GB**,
  así que cargar el modelo OOM-killeaba el único worker (`Worker was sent
  SIGKILL! Perhaps out of memory?`) → 502 que tiraba TODO el sitio unos segundos.
  El flag corta antes de tocar el modelo y muestra una página amable.
  **Para re-habilitar**, elegí una:
  1. Subir la RAM del servicio `fotos` a ≥2 GB (Railway → servicio → Settings →
     límites, o `railway scale`) y poner `FACE_SEARCH_ENABLED=true`. La RAM se
     factura por uso real (idlea en ~150 MB, sube ~1.1 GB sólo durante una
     búsqueda), así que el costo extra es chico.
  2. Cambiar a un modelo más liviano (`buffalo_s`) en `apps/ml/face_recognition.py`
     (`MODEL_NAME`) — entra en 1 GB pero baja algo la precisión y hay que
     recalibrar los umbrales con `tune_threshold`.
  3. Mover la inferencia a un microservicio aparte con su propia RAM.
  El umbral, el blur de menores y el matching ya están verificados (local) — sólo
  falta la RAM. Local/dev tiene el flag en `true` y la búsqueda anda normal.
