"""Pre-genera los renders limpios (sin logos) del área de invitados.

Sin esto, la 1ª vez que un invitado abre la galería cada miniatura se genera
on-demand (baja el original de 3-5 MB + re-encodea) → navegación lenta. Este
comando las genera todas de antemano y las deja cacheadas en R2.

    python manage.py warm_reviewer_clean surf-city-2026
    python manage.py warm_reviewer_clean                # todos los reviewer_visible
    python manage.py warm_reviewer_clean surf-city-2026 --sizes thumb
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.events.models import Event, EventStatus
from apps.reviewers.services import warm_event_clean_renders


class Command(BaseCommand):
    help = "Pre-genera los renders limpios (sin logos) para el área de invitados."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "slug",
            nargs="?",
            help="Slug del evento. Sin él, procesa todos los reviewer_visible.",
        )
        parser.add_argument(
            "--sizes",
            default="thumb,preview",
            help="Tamaños a generar, separados por coma (default: thumb,preview).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenera aunque ya existan.",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        sizes = tuple(s.strip() for s in opts["sizes"].split(",") if s.strip())
        qs = Event.objects.filter(reviewer_visible=True).exclude(status=EventStatus.DELETED)
        if opts["slug"]:
            qs = qs.filter(slug=opts["slug"])
            if not qs.exists():
                raise CommandError(f"No hay evento reviewer_visible con slug '{opts['slug']}'.")
        events = list(qs.order_by("-date"))
        if not events:
            self.stdout.write("No hay eventos visibles para invitados.")
            return

        totals = {"generated": 0, "skipped": 0, "errors": 0}
        for event in events:
            self.stdout.write(f"Calentando '{event.slug}' (sizes={','.join(sizes)}) ...")
            stats = warm_event_clean_renders(event, sizes=sizes, force=opts["force"])
            for k in totals:
                totals[k] += stats[k]
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {event.slug}: generadas={stats['generated']} "
                    f"saltadas={stats['skipped']} errores={stats['errors']}"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Total: generadas={totals['generated']} "
                f"saltadas={totals['skipped']} errores={totals['errors']}"
            )
        )
