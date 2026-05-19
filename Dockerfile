# syntax=docker/dockerfile:1.7
# ============================================================================
# Dockerfile multi-stage para RunFoto
#
# Stages:
#   1. tailwind-builder  — Node 20 compila el CSS de Tailwind.
#   2. python-builder    — Python 3.12 + build deps; instala wheels Python.
#   3. runtime           — Imagen final liviana; solo runtime deps + código.
# ============================================================================

# ----------------------------------------------------------------------------
# 1) Tailwind CSS build (Node)
# ----------------------------------------------------------------------------
FROM node:20-alpine AS tailwind-builder
WORKDIR /tw

# Copiamos primero los lockfiles para aprovechar caché de Docker.
COPY theme/static_src/package.json theme/static_src/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

# Copiamos el resto del proyecto Tailwind y los templates/apps que Tailwind
# escanea (content paths).
COPY theme/static_src/ ./
COPY templates/ /workspace/templates/
COPY apps/ /workspace/apps/

# Output: /workspace/theme/static/css/dist/styles.css (lo copiamos a la final).
RUN mkdir -p /workspace/theme/static/css/dist && \
    npx tailwindcss \
        -i ./src/styles.css \
        -o /workspace/theme/static/css/dist/styles.css \
        --minify

# ----------------------------------------------------------------------------
# 2) Python builder (compila wheels donde haga falta)
# ----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS python-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libjpeg-dev \
        zlib1g-dev \
        libwebp-dev \
        libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiamos solo lo mínimo necesario para resolver dependencias.
COPY pyproject.toml README.md ./
COPY apps/__init__.py apps/__init__.py
COPY config/__init__.py config/__init__.py

RUN pip install --upgrade pip setuptools wheel \
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

# Runtime deps (sin -dev).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libjpeg62-turbo \
        libwebp7 \
        libpng16-16 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root.
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

# Paquetes Python ya instalados desde el builder.
COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

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

USER app
EXPOSE 8000

# Healthcheck (Docker; Railway tiene el suyo en railway.toml).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PORT}/healthz || exit 1

# Default command: web. Worker y beat overridean en railway.toml / compose.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 3 --access-logfile -"]
