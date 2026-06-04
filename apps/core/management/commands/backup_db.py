"""Backup manual de la DB a R2: `python manage.py backup_db` (Fase 6, ADR 0010)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.core.backup import run_db_backup


class Command(BaseCommand):
    help = "Backup de la base de datos a R2 (pg_dump → gzip → R2). Requiere pg_dump."

    def handle(self, *args: Any, **options: Any) -> None:
        result = run_db_backup()
        if result.get("ok"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backup OK: {result['key']} ({result['size_bytes']} bytes, "
                    f"{result['pruned']} viejos borrados)"
                )
            )
        else:
            self.stdout.write(self.style.WARNING(f"Backup NO realizado: {result.get('reason')}"))
