"""Vista pública del lightbox de una foto + avatares de caras (visor)."""

from __future__ import annotations

from io import BytesIO

from django.db.models import F
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps.events.metrics import Metric, record_event_metric
from apps.photos.faces import avatar_faces_for_photo
from apps.photos.models import FaceEmbedding, Photo, PhotoStatus


class PhotoLightboxView(View):
    """Lightbox de una foto aprobada. HTMX → solo el contenido del modal."""

    def get(self, request: HttpRequest, slug: str, photo_id: int) -> HttpResponse:
        photo = get_object_or_404(
            Photo.objects.select_related("event", "photographer_link").prefetch_related("bibs"),
            id=photo_id,
            event__slug=slug,
            status=PhotoStatus.APPROVED,
        )

        event = photo.event
        # Solo visible si el evento permite galería pública o búsqueda.
        if not (event.is_public() or event.is_searchable()):
            raise Http404

        # view_count atómico.
        Photo.objects.filter(id=photo.id).update(view_count=F("view_count") + 1)
        record_event_metric(event.id, Metric.VIEW)

        bib_filter = request.GET.get("bib", "").strip()
        prev_photo, next_photo = self._get_siblings(photo, bib_filter)

        photographer_name = (
            photo.photographer_link.photographer_name if photo.photographer_link else "Admin"
        )

        ctx = {
            "photo": photo,
            "event": event,
            "preview_url": photo.get_preview_url(expires_in_seconds=900),
            "prev_photo": prev_photo,
            "next_photo": next_photo,
            "bib_filter": bib_filter,
            "photographer_name": photographer_name,
            "bibs": list(photo.bibs.filter(rejected=False)),
            # Visor: caras grandes/nítidas de ESTA foto, con avatar ya generado.
            "faces": avatar_faces_for_photo(photo),
        }

        template = (
            "public/_lightbox_content.html"
            if getattr(request, "htmx", False)
            else "public/lightbox_page.html"
        )
        return render(request, template, ctx)

    def _get_siblings(self, photo: Photo, bib_filter: str) -> tuple[Photo | None, Photo | None]:
        """Foto anterior/siguiente dentro del mismo evento (y filtro de dorsal)."""
        qs = Photo.objects.filter(event=photo.event, status=PhotoStatus.APPROVED)
        if bib_filter:
            from apps.core.utils import bib_query_variants

            qs = qs.filter(
                bibs__number__in=bib_query_variants(bib_filter), bibs__rejected=False
            ).distinct()
        qs = qs.order_by("capture_time", "created_at")

        ids = list(qs.values_list("id", flat=True))
        try:
            idx = ids.index(photo.id)
        except ValueError:
            return None, None

        prev_id = ids[idx - 1] if idx > 0 else None
        next_id = ids[idx + 1] if idx < len(ids) - 1 else None
        prev_photo = Photo.objects.filter(id=prev_id).first() if prev_id else None
        next_photo = Photo.objects.filter(id=next_id).first() if next_id else None
        return prev_photo, next_photo


class FaceAvatarView(View):
    """Sirve el recorte (webp) de una cara desde R2, con cache largo.

    Mismo patrón que la portada del evento: el bucket es privado, así que en
    vez de exponer una URL firmada (que expira y no cachea) lo servimos por
    acá. El key es inmutable por cara, así que el cache puede ser agresivo.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest, slug: str, face_id: int) -> HttpResponseBase:
        face = get_object_or_404(
            FaceEmbedding.objects.select_related("photo__event").only(
                "id", "avatar_key", "photo__status", "photo__event__slug"
            ),
            id=face_id,
            photo__event__slug=slug,
            photo__status=PhotoStatus.APPROVED,
        )
        if not face.avatar_key:
            raise Http404

        event = face.photo.event
        # Mismo criterio de visibilidad que el lightbox; los invitados entran
        # por su propia vista, que valida la sesión del reviewer.
        if not (event.is_public() or event.is_searchable()):
            raise Http404

        from apps.photos.storage import R2NotConfiguredError, R2UploadError, default_storage

        buf = BytesIO()
        try:
            default_storage().download_fileobj(face.avatar_key, buf)
        except (R2NotConfiguredError, R2UploadError) as exc:
            raise Http404 from exc
        buf.seek(0)

        resp = FileResponse(buf, content_type="image/webp")
        resp["Cache-Control"] = "public, max-age=2592000"  # 30 días (key inmutable)
        return resp
