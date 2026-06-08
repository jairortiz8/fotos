#!/bin/sh
# ============================================================================
# Entrypoint único para los 3 roles del mismo image en Railway.
#
# El rol se elige con la env var PROCESS_TYPE (default: web):
#   web    → migraciones + bootstrap del superadmin + gunicorn
#   worker → celery worker (procesa fotos: preview/thumbnail + OCR de dorsal)
#   beat   → celery beat (crons de retención/cleanup/backup de Fase 6)
#
# Los 3 servicios de Railway corren ESTA misma imagen; solo cambia PROCESS_TYPE.
# Así no hay que mantener un "start command" por servicio en el dashboard.
# ============================================================================
set -e

ROLE="${PROCESS_TYPE:-web}"
echo "[entrypoint] arrancando rol: ${ROLE}"

case "$ROLE" in
  worker)
    # concurrency 1 = una foto a la vez → poca RAM (decisión de costo). En prod
    # el modelo facial está apagado (FACE_PROCESSING_ENABLED=False), así que el
    # worker solo hace preview/thumbnail + OCR y se mantiene liviano.
    exec celery -A config worker --loglevel=info --concurrency="${CELERY_CONCURRENCY:-1}"
    ;;
  beat)
    # --schedule en /tmp: el FS del contenedor es efímero y el schedule estático
    # vive en settings (CELERY_BEAT_SCHEDULE); no hace falta persistirlo.
    exec celery -A config beat --loglevel=info --schedule=/tmp/celerybeat-schedule
    ;;
  web | *)
    # Migraciones idempotentes + bootstrap del superadmin desde DJANGO_SUPERUSER_*
    # (|| true: si ya existe o faltan las vars, no rompe el deploy; no cambia la
    # pass de un usuario ya creado).
    python manage.py migrate --noinput
    python manage.py createsuperuser --noinput 2>/dev/null || true
    # --timeout 120: si la búsqueda por selfie estuviera habilitada, el 1er
    #   request carga buffalo_l (~5-10s) y el default de 30s lo mataría.
    # --workers 1 --threads 8: UNA sola copia del modelo en RAM, compartida por
    #   los threads (onnxruntime + boto3 liberan el GIL en I/O). 8 threads =
    #   hasta 8 requests simultáneas (subidas + búsquedas) sin sumar RAM apenas.
    #   Para más fotógrafos a la vez, subir WEB_THREADS (barato) o WEB_CONCURRENCY
    #   (suma ~1GB de RAM por worker, porque cada worker recarga el modelo).
    exec gunicorn config.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-1}" \
      --threads "${WEB_THREADS:-8}" \
      --timeout "${WEB_TIMEOUT:-120}" \
      --access-logfile -
    ;;
esac
