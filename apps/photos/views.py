"""Vista pública del lightbox de una foto."""

from __future__ import annotations

from django.db.models import F
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps.photos.models import Photo, PhotoStatus


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
