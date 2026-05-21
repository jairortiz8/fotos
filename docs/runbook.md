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

## Backups

> **Fase 0**: no aplica todavía (no hay datos en producción).
>
> **Fase 1+**: Railway hace snapshots automáticos de Postgres. Documentar
> acá la frecuencia y cómo restaurar.

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

- _(pendiente — se completa cuando aparezcan los primeros incidentes)_
