"""Regenera los thumbnails (calidad actual) de fotos ya procesadas, SIN re-aprobar.

Caso de uso: se subió la calidad de los thumbnails (THUMB_LONG_EDGE / QUALITY en
imaging.py) y se quiere que las fotos YA aprobadas de un evento se vean nítidas,
sin re-correr OCR/caras ni volver a mandarlas a la cola de aprobación.

Encola `photos.regenerate_thumbnail` por foto (el worker hace el trabajo de R2).
El key del thumb es estable → sobrescribe en R2, sin huérfanos.

Ejemplos:
    python manage.py regenerate_thumbnails --event surf-city-2026
    python manage.py regenerate_thumbnails --event surf-city-2026 --previews
    python manage.py regenerate_thumbnails --dry-run          # solo listar
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.photos.models import Photo, PhotoStatus
from apps.photos.tasks import regenerate_thumbnail


class Command(BaseCommand):
    help = "Regenera thumbnails con la calidad actual, sin re-aprobar ni re-OCR."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--event", type=str, default=None, help="Limitar a un evento (slug).")
        parser.add_argument(
            "--previews", action="store_true", help="También regenerar el preview (pierde blur)."
        )
        parser.add_argument("--dry-run", action="store_true", help="Solo listar, no encolar.")

    def handle(self, *args: object, **opts: object) -> None:
        qs = Photo.objects.exclude(status=PhotoStatus.DELETED).exclude(original_key="")
        if opts["event"]:
            qs = qs.filter(event__slug=opts["event"])

        ids = list(qs.values_list("id", flat=True))
        if not ids:
            self.stdout.write(self.style.WARNING("No hay fotos para regenerar."))
            return

        if opts["dry_run"]:
            self.stdout.write(f"[dry-run] {len(ids)} fotos regenerarían su thumbnail.")
            return

        for pid in ids:
            regenerate_thumbnail.delay(pid, include_preview=bool(opts["previews"]))
        self.stdout.write(
            self.style.SUCCESS(f"Encoladas {len(ids)} fotos para regenerar thumbnail.")
        )
