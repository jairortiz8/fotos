"""Celery app — RunFoto.

Se inicia automáticamente al importar `config` (ver `config/__init__.py`).
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("runfoto")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:
    """Health-check task. Útil para verificar que el broker esté OK."""
    print(f"Request: {self.request!r}")
