#!/bin/sh
# ============================================================================
# Entrypoint único para los 3 roles del mismo image en Railway.
#
# El rol se elige con la env var PROCESS_TYPE (default: web):
#   web         → migraciones + bootstrap del superadmin + gunicorn
#   worker      → celery worker: colas `celery,faces,fast` (InsightFace ~2GB para
#                 el selfie; con OCR_BACKEND=gemini no carga engines de OCR)
#   worker_fast → celery worker SÓLO cola `fast` (preview/thumbnail + OCR), SIN
#                 InsightFace. OPCIONAL: para eventos grandes, corré este servicio
#                 aparte → los previews salen al instante sin quedar detrás de las
#                 tareas de cara (~15s) del worker pesado. El indexado de selfie
#                 se pone al día en segundo plano en `worker`.
#   beat        → celery beat (crons de retención/cleanup/backup de Fase 6)
#
# Los servicios de Railway corren ESTA misma imagen; solo cambia PROCESS_TYPE.
# Así no hay que mantener un "start command" por servicio en el dashboard.
# ============================================================================
set -e

ROLE="${PROCESS_TYPE:-web}"
echo "[entrypoint] arrancando rol: ${ROLE}"

case "$ROLE" in
  worker)
    # Worker ÚNICO: `celery` (crons), `faces` (InsightFace ~2GB, selfie) y `fast`
    # (preview/thumbnail + OCR vía Gemini API — los engines locales sólo cargan
    # si la API falla y entra el fallback). concurrency 1 = un proceso, una sola
    # copia de los modelos (2 procesos cargando engines fue el OOM-stall del
    # incidente del 2026-06-09; no repetir).
    # Colas parametrizables: si corrés un `worker_fast` aparte, podés setear
    # WORKER_QUEUES=celery,faces en ESTE servicio para dedicarlo a las caras
    # (default: las 3, así funciona igual sin el worker_fast).
    exec celery -A config worker --loglevel=info -Q "${WORKER_QUEUES:-celery,faces,fast}" \
      --concurrency="${CELERY_CONCURRENCY:-1}"
    ;;
  worker_fast)
    # Worker LIVIANO dedicado SÓLO a la cola `fast` (preview/thumbnail + OCR vía
    # Gemini). NO consume `faces` → NUNCA carga InsightFace → RAM baja y los
    # previews salen al instante, sin quedar detrás de las tareas de cara del
    # worker pesado. Para eventos grandes: garantiza que las fotos no se vean
    # "muertas" mientras el indexado de selfie se pone al día en `worker`.
    # Concurrency 2 por default (tareas de I/O livianas, sin modelo en RAM).
    # (Si Gemini cayera en masa, el fallback de OCR local carga engines pesados
    #  → subí la RAM del servicio o bajá CELERY_FAST_CONCURRENCY a 1.)
    exec celery -A config worker --loglevel=info -Q fast \
      --concurrency="${CELERY_FAST_CONCURRENCY:-2}"
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
