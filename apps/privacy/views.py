"""Vistas de privacidad: política + borrado de datos por selfie.

`DeleteMyDataView` procesa el selfie EN MEMORIA (síncrono). El embedding del
solicitante NUNCA se persiste ni pasa por Celery. Sólo los `photo_ids` a borrar
(que no son biométricos) se pasan a la task de borrado.
"""

from __future__ import annotations

import logging

from django.db.models import Min
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView
from pgvector.django import CosineDistance

from apps.core.utils import check_deletion_rate_limit, get_client_ip, hash_ip
from apps.photos.models import Photo, PhotoStatus
from apps.privacy.models import DataDeletionRequest, DeletionStatus

logger = logging.getLogger(__name__)

# Umbral más estricto para borrado que para búsqueda (evitar borrar fotos
# de otra persona por un falso positivo). ADR 0006.
DELETION_THRESHOLD = 0.62
MAX_DELETION_MATCHES = 1000
MAX_SELFIE_BYTES = 10 * 1024 * 1024


class PrivacyPolicyView(TemplateView):
    template_name = "public/privacy_policy.html"


@method_decorator(csrf_exempt, name="dispatch")
class DeleteMyDataView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return render(request, "public/privacy_delete.html")

    def post(self, request: HttpRequest) -> HttpResponse:
        if not check_deletion_rate_limit(request):
            return render(request, "public/rate_limited.html", status=429)

        if request.POST.get("confirmed") != "yes":
            return JsonResponse({"error": "must_confirm"}, status=400)

        selfie = request.FILES.get("selfie")
        if not selfie:
            return JsonResponse({"error": "no_selfie"}, status=400)
        if selfie.size and selfie.size > MAX_SELFIE_BYTES:
            return JsonResponse({"error": "file_too_large"}, status=400)

        from apps.ml.face_recognition import (
            InvalidImageError,
            MultipleFacesDetectedError,
            NoFaceDetectedError,
            embedding_from_bytes,
        )

        # --- Extracción EN MEMORIA — el embedding nunca se persiste ---
        try:
            query_embedding = embedding_from_bytes(selfie.read())
        except NoFaceDetectedError:
            return render(request, "public/selfie_no_face_delete.html")
        except MultipleFacesDetectedError:
            return render(request, "public/selfie_multiple_faces_delete.html")
        except InvalidImageError:
            return JsonResponse({"error": "invalid_format"}, status=400)

        # Buscar en TODOS los eventos (no filtramos por evento acá).
        photo_ids = find_matching_photo_ids(query_embedding.tolist())

        deletion = DataDeletionRequest.objects.create(
            requester_ip_hash=hash_ip(get_client_ip(request)),
            status=DeletionStatus.PROCESSING,
            matched_photo_count=len(photo_ids),
        )

        # El embedding sale de scope acá. A la task sólo le pasamos IDs.
        from apps.privacy.tasks import delete_photos_for_request

        delete_photos_for_request.delay(deletion.id, photo_ids)

        logger.info(
            "data_deletion request=%s matched=%d ip_hash=%s",
            deletion.id,
            len(photo_ids),
            deletion.requester_ip_hash[:12],
        )

        return render(
            request,
            "public/privacy_delete_pending.html",
            {"request_id": deletion.id, "matched_count": len(photo_ids)},
        )


# ---------------------------------------------------------------------------
# Matching global (todos los eventos)
# ---------------------------------------------------------------------------
def find_matching_photo_ids(
    query_embedding: list[float],
    *,
    threshold: float = DELETION_THRESHOLD,
    limit: int = MAX_DELETION_MATCHES,
) -> list[int]:
    """IDs de fotos (cualquier evento) cuya cara matchea el selfie."""
    max_distance = 1 - threshold
    qs = (
        Photo.objects.exclude(status=PhotoStatus.DELETED)
        .annotate(min_distance=Min(CosineDistance("face_embeddings__embedding", query_embedding)))
        .filter(min_distance__isnull=False, min_distance__lte=max_distance)
        .order_by("min_distance")
        .values_list("id", flat=True)[:limit]
    )
    return list(qs)  # type: ignore[arg-type]
