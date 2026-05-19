"""RunFoto — config package.

Importa la app de Celery al inicio para que el decorador `@shared_task`
funcione en todo el proyecto.
"""

from __future__ import annotations

from .celery import app as celery_app

__all__ = ["celery_app"]
