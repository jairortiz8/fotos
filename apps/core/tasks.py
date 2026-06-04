"""Celery tasks de core: backup de DB (Fase 6)."""

from __future__ import annotations

from celery import shared_task

from apps.core.backup import run_db_backup


@shared_task(name="core.backup_database")
def backup_database() -> dict[str, object]:
    """Backup de la DB a R2 (beat 1 AM). Ver apps/core/backup.py + ADR 0010."""
    return run_db_backup()
