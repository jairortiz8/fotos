"""Vistas públicas del portal del fotógrafo (`/u/<token>/`).

NO requiere cuenta — la autenticación es el token URL único.
Validamos el token en CADA request (no confiamos en sesiones).

Rate limiting:
- GET `/u/<token>/`: 60 requests/min por IP (carga del portal).
- POST `/u/<token>/upload/`: 100 fotos/min por token (anti-flood pero permite ráfagas).
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
import uuid
from typing import Any

from django.conf import settings
from django.db.models import F
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from apps.core.models import AuditLog, anonymize_ip
from apps.photographers.models import PhotographerLink
from apps.photos.models import Photo, PhotoStatus
from apps.photos.storage import (
    R2NotConfiguredError,
    R2UploadError,
    default_storage,
    key_for_original,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_client_ip(request: HttpRequest) -> str | None:
    """Extrae IP del cliente respetando X-Forwarded-For (Railway está detrás de proxy)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "").strip()
    if xff:
        # XFF puede tener "client, proxy1, proxy2" — nos quedamos con el primero.
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


_FILENAME_BAD = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """Filename seguro para guardar (sólo ASCII + . _ -)."""
    if not name:
        return "photo.jpg"
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    cleaned = _FILENAME_BAD.sub("_", ascii_name).strip("._")
    return cleaned[:200] or "photo.jpg"


def is_valid_jpeg(uploaded_file: Any) -> bool:
    """Verifica que el archivo arranque con magic bytes de JPEG.

    Pillow puede abrirlo después para extra validación; acá hacemos check rápido
    sin descomprimir.
    """
    head = uploaded_file.read(3)
    uploaded_file.seek(0)
    return head[:3] == b"\xff\xd8\xff"


def lookup_link(raw_token: str) -> PhotographerLink | None:
    """Resuelve el link por token sin validar uso."""
    try:
        return PhotographerLink.objects.select_related("event").get(
            token_hash=hash_token(raw_token)
        )
    except PhotographerLink.DoesNotExist:
        return None


def get_valid_link(raw_token: str) -> PhotographerLink | None:
    """Resuelve + valida (active, no expirado, no revocado, dentro de limit)."""
    link = lookup_link(raw_token)
    if link is None or not link.is_valid():
        return None
    return link


def is_link_authenticatable(link: PhotographerLink) -> bool:
    """Más laxo que `is_valid()`: ignora photo_limit.

    Cuando el upload toca el límite queremos devolver 403 con detalle, no 410
    genérico. Por eso separamos "el token coincide y la sesión está viva" de
    "puede subir una foto más".
    """
    if not link.is_active or link.revoked_at is not None:
        return False
    return link.expires_at > timezone.now()


def upload_ratelimit_key(group: str, request: HttpRequest) -> str:
    """Rate limit por token (no por IP) en el endpoint de upload.

    Si no se puede extraer el token, usamos IP como fallback razonable.
    """
    token = request.resolver_match.kwargs.get("token") if request.resolver_match else None
    return token or (get_client_ip(request) or "anonymous")


# ---------------------------------------------------------------------------
# PortalView (GET)
# ---------------------------------------------------------------------------
@method_decorator(
    ratelimit(key="ip", rate="60/m", method="GET", block=True),
    name="dispatch",
)
class PhotographerPortalView(View):
    """Página principal del portal — drag-and-drop + cola de subidas."""

    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        link = get_valid_link(token)
        if link is None:
            return self._invalid_link_response(request, token)

        self._record_use(request, link)

        ctx = {
            "link": link,
            "event": link.event,
            "token": token,
            "photos_uploaded": link.photos_uploaded,
            "photo_limit": link.photo_limit,
            "max_upload_mb": settings.PHOTO_UPLOAD_MAX_BYTES // (1024 * 1024),
            "recent_uploads": link.photos.exclude(status=PhotoStatus.DELETED).order_by(
                "-created_at"
            )[:8],
        }
        return render(request, "photographer/portal.html", ctx)

    def _record_use(self, request: HttpRequest, link: PhotographerLink) -> None:
        ip = get_client_ip(request)
        PhotographerLink.objects.filter(pk=link.pk).update(
            last_used_at=timezone.now(),
            last_used_ip=anonymize_ip(ip) if ip else None,
        )

    def _invalid_link_response(self, request: HttpRequest, token: str) -> HttpResponse:
        return render(
            request,
            "photographer/invalid_link.html",
            {"token_fragment": token[:6] if token else ""},
            status=410,
        )


# ---------------------------------------------------------------------------
# UploadView (POST)
#
# `csrf_exempt`: el endpoint usa el token URL único como autenticación. No hay
# sesión que defender, así que CSRF no aporta seguridad real — sólo bloquearía
# clientes legítimos (apps mobiles, curl, etc.). El rate limit por token + la
# validación del hash son la defensa real.
# ---------------------------------------------------------------------------
@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(
    ratelimit(key=upload_ratelimit_key, rate="100/m", method="POST", block=True),
    name="dispatch",
)
class PhotographerUploadView(View):
    """Recibe UN archivo por request (HTMX dispara request por archivo)."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, token: str) -> HttpResponse:
        link = lookup_link(token)
        if link is None or not is_link_authenticatable(link):
            return JsonResponse({"error": "invalid_link"}, status=410)

        # El límite tiene su propio status code (403) — distinto de 410 (token muerto).
        if link.photo_limit is not None and link.photos_uploaded >= link.photo_limit:
            return JsonResponse({"error": "photo_limit_reached"}, status=403)

        upload = request.FILES.get("file")
        if not upload:
            return JsonResponse({"error": "no_file"}, status=400)

        max_bytes = settings.PHOTO_UPLOAD_MAX_BYTES
        if upload.size > max_bytes:
            return JsonResponse(
                {"error": "file_too_large", "max_mb": max_bytes // (1024 * 1024)},
                status=400,
            )

        if not is_valid_jpeg(upload):
            return JsonResponse(
                {"error": "invalid_format", "allowed": ["jpg", "jpeg"]},
                status=400,
            )

        photo = Photo.objects.create(
            event=link.event,
            photographer_link=link,
            uploaded_by_admin=False,
            original_key="",  # se setea tras upload
            original_filename=sanitize_filename(upload.name or ""),
            width=0,
            height=0,
            file_size=upload.size or 0,
            status=PhotoStatus.UPLOADING,
        )

        photo_uid = uuid.uuid4().hex
        key = key_for_original(link.event.slug, photo_uuid=photo_uid)
        try:
            default_storage().upload(upload, key, content_type="image/jpeg")
        except R2NotConfiguredError:
            photo.delete()
            return JsonResponse(
                {
                    "error": "storage_not_configured",
                    "hint": "R2 todavía no está configurado en este entorno.",
                },
                status=503,
            )
        except R2UploadError:
            logger.exception("R2 upload falló (photo=%s)", photo.id)
            photo.delete()
            return JsonResponse({"error": "upload_failed"}, status=500)

        photo.original_key = key
        photo.status = PhotoStatus.PROCESSING
        photo.save(update_fields=["original_key", "status", "updated_at"])

        # Disparar pipeline async (no bloqueante).
        from apps.photos.tasks import process_photo

        process_photo.delay(photo.id)

        # Bump counter del link.
        PhotographerLink.objects.filter(pk=link.pk).update(
            photos_uploaded=F("photos_uploaded") + 1,
            last_used_at=timezone.now(),
        )

        AuditLog.log(
            "photo.uploaded",
            target=photo,
            metadata={
                "event_slug": link.event.slug,
                "photographer_link_id": link.id,
                "filename": photo.original_filename,
            },
            ip=get_client_ip(request),
        )

        if getattr(request, "htmx", False):
            return render(request, "photographer/_upload_row.html", {"photo": photo})

        return JsonResponse(
            {
                "id": photo.id,
                "status": photo.status,
                "key": photo.original_key,
            }
        )
