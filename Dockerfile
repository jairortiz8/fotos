# syntax=docker/dockerfile:1.7
# ============================================================================
# Dockerfile multi-stage para RunFoto
#
# Stages:
#   1. tailwind-builder  — Node 20 compila el CSS de Tailwind v4 via postcss.
#   2. python-builder    — Python 3.12; instala wheels (todas manylinux, sin
#                          necesidad de build-essential ni libs -dev).
#   3. runtime           — Imagen final liviana; solo runtime libs + código.
# ============================================================================

# ----------------------------------------------------------------------------
# 1) Tailwind CSS build (Node)
#
# Importante: en Tailwind v4 el plugin es @tailwindcss/postcss, NO existe
# un binario `tailwindcss` invocable con `npx`. La compilación se hace con
# `npm run build` que usa postcss-cli + @tailwindcss/postcss (definido en
# theme/static_src/package.json y theme/static_src/postcss.config.js).
# ----------------------------------------------------------------------------
FROM node:20-alpine AS tailwind-builder
WORKDIR /workspace

# Tailwind escanea estos paths según los @source en theme/static_src/src/styles.css.
COPY theme/ ./theme/
COPY templates/ ./templates/
COPY apps/ ./apps/

WORKDIR /workspace/theme/static_src

RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
RUN npm run build

# Output esperado: /workspace/theme/static/css/dist/styles.css

# ----------------------------------------------------------------------------
# 2) Python builder (sin build-essential — wheels manylinux alcanzan)
# ----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS python-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Copiamos solo lo mínimo necesario para que setuptools resuelva packages.
COPY pyproject.toml README.md ./
COPY apps/__init__.py apps/__init__.py
COPY config/__init__.py config/__init__.py

# EasyOCR depende de torch. Por default pip baja torch con las librerías CUDA
# (~1.5 GB de GPU que NO usamos — hacemos OCR en CPU). Instalamos torch+cpu
# PRIMERO desde el índice CPU; cuando easyocr resuelva sus deps, ve que torch
# ya está satisfecho y no baja la versión CUDA. Imagen: ~3 GB → ~1.5 GB.
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir .

# ----------------------------------------------------------------------------
# 3) Runtime (imagen final, sin build tools)
# ----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=8000 \
    PATH="/usr/local/bin:${PATH}"

WORKDIR /app

# Runtime libs:
#  - Pillow: libjpeg/libwebp/libpng
#  - OpenCV (cv2, dependencia de InsightFace): libGL + GLib + X11 (libxcb, etc.).
#    Aunque usamos opencv-python-headless, InsightFace arrastra opencv-python
#    completo como dep transitiva y su .so necesita estas libs. Sin ellas el
#    import de cv2 falla con "libxcb.so.1: cannot open shared object file" y la
#    búsqueda por selfie devuelve 500.
#  - onnxruntime (inferencia del modelo): libgomp (OpenMP).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        libwebp7 \
        libpng16-16 \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libxcb1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root.
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

# Paquetes Python ya instalados desde el builder.
COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

# --- Pre-cache del modelo facial buffalo_l (~280 MB) ---
# La búsqueda por selfie es SÍNCRONA (corre en el proceso web, por privacidad).
# Sin pre-cache, el primer request descargaría el modelo en caliente (~30-60s) y
# cada reinicio del dyno lo re-descargaría (FS efímero). Lo bajamos en build-time
# a /opt/insightface y apuntamos INSIGHTFACE_ROOT ahí.
# Best-effort (`|| true`): si el host del modelo está caído, NO rompemos el
# deploy — el modelo se baja en runtime (cubierto por --timeout 120 en gunicorn).
ENV INSIGHTFACE_ROOT=/opt/insightface
RUN mkdir -p /opt/insightface \
 && python -c "import insightface; insightface.app.FaceAnalysis(name='buffalo_l', root='/opt/insightface', providers=['CPUExecutionProvider']).prepare(ctx_id=0, det_size=(640,640))" \
 || echo "WARN: pre-cache de buffalo_l falló; se descargará en runtime." \
 && chown -R app:app /opt/insightface

# Código de la app.
COPY --chown=app:app . .

# CSS de Tailwind ya compilado.
COPY --from=tailwind-builder --chown=app:app /workspace/theme/static/css/dist/styles.css /app/theme/static/css/dist/styles.css

# collectstatic. SECRET_KEY dummy solo para que Django arranque durante el build.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    SECRET_KEY=build-time-dummy \
    ALLOWED_HOSTS=* \
    DATABASE_URL=postgres://u:p@localhost/d \
    REDIS_URL=redis://localhost:6379/0 \
    CELERY_BROKER_URL=redis://localhost:6379/1 \
    CELERY_RESULT_BACKEND=redis://localhost:6379/2 \
    python manage.py collectstatic --noinput

# gunicorn 23 abre un "control server" que escribe en el CWD (/app). El dir /app
# lo crea WORKDIR como root; sin esto el proceso `app` no puede escribir ahí y
# loggea "Permission denied: '/app/.gunicorn'". chown del nodo de directorio.
RUN chown app:app /app

USER app
EXPOSE 8000

# Healthcheck (Docker; Railway tiene el suyo en railway.toml).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/healthz/lite || exit 1

# Un solo entrypoint para los 3 roles (web / worker / beat). El rol se elige con
# la env var PROCESS_TYPE (default: web). Toda la lógica (migraciones, bootstrap
# del superadmin, flags de gunicorn/celery y su porqué) vive en
# scripts/entrypoint.sh, así los 3 servicios de Railway comparten ESTA misma
# imagen sin tener que setear un start-command por servicio en el dashboard.
CMD ["sh", "/app/scripts/entrypoint.sh"]
