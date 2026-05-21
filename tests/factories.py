"""Factories factory-boy para todos los modelos de RunFoto.

Convenciones:
- Una factory base por modelo + subfactories para estados comunes.
- Defaults sensatos (nada de "lorem ipsum 50 caracteres" si una palabra alcanza).
- Embeddings y bbox usan datos de prueba estables (no random) para reproducibilidad.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.models import AuditLog, UserMFA
from apps.events.models import Event, EventStatus, EventVisibility
from apps.photographers.models import PhotographerLink, _hash_token
from apps.photos.models import Bib, BibSource, FaceEmbedding, Photo, PhotoStatus
from apps.privacy.models import DataDeletionRequest, DeletionStatus

User = get_user_model()


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda u: f"{u.username}@runfoto.local")
    first_name = "Test"
    last_name = "User"
    is_active = True
    is_staff = False
    is_superuser = False
    password = factory.PostGenerationMethodCall("set_password", "test-pass-1234")


class SuperUserFactory(UserFactory):
    is_staff = True
    is_superuser = True


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------
class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Event
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Carrera de prueba {n}")
    slug = factory.Sequence(lambda n: f"carrera-prueba-{n}")
    date = factory.LazyFunction(lambda: timezone.now().date())
    location = "Guatemala City, GT"
    description = "Evento de prueba"
    status = EventStatus.LIVE
    visibility = EventVisibility.PUBLIC


class LiveEventFactory(EventFactory):
    status = EventStatus.LIVE
    date = factory.LazyFunction(lambda: timezone.now().date())


class ArchivedEventFactory(EventFactory):
    status = EventStatus.ARCHIVED
    # Fecha vieja para que archive_until ya esté en el pasado.
    date = factory.LazyFunction(lambda: (timezone.now() - dt.timedelta(days=400)).date())


class PermanentArchiveEventFactory(EventFactory):
    permanent_archive = True
    status = EventStatus.LIVE


# ---------------------------------------------------------------------------
# PhotographerLink
# ---------------------------------------------------------------------------
class PhotographerLinkFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PhotographerLink

    event = factory.SubFactory(EventFactory)
    photographer_name = factory.Sequence(lambda n: f"Fotógrafo {n}")
    photographer_email = factory.LazyAttribute(
        lambda link: f"{link.photographer_name.lower().replace(' ', '.')}@runfoto.local"
    )
    # En tests usamos un token determinístico para poder verify_token() después.
    token_hash = factory.Sequence(lambda n: _hash_token(f"test-token-{n}"))
    expires_at = factory.LazyFunction(lambda: timezone.now() + dt.timedelta(days=30))
    is_active = True


class ExpiredPhotographerLinkFactory(PhotographerLinkFactory):
    expires_at = factory.LazyFunction(lambda: timezone.now() - dt.timedelta(days=1))


class RevokedPhotographerLinkFactory(PhotographerLinkFactory):
    is_active = False
    revoked_at = factory.LazyFunction(timezone.now)
    revoked_reason = "test_revocation"


# ---------------------------------------------------------------------------
# Photo + Bib + FaceEmbedding
# ---------------------------------------------------------------------------
class PhotoFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Photo

    event = factory.SubFactory(EventFactory)
    photographer_link = None
    uploaded_by_admin = True
    original_key = factory.Sequence(lambda n: f"events/test/originals/{n:06d}.jpg")
    preview_key = factory.LazyAttribute(lambda p: p.original_key.replace("originals", "previews"))
    thumbnail_key = factory.LazyAttribute(lambda p: p.original_key.replace("originals", "thumbs"))
    original_filename = factory.Sequence(lambda n: f"DSC{n:05d}.jpg")
    width = 4000
    height = 6000
    file_size = 3_500_000
    status = PhotoStatus.PENDING_REVIEW


class ApprovedPhotoFactory(PhotoFactory):
    status = PhotoStatus.APPROVED
    approved_at = factory.LazyFunction(timezone.now)
    approved_by_admin = True


class PendingPhotoFactory(PhotoFactory):
    status = PhotoStatus.PENDING_REVIEW


class BibFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Bib

    photo = factory.SubFactory(PhotoFactory)
    number = factory.Sequence(lambda n: str(1000 + n))
    confidence = 0.92
    source = BibSource.OCR_PADDLE
    bbox = factory.LazyFunction(lambda: {"x": 0.3, "y": 0.4, "w": 0.1, "h": 0.05})


class FaceEmbeddingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FaceEmbedding

    photo = factory.SubFactory(PhotoFactory)
    # Vector estable para tests: 512-d con valores incrementales pequeños.
    embedding = factory.LazyFunction(lambda: [0.01 * i for i in range(512)])
    bbox = factory.LazyFunction(lambda: {"x": 0.4, "y": 0.2, "w": 0.15, "h": 0.2})
    estimated_age = 28
    is_minor = False


class MinorFaceEmbeddingFactory(FaceEmbeddingFactory):
    estimated_age = 14
    is_minor = True


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------
class AuditLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditLog

    user = factory.SubFactory(SuperUserFactory)
    action = "event.created"
    target_type = "Event"
    target_id = factory.Sequence(lambda n: str(n))
    metadata = factory.LazyFunction(dict)
    ip_address = "192.168.1.0"


# ---------------------------------------------------------------------------
# UserMFA
# ---------------------------------------------------------------------------
class UserMFAFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserMFA

    user = factory.SubFactory(SuperUserFactory)
    totp_secret = None
    backup_codes = factory.LazyFunction(list)
    is_active = False


# ---------------------------------------------------------------------------
# DataDeletionRequest
# ---------------------------------------------------------------------------
class DataDeletionRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DataDeletionRequest

    matched_photo_count = 0
    deleted_photo_count = 0
    deleted_embedding_count = 0
    status = DeletionStatus.PENDING
    requester_ip_hash = factory.LazyFunction(lambda: hashlib.sha256(b"192.168.1.1").hexdigest())


__all__ = [
    "ApprovedPhotoFactory",
    "ArchivedEventFactory",
    "AuditLogFactory",
    "BibFactory",
    "DataDeletionRequestFactory",
    "EventFactory",
    "ExpiredPhotographerLinkFactory",
    "FaceEmbeddingFactory",
    "LiveEventFactory",
    "MinorFaceEmbeddingFactory",
    "PendingPhotoFactory",
    "PermanentArchiveEventFactory",
    "PhotoFactory",
    "PhotographerLinkFactory",
    "RevokedPhotographerLinkFactory",
    "SuperUserFactory",
    "UserFactory",
    "UserMFAFactory",
]


def _unused_keep_typing_imports() -> Any:  # pragma: no cover
    """Keep optional imports referenced."""
    return None
