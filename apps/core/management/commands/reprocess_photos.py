"""Re-encola el procesamiento de fotos atascadas (sin preview).

Caso de uso: se subieron fotos SIN que el worker de Celery estuviera corriendo,
así que quedaron en `processing` y sin preview/thumbnail (se ven negras). Una
vez que el worker está activo, este comando las vuelve a encolar en
`process_photo` para que las procese.

Ejemplos:
    python manage.py reprocess_photos                  # todas las sin preview
    python manage.py reprocess_photos --event maraton  # solo ese evento
    python manage.py reprocess_photos --all            # todas (re-genera preview)
    python manage.py reprocess_photos --dry-run        # solo listar
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.photos.models import Photo, PhotoStatus
from apps.photos.tasks import process_photo


class Command(BaseCommand):
    help = "Re-encola process_photo para fotos sin preview (atascadas sin worker)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--event", type=str, default=None, help="Limitar a un evento por slug.")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Reprocesar TODAS, no solo las que no tienen preview.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Solo listar, no encolar.")

    def handle(self, *args: object, **opts: object) -> None:
        qs = Photo.objects.exclude(status=PhotoStatus.DELETED)
        if opts["event"]:
            qs = qs.filter(event__slug=opts["event"])
        if not opts["all"]:
            qs = qs.filter(Q(preview_key="") | Q(preview_key__isnull=True))

        ids = list(qs.values_list("id", flat=True))
        if not ids:
            self.stdout.write(self.style.WARNING("No hay fotos para reprocesar."))
            return

        if opts["dry_run"]:
            self.stdout.write(f"[dry-run] {len(ids)} fotos: {ids}")
            return

        for pid in ids:
            process_photo.delay(pid)
        self.stdout.write(self.style.SUCCESS(f"Re-encoladas {len(ids)} fotos: {ids}"))
