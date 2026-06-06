"""Comando para crear datos de prueba.

Uso:
    python manage.py seed_data            # agrega data sin borrar lo existente
    python manage.py seed_data --clean    # primero limpia todo (excepto users)

Crea:
- 1 superuser `runfoto-admin` con password aleatoria (mostrada al final).
- 3 eventos en distintos estados (live, upcoming, archived).
- 50 fotos placeholder por evento (sólo metadata + R2 keys simulados).
- 2-3 PhotographerLinks por evento (token plano mostrado al final).
- Algunos AuditLogs históricos.
"""

from __future__ import annotations

import datetime as dt
import random
import secrets

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.utils import timezone

# Import directo (no `get_user_model()`) para que mypy entienda los tipos.
from apps.core.models import AuditLog, User
from apps.events.models import Event, EventStatus, EventVisibility
from apps.photographers.models import PhotographerLink
from apps.photos.models import Bib, BibSource, Photo, PhotoStatus

# Nombres y datos plausibles para que el admin no parezca generado por Faker.
EVENTS_SEED = [
    {
        "name": "Maratón de San Salvador 2026",
        "slug": "maraton-san-salvador-2026",
        "date_delta_days": -7,
        "status": EventStatus.LIVE,
        "location": "San Salvador, SV",
        "description": "21K y 42K por el centro histórico.",
    },
    {
        "name": "Trail El Boquerón 2026",
        "slug": "trail-boqueron-2026",
        "date_delta_days": +45,
        "status": EventStatus.UPCOMING,
        "location": "Santa Tecla, SV",
        "description": "Ultra de montaña al volcán de San Salvador.",
    },
    {
        "name": "Nocturna Santa Ana 2025",
        "slug": "nocturna-santa-ana-2025",
        "date_delta_days": -400,
        "status": EventStatus.ARCHIVED,
        "location": "Santa Ana, SV",
        "description": "Carrera urbana nocturna por el centro.",
    },
]

PHOTOGRAPHER_NAMES = [
    "Lucia Pérez",
    "Marcos Vargas",
    "Sofía Argueta",
    "Ricardo Mejía",
]


class Command(BaseCommand):
    help = "Sembra datos de prueba para desarrollo y demos."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Borra Events/Photos/PhotographerLinks/AuditLogs antes de sembrar.",
        )

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        if options.get("clean"):
            self.stdout.write(self.style.WARNING("Limpiando datos previos..."))
            AuditLog.objects.all().delete()
            Bib.objects.all().delete()
            Photo.objects.all().delete()
            PhotographerLink.objects.all().delete()
            Event.objects.all().delete()

        # --- Superuser ---
        admin, raw_password = self._ensure_admin()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Super admin listo:"))
        self.stdout.write(f"  username: {admin.username}")
        if raw_password:
            self.stdout.write(
                self.style.WARNING(
                    f"  password: {raw_password}  (guardalo, no se vuelve a mostrar)"
                )
            )
        else:
            self.stdout.write("  password: (no cambiada — usuario ya existía)")

        # --- Eventos + Photos + Bibs + PhotographerLinks ---
        for event_seed in EVENTS_SEED:
            event = self._seed_event(event_seed)
            self._seed_photographer_links(event)
            self._seed_photos(event, n=50)
            self.stdout.write(self.style.SUCCESS(f"Evento sembrado: {event}"))

        # --- AuditLogs históricos ---
        self._seed_audit_logs(admin)
        self.stdout.write(self.style.SUCCESS("Audit logs sembrados."))
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Seed completado."))
        self.stdout.write("Levantá el server con: python manage.py runserver")
        self.stdout.write("Admin en: http://127.0.0.1:8000/admin/")

    # ---------------------------------------------------------------------
    def _ensure_admin(self) -> tuple[User, str | None]:
        admin, created = User.objects.get_or_create(
            username="runfoto-admin",
            defaults={
                "email": "admin@runfoto.local",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        if created:
            password = secrets.token_urlsafe(16)
            admin.set_password(password)
            admin.save()
            return admin, password
        return admin, None

    def _seed_event(self, seed: dict[str, object]) -> Event:
        delta = int(seed["date_delta_days"])  # type: ignore[call-overload]
        date = timezone.now().date() + dt.timedelta(days=delta)
        defaults = {
            "name": seed["name"],
            "date": date,
            "location": seed["location"],
            "description": seed["description"],
            "status": seed["status"],
            "visibility": EventVisibility.PUBLIC,
        }
        event, _created = Event.objects.update_or_create(
            slug=str(seed["slug"]),
            defaults=defaults,
        )
        # Forzamos resave para que el slug y los `*_until` se calculen.
        event.save()
        return event

    def _seed_photographer_links(self, event: Event) -> None:
        n = random.randint(2, 3)
        for i in range(n):
            name = PHOTOGRAPHER_NAMES[(event.id * 7 + i) % len(PHOTOGRAPHER_NAMES)]
            _link, raw_token = PhotographerLink.generate_token_and_create(
                event,
                name=name,
                email=f"{name.split()[0].lower()}{event.id}@runfoto.local",
                phone=f"+502 5{random.randint(1000_0000, 9999_9999)}",
                photo_limit=200,
            )
            self.stdout.write(f"  → link de {name}: token={raw_token[:10]}... (event={event.slug})")

    def _seed_photos(self, event: Event, *, n: int) -> None:
        statuses = [
            PhotoStatus.APPROVED,
            PhotoStatus.APPROVED,
            PhotoStatus.APPROVED,
            PhotoStatus.PENDING_REVIEW,
        ]  # 75% approved, 25% pending
        for i in range(n):
            status = statuses[i % len(statuses)]
            photo = Photo.objects.create(
                event=event,
                uploaded_by_admin=True,
                original_key=f"events/{event.slug}/originals/{i:04d}.jpg",
                preview_key=f"events/{event.slug}/previews/{i:04d}.webp",
                thumbnail_key=f"events/{event.slug}/thumbs/{i:04d}.webp",
                original_filename=f"DSC_{1000 + i:05d}.jpg",
                width=4000,
                height=6000,
                file_size=3_200_000 + (i * 500),
                capture_time=timezone.now() - dt.timedelta(hours=24 - i // 5),
                camera_make="Sony",
                camera_model="A7 IV",
                lens_model="FE 70-200mm f/2.8",
                aperture="f/2.8",
                shutter_speed="1/2000s",
                iso=400,
                focal_length="200mm",
                status=status,
                approved_at=(timezone.now() if status == PhotoStatus.APPROVED else None),
                approved_by_admin=(status == PhotoStatus.APPROVED),
                has_bibs_detected=True,
            )
            # 1-3 dorsales por foto (algunos números repetidos para que las búsquedas tengan match)
            bib_count = random.randint(1, 3)
            for j in range(bib_count):
                Bib.objects.create(
                    photo=photo,
                    number=str(1000 + ((i * 3 + j) % 80)),
                    confidence=random.uniform(0.7, 0.99),
                    source=BibSource.OCR_PADDLE,
                    bbox={"x": 0.3, "y": 0.4, "w": 0.12, "h": 0.06},
                )

    def _seed_audit_logs(self, admin: User) -> None:
        events = list(Event.objects.all())
        actions = [
            "event.created",
            "event.published",
            "photo.approved",
            "photographer_link.generated",
        ]
        for event in events:
            for action in actions:
                AuditLog.log(
                    action,
                    target=event,
                    user=admin,
                    metadata={"slug": event.slug},
                    ip="127.0.0.1",
                )
