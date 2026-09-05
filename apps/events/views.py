"""Vistas públicas de eventos: landing + galería + búsqueda por dorsal."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import F
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic import TemplateView

from apps.core.utils import (
    bib_query_variants,
    check_bib_specific_rate_limit,
    check_general_search_rate_limit,
    generate_ocr_variants,
    is_valid_bib_format,
    normalize_bib_query,
)
from apps.events.metrics import Metric, record_event_metric
from apps.events.models import Event, EventStatus, EventVisibility
from apps.photos.models import Bib, Photo, PhotoStatus

GALLERY_PAGE_SIZE = 60
SEARCH_CACHE_TTL = 300  # 5 minutos
MAX_SEARCH_RESULTS = 200

# Estados en los que la galería pública (grid completo) está visible.
PUBLIC_GALLERY_STATUSES = {EventStatus.UPCOMING, EventStatus.LIVE, EventStatus.PUBLIC_CLOSED}
# Estados que aparecen listados en el home.
HOME_LISTED_STATUSES = {EventStatus.UPCOMING, EventStatus.LIVE, EventStatus.PUBLIC_CLOSED}


# ---------------------------------------------------------------------------
# HomeView — landing pública
# ---------------------------------------------------------------------------
class HomeView(TemplateView):
    template_name = "public/home.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        events = list(
            Event.objects.filter(
                visibility=EventVisibility.PUBLIC,
                status__in=HOME_LISTED_STATUSES,
            ).order_by("-date")[:12]
        )
        ctx["events"] = events
        ctx["live_count"] = sum(1 for e in events if e.status == EventStatus.LIVE)
        return ctx


# ---------------------------------------------------------------------------
# EventGalleryView — galería + búsqueda por dorsal
# ---------------------------------------------------------------------------
class EventGalleryView(View):
    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)

        # Visibilidad privada o evento ya borrado → 404.
        if event.visibility == EventVisibility.PRIVATE or event.status in {
            EventStatus.DRAFT,
            EventStatus.DELETED,
        }:
            raise Http404

        # Archivado / pendiente de borrado → 404 amigable público.
        if event.status in {EventStatus.ARCHIVED, EventStatus.PENDING_DELETION}:
            return render(request, "public/event_archived.html", {"event": event}, status=404)

        bib_query = request.GET.get("bib", "").strip()
        if bib_query:
            return self._handle_bib_search(request, event, bib_query)

        # ?cara=<id> → "las fotos de esta persona" (click en el visor). Es una
        # búsqueda, así que vale igual con la galería cerrada pero searchable.
        face_query = request.GET.get("cara", "").strip()
        if face_query.isdigit():
            return self._handle_face_search(request, event, int(face_query))

        # Sin query: si la galería pública no está abierta mostramos una pantalla
        # intermedia (con buscador por dorsal). Distinguimos dos casos para no
        # confundir:
        #   - UPCOMING ("Próximo"): el evento todavía NO abrió → "próximamente".
        #   - public_closed / searchable_only / public_until pasado: ya cerró por
        #     retención → "galería cerrada, buscá por dorsal".
        gallery_open = event.is_public() and event.status in PUBLIC_GALLERY_STATUSES
        if not gallery_open:
            if event.is_searchable():
                return render(
                    request,
                    "public/event_closed.html",
                    {"event": event, "is_upcoming": event.status == EventStatus.UPCOMING},
                )
            raise Http404

        # Modos de navegación (sólo con galería abierta):
        #   ?vista=fotografos → "carpetas" por fotógrafo
        #   ?fotografo=<id>   → las fotos de ese fotógrafo (cronológicas)
        if request.GET.get("vista") == "fotografos":
            return self._render_photographer_folders(request, event)
        photographer = None
        fid = request.GET.get("fotografo", "")
        if fid.isdigit():
            photographer = event.photographer_links.filter(id=int(fid)).first()
            if photographer is None:
                raise Http404
        return self._render_gallery(request, event, photographer=photographer)

    # ----- Galería completa (o filtrada por un fotógrafo) -----
    def _render_gallery(
        self, request: HttpRequest, event: Event, photographer: Any = None
    ) -> HttpResponse:
        photos_qs = Photo.objects.filter(event=event, status=PhotoStatus.APPROVED)
        if photographer is not None:
            photos_qs = photos_qs.filter(photographer_link=photographer)
        # Cronológico: la primera foto tomada (hora de disparo) primero.
        photos_qs = photos_qs.prefetch_related("bibs").order_by("capture_time", "created_at")
        paginator = Paginator(photos_qs, GALLERY_PAGE_SIZE)
        page = paginator.get_page(request.GET.get("page", 1))

        ctx = {
            "event": event,
            "photos": page,
            "page_obj": page,
            "total_photos": paginator.count,
            "photographer_count": event.photographer_links.count(),
            "photographer": photographer,
        }
        # HTMX infinite-scroll: solo el grid + el sentinel de la próxima página.
        if getattr(request, "htmx", False):
            return render(request, "public/_photo_grid.html", ctx)
        return render(request, "public/event_gallery.html", ctx)

    # ----- Carpetas por fotógrafo -----
    def _render_photographer_folders(self, request: HttpRequest, event: Event) -> HttpResponse:
        from django.db.models import Count, Q

        folders = list(
            event.photographer_links.annotate(
                approved_count=Count("photos", filter=Q(photos__status=PhotoStatus.APPROVED))
            )
            .filter(approved_count__gt=0)
            .order_by("-approved_count", "photographer_name")
        )
        return render(
            request,
            "public/event_gallery.html",
            {
                "event": event,
                "folders": folders,
                "vista": "fotografos",
                "photographer_count": len(folders),
            },
        )

    # ----- Búsqueda por dorsal -----
    def _handle_bib_search(
        self, request: HttpRequest, event: Event, bib_query: str
    ) -> HttpResponse:
        bib_query = normalize_bib_query(bib_query)

        if not is_valid_bib_format(bib_query):
            return render(
                request,
                "public/event_gallery.html",
                {"event": event, "bib_query": bib_query, "error": "invalid_format"},
            )

        # Cache 5 min: guardamos IDs (no objetos, para no cachear signed URLs).
        # Se consulta ANTES del rate limit a propósito: repetir la misma búsqueda
        # (recargar, volver atrás, abrir el link que te pasaron) sale de la caché
        # y no le cuesta nada al servidor, así que no gasta cupo. El anti-scraping
        # no se debilita: bajarse un evento entero exige dorsales DISTINTOS, y
        # cada uno de esos sí pasa por el límite.
        cache_key = f"search:bib:{event.id}:{bib_query}"
        photo_ids = cache.get(cache_key)

        if photo_ids is None:
            if not check_general_search_rate_limit(request):
                return render(request, "public/rate_limited.html", {"event": event}, status=429)
            if not check_bib_specific_rate_limit(request, event.id, bib_query):
                return render(request, "public/rate_limited.html", {"event": event}, status=429)

            photo_ids = list(
                Photo.objects.filter(
                    event=event,
                    status=PhotoStatus.APPROVED,
                    # Ignora ceros a la izquierda: "99" encuentra "099" (y viceversa).
                    bibs__number__in=bib_query_variants(bib_query),
                    bibs__rejected=False,
                )
                .distinct()
                .order_by("capture_time", "created_at")
                .values_list("id", flat=True)[:MAX_SEARCH_RESULTS]
            )
            cache.set(cache_key, photo_ids, timeout=SEARCH_CACHE_TTL)

        # Incrementar contador del evento (no bloqueante para el usuario).
        Event.objects.filter(id=event.id).update(search_count=F("search_count") + 1)
        record_event_metric(event.id, Metric.SEARCH)

        if not photo_ids:
            return self._render_no_results(request, event, bib_query)

        photos = list(
            Photo.objects.filter(id__in=photo_ids)
            .prefetch_related("bibs")
            .order_by("capture_time", "created_at")
        )

        return render(
            request,
            "public/event_gallery.html",
            {
                "event": event,
                "search_photos": photos,
                "bib_query": bib_query,
                "is_search_result": True,
                "result_count": len(photos),
            },
        )

    # ----- Búsqueda por cara (click en el visor) -----
    def _handle_face_search(self, request: HttpRequest, event: Event, face_id: int) -> HttpResponse:
        """Fotos de la persona de esa cara, por similitud con el embedding YA
        guardado. No procesa ninguna imagen nueva ni sube nada: usa el vector
        que se extrajo cuando se subió la foto."""
        from apps.photos.models import FaceEmbedding
        from apps.search.views import (
            FACE_CLICK_MAX_RESULTS,
            FACE_CLICK_THRESHOLD,
            search_faces_by_similarity,
        )

        if not event.is_searchable():
            raise Http404

        face = (
            FaceEmbedding.objects.filter(
                id=face_id, photo__event=event, photo__status=PhotoStatus.APPROVED
            )
            .only("id", "embedding")
            .first()
        )
        if face is None:
            raise Http404

        if not check_general_search_rate_limit(request):
            return render(request, "public/rate_limited.html", {"event": event}, status=429)

        photos = search_faces_by_similarity(
            event,
            list(face.embedding),
            threshold=FACE_CLICK_THRESHOLD,
            limit=FACE_CLICK_MAX_RESULTS,
        )
        record_event_metric(event.id, Metric.SEARCH)

        return render(
            request,
            "public/event_gallery.html",
            {
                "event": event,
                "search_photos": photos,
                "is_search_result": True,
                "is_face_search": True,
                "face_id": face_id,
                "result_count": len(photos),
            },
        )

    def _render_no_results(
        self, request: HttpRequest, event: Event, bib_query: str
    ) -> HttpResponse:
        similar = get_similar_bibs_in_event(event, bib_query, limit=5)
        return render(
            request,
            "public/event_no_results.html",
            {"event": event, "bib_query": bib_query, "similar_bibs": similar},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_similar_bibs_in_event(event: Event, query: str, *, limit: int = 5) -> list[str]:
    """Sugiere dorsales que existen en el evento y son OCR-confundibles con el query."""
    if not query.isdigit():
        return []

    variants = set(generate_ocr_variants(query))
    if not variants:
        return []

    existing = set(
        Bib.objects.filter(
            photo__event=event,
            photo__status=PhotoStatus.APPROVED,
            rejected=False,
            number__in=variants,
        )
        .values_list("number", flat=True)
        .distinct()
    )
    similar = [v for v in sorted(existing) if v != query]
    return similar[:limit]


# ---------------------------------------------------------------------------
# EventCoverView — sirve la portada del evento desde R2
# ---------------------------------------------------------------------------
class EventCoverView(View):
    """Sirve la portada (webp) desde R2 con cache.

    La portada vive en el bucket PRIVADO; en vez de exponer una URL firmada
    (que expira y no se cachea), la servimos por acá con `Cache-Control` largo.
    La URL lleva `?v=<updated_at>` para bustear el cache cuando cambia.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest, slug: str) -> HttpResponseBase:
        event = get_object_or_404(Event, slug=slug)
        if not event.cover_key or event.status == EventStatus.DELETED:
            raise Http404

        from apps.photos.storage import R2NotConfiguredError, R2UploadError, default_storage

        buf = BytesIO()
        try:
            default_storage().download_fileobj(event.cover_key, buf)
        except (R2NotConfiguredError, R2UploadError) as exc:
            raise Http404 from exc
        buf.seek(0)

        resp = FileResponse(buf, content_type="image/webp")
        resp["Cache-Control"] = "public, max-age=604800"  # 7 días (URL versionada)
        return resp
