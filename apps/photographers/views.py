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
from io import BytesIO
from typing import Any

from django.conf import settings
from django.db.models import F
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from apps.core.models import AuditLog, anonymize_ip
from apps.core.utils import get_client_ip
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
@method_decorator(never_cache, name="dispatch")  # el navegador siempre trae el portal fresco
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
            "recent_uploads": link.photos.exclude(status=PhotoStatus.DELETED)
            .prefetch_related("bibs")
            .order_by("-created_at")[:8],
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
    ratelimit(key=upload_ratelimit_key, rate="600/m", method="POST", block=True),
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

        # Duplicados: hash del contenido. Si esta MISMA foto ya está en el evento
        # (no borrada), no la volvemos a subir → el portal la marca "Repetida".
        upload.seek(0)
        content_hash = hashlib.sha256(upload.read()).hexdigest()
        upload.seek(0)
        duplicate_id = (
            Photo.objects.filter(event=link.event, content_hash=content_hash)
            .exclude(status=PhotoStatus.DELETED)
            .values_list("id", flat=True)
            .first()
        )
        if duplicate_id is not None:
            return JsonResponse({"error": "duplicate", "duplicate_of": duplicate_id}, status=409)

        photo = Photo.objects.create(
            event=link.event,
            photographer_link=link,
            uploaded_by_admin=False,
            original_key="",  # se setea tras upload
            original_filename=sanitize_filename(upload.name or ""),
            width=0,
            height=0,
            file_size=upload.size or 0,
            content_hash=content_hash,
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


# ---------------------------------------------------------------------------
# UploadStatusView (GET) — estado de procesamiento de las subidas
#
# El portal hace polling acá para saber cuándo el worker terminó el preview/
# thumbnail (en vez de adivinar con un timeout falso). Filtra por el link del
# token, así un fotógrafo sólo ve el estado de SUS propias fotos.
# ---------------------------------------------------------------------------
@method_decorator(
    ratelimit(key="ip", rate="240/m", method="GET", block=True),
    name="dispatch",
)
class PhotographerUploadStatusView(View):
    """Devuelve `{photos: [{id, status, thumb_url}]}` para los IDs pedidos."""

    http_method_names = ["get"]

    def get(self, request: HttpRequest, token: str) -> HttpResponse:
        link = lookup_link(token)
        if link is None or not is_link_authenticatable(link):
            return JsonResponse({"error": "invalid_link"}, status=410)

        ids: list[int] = []
        for chunk in request.GET.get("ids", "").split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                ids.append(int(chunk))
            if len(ids) >= 50:
                break
        if not ids:
            return JsonResponse({"photos": []})

        photos = Photo.objects.filter(id__in=ids, photographer_link=link)
        data = [
            {
                "id": photo.id,
                "status": photo.status,
                "thumb_url": photo.get_thumbnail_url() if photo.thumbnail_key else "",
            }
            for photo in photos
        ]
        return JsonResponse({"photos": data})


# ---------------------------------------------------------------------------
# Imagen destacada de la carpeta del fotógrafo
# ---------------------------------------------------------------------------
class PhotographerCoverView(View):
    """Sirve la imagen destacada (webp) de la carpeta del fotógrafo desde R2,
    con cache. Pública (la portada de la carpeta se ve en la galería del evento).
    URL versionada con `?v=` → cache largo sin quedar vieja."""

    http_method_names = ["get"]

    def get(self, request: HttpRequest, link_id: int) -> HttpResponseBase:
        link = get_object_or_404(PhotographerLink, id=link_id)
        if not link.featured_image_key:
            raise Http404

        buf = BytesIO()
        try:
            default_storage().download_fileobj(link.featured_image_key, buf)
        except (R2NotConfiguredError, R2UploadError) as exc:
            raise Http404 from exc
        buf.seek(0)
        resp = FileResponse(buf, content_type="image/webp")
        resp["Cache-Control"] = "public, max-age=604800"  # 7 días (URL versionada)
        return resp


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(
    ratelimit(key=upload_ratelimit_key, rate="20/m", method="POST", block=True),
    name="dispatch",
)
class PhotographerFeaturedUploadView(View):
    """El fotógrafo sube la imagen destacada de su carpeta (autenticado por token).
    La procesa a webp → R2 → `featured_image_key`. csrf_exempt: el token URL es la
    autenticación (igual que el upload de fotos)."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, token: str) -> HttpResponse:
        link = lookup_link(token)
        if link is None or not is_link_authenticatable(link):
            return JsonResponse({"error": "invalid_link"}, status=410)

        upload = request.FILES.get("file")
        if not upload:
            return JsonResponse({"error": "no_file"}, status=400)
        if upload.size and upload.size > settings.PHOTO_UPLOAD_MAX_BYTES:
            return JsonResponse({"error": "file_too_large"}, status=400)

        from PIL import UnidentifiedImageError

        from apps.photos.imaging import process_photographer_cover

        try:
            key = process_photographer_cover(upload, link.id)
        except UnidentifiedImageError:
            return JsonResponse({"error": "invalid_format"}, status=400)
        except R2NotConfiguredError:
            return JsonResponse({"error": "storage_not_configured"}, status=503)
        except (R2UploadError, OSError):
            logger.exception("Falló la imagen destacada (link=%s)", link.id)
            return JsonResponse({"error": "upload_failed"}, status=500)

        link.featured_image_key = key
        link.save(update_fields=["featured_image_key", "updated_at"])
        AuditLog.log(
            "photographer_link.featured_set",
            target=link,
            metadata={"event_slug": link.event.slug},
            ip=get_client_ip(request),
        )
        return JsonResponse({"featured_url": link.featured_url()})
