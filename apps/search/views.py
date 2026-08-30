"""Búsqueda por selfie (reconocimiento facial).

PRIVACIDAD (CLAUDE.md §3): el selfie del usuario se procesa EN MEMORIA durante
el request y se descarta. El embedding NUNCA se persiste ni pasa por Celery/Redis.
Esta vista es 100% síncrona por diseño (ADR 0006).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db.models import F, Min
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from pgvector.django import CosineDistance

from apps.core.utils import check_selfie_rate_limit, get_client_ip, hash_ip
from apps.events.metrics import Metric, record_event_metric
from apps.events.models import Event, EventVisibility
from apps.photos.models import Photo, PhotoStatus

logger = logging.getLogger(__name__)

# Umbral de similitud coseno (ADR 0006). Ajustable con `tune_threshold`.
SIMILARITY_THRESHOLD = 0.55
# Click en una cara del visor.
# MEDIDO contra datos reales de Surf City (2026-08), usando el dorsal como
# verdad de referencia sobre en qué fotos está cada corredor:
#     umbral   0.62    0.55    0.45    0.35
#     recall    42%     51%     55%     61%
# Con 0.62 se perdía ~1 de cada 3 apariciones REALES: la misma persona de
# lejos, de perfil o con otra luz queda apenas por debajo del corte. Bajado a
# 0.48, que recupera la mayor parte sin irse al extremo permisivo. Es la
# función "mostrame todas mis fotos": una foto de más molesta mucho menos que
# una propia que falta.
FACE_CLICK_THRESHOLD = 0.48
MAX_SELFIE_RESULTS = 50
# El click en una cara NO usa el tope de 50: un corredor bien fotografiado
# aparece en 100+ fotos y cortarle a 50 contradice el "todas tus fotos".
# La consulta es un índice HNSW, así que subir el tope no la encarece.
FACE_CLICK_MAX_RESULTS = 400
MAX_SELFIE_BYTES = 10 * 1024 * 1024  # 10 MB

# Cortes de confianza para agrupar resultados en la UI.
HIGH_CONFIDENCE = 0.80
MED_CONFIDENCE = 0.60


def _face_unavailable(request: HttpRequest, event: Event | None, *, mode: str) -> HttpResponse:
    """Respuesta amable cuando la búsqueda facial está apagada (FACE_SEARCH_ENABLED).

    `mode`: "search" (buscar por selfie) o "delete" (borrar mis datos).
    No carga el modelo — es seguro de servir en el dyno de 1GB.
    """
    return render(
        request,
        "public/face_unavailable.html",
        {"event": event, "mode": mode},
        status=503,
    )


@method_decorator(csrf_exempt, name="dispatch")
class SelfieSearchView(View):
    """GET: formulario de selfie. POST: procesa y devuelve coincidencias."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)
        if not self._can_search(event):
            raise Http404
        if not settings.FACE_SEARCH_ENABLED:
            return _face_unavailable(request, event, mode="search")
        return render(
            request,
            "public/selfie_search.html",
            {
                "event": event,
                "approved_count": event.photos.filter(status=PhotoStatus.APPROVED).count(),
            },
        )

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)
        if not self._can_search(event):
            raise Http404

        # Cortamos ANTES de cargar buffalo_l: en prod (dyno 1GB) cargar el
        # modelo OOM-killea el worker. El flag lo mantiene apagado hasta resolver
        # la RAM. Local/dev queda en True.
        if not settings.FACE_SEARCH_ENABLED:
            return _face_unavailable(request, event, mode="search")

        if not check_selfie_rate_limit(request):
            return render(request, "public/rate_limited.html", {"event": event}, status=429)

        selfie = request.FILES.get("selfie")
        if not selfie:
            return JsonResponse({"error": "no_selfie"}, status=400)
        if selfie.size and selfie.size > MAX_SELFIE_BYTES:
            return JsonResponse({"error": "file_too_large", "max_mb": 10}, status=400)

        # --- Procesamiento EN MEMORIA — el embedding nunca se persiste ---
        from apps.ml.face_recognition import (
            InvalidImageError,
            MultipleFacesDetectedError,
            NoFaceDetectedError,
            embedding_from_bytes,
        )

        try:
            query_embedding = embedding_from_bytes(selfie.read())
        except NoFaceDetectedError:
            return render(request, "public/selfie_no_face.html", {"event": event})
        except MultipleFacesDetectedError:
            return render(request, "public/selfie_multiple_faces.html", {"event": event})
        except InvalidImageError:
            return JsonResponse({"error": "invalid_format"}, status=400)

        matches = search_faces_by_similarity(event, query_embedding.tolist())

        # Actualizar retención de los matches (last_matched_at).
        if matches:
            from apps.photos.models import FaceEmbedding

            FaceEmbedding.objects.filter(photo_id__in=[m.id for m in matches]).update(
                last_matched_at=timezone.now(),
                match_count=F("match_count") + 1,
            )
            event.__class__.objects.filter(id=event.id).update(search_count=F("search_count") + 1)
            record_event_metric(event.id, Metric.SEARCH)

        # Log anonimizado (sin el embedding ni la IP cruda).
        logger.info(
            "selfie_search event=%s matches=%d ip_hash=%s",
            event.slug,
            len(matches),
            hash_ip(get_client_ip(request))[:12],
        )

        # IMPORTANTE: query_embedding sale de scope al terminar el request.
        if not matches:
            return render(request, "public/selfie_no_results.html", {"event": event})

        def _sim(photo: Photo) -> int:
            return int(getattr(photo, "similarity", 0))

        high = [m for m in matches if _sim(m) >= HIGH_CONFIDENCE * 100]
        med = [m for m in matches if MED_CONFIDENCE * 100 <= _sim(m) < HIGH_CONFIDENCE * 100]
        low = [m for m in matches if _sim(m) < MED_CONFIDENCE * 100]

        return render(
            request,
            "public/selfie_results.html",
            {
                "event": event,
                "matches": matches,
                "high_matches": high,
                "med_matches": med,
                "low_matches": low,
                "match_count": len(matches),
            },
        )

    @staticmethod
    def _can_search(event: Event) -> bool:
        if event.visibility == EventVisibility.PRIVATE:
            return False
        return event.is_searchable()


# ---------------------------------------------------------------------------
# Matching con pgvector
# ---------------------------------------------------------------------------
def search_faces_by_similarity(
    event: Event,
    query_embedding: list[float],
    *,
    threshold: float = SIMILARITY_THRESHOLD,
    limit: int = MAX_SELFIE_RESULTS,
) -> list[Photo]:
    """Devuelve fotos aprobadas ordenadas por similitud coseno (desc).

    cosine_distance = 1 - cosine_similarity, así que filtramos por
    `distance <= 1 - threshold` y ordenamos ascendente por distancia.
    """
    max_distance = 1 - threshold
    results: list[Photo] = list(
        Photo.objects.filter(event=event, status=PhotoStatus.APPROVED)
        .annotate(min_distance=Min(CosineDistance("face_embeddings__embedding", query_embedding)))
        .filter(min_distance__isnull=False, min_distance__lte=max_distance)
        .order_by("min_distance")
        .prefetch_related("bibs")[:limit]
    )
    for photo in results:
        # `min_distance` y `similarity` son atributos anotados/dinámicos.
        photo.similarity = round((1 - photo.min_distance) * 100)  # type: ignore[attr-defined]
    return results
