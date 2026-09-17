"""Vistas de descarga ZIP: crear pedido + polling de estado."""

from __future__ import annotations

from io import BytesIO

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
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.core.utils import (
    check_photo_download_rate_limit,
    check_zip_rate_limit,
    get_client_ip,
    hash_ip,
)
from apps.downloads.models import MAX_PHOTOS_PER_ZIP, ZipDownload, ZipStatus
from apps.events.metrics import Metric, record_event_metric
from apps.events.models import Event, EventVisibility
from apps.photos.models import Photo, PhotoStatus
from apps.photos.storage import R2NotConfiguredError, R2UploadError, default_storage


@method_decorator(csrf_exempt, name="dispatch")
class CreateZipDownloadView(View):
    """POST con `photo_ids` → crea un ZipDownload y dispara la task."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> HttpResponse:
        raw_ids = request.POST.getlist("photo_ids") or _ids_from_csv(request.POST.get("ids", ""))
        photo_ids = _clean_ids(raw_ids)

        if not photo_ids:
            return JsonResponse({"error": "empty_selection"}, status=400)
        if len(photo_ids) > MAX_PHOTOS_PER_ZIP:
            return JsonResponse({"error": "too_many", "max": MAX_PHOTOS_PER_ZIP}, status=400)

        if not check_zip_rate_limit(request):
            return JsonResponse({"error": "rate_limited"}, status=429)

        # Sólo fotos aprobadas Y de eventos que el público puede ver hoy.
        # SEGURIDAD: antes filtraba únicamente por `status=APPROVED`, así que
        # con el id de una foto de un evento privado o archivado —que la galería
        # y el lightbox devuelven 404— se podía igual armar el ZIP y bajarla.
        # Es el mismo criterio que ya aplica `PhotoDownloadView` más abajo.
        valid_ids = [
            foto.id
            for foto in Photo.objects.filter(
                id__in=photo_ids, status=PhotoStatus.APPROVED
            ).select_related("event")
            if foto.event.visibility != EventVisibility.PRIVATE and foto.event.is_searchable()
        ]
        if not valid_ids:
            return JsonResponse({"error": "no_valid_photos"}, status=400)

        download = ZipDownload.objects.create(
            requester_ip_hash=hash_ip(get_client_ip(request)),
            photo_ids=valid_ids,
            photo_count=len(valid_ids),
            status=ZipStatus.PENDING,
        )

        from apps.downloads.tasks import generate_zip

        generate_zip.delay(download.id)

        return JsonResponse(
            {
                "download_id": download.id,
                "status": download.status,
                "poll_url": f"/descargas/estado/{download.id}/",
            }
        )


class ZipStatusView(View):
    """Polling del estado de un ZIP. HTMX-friendly (devuelve un partial).

    SEGURIDAD: la consulta va atada a quien pidió el ZIP. Antes era
    `get_object_or_404(ZipDownload, id=...)` a secas y la respuesta incluye
    `download_url`, que es una URL FIRMADA de R2 válida una hora y sin más
    autenticación. Como el id es un autoincremental, cualquiera podía recorrer
    /descargas/estado/1/, /2/, /3/… y cosechar las URLs de los ZIP de otros
    visitantes — hasta 200 originales en alta por cada uno.

    El hash de IP usa salt diaria, así que un ZIP creado antes de medianoche no
    se puede consultar después. Es aceptable: el ZIP vive una hora, y el modo de
    falla es 404 (cerrado), no fuga.
    """

    def get(self, request: HttpRequest, download_id: int) -> HttpResponse:
        download = get_object_or_404(
            ZipDownload,
            id=download_id,
            requester_ip_hash=hash_ip(get_client_ip(request)),
        )

        if getattr(request, "htmx", False):
            return render(request, "public/_zip_status.html", {"download": download})

        return JsonResponse(
            {
                "status": download.status,
                "download_url": download.download_url,
                "photo_count": download.photo_count,
                "total_size_mb": download.total_size_mb,
                "error": download.error_message,
            }
        )


# ---------------------------------------------------------------------------
# Descarga de UNA foto (original, alta resolución, sin watermark)
# ---------------------------------------------------------------------------
class PhotoDownloadView(View):
    """Sirve el ORIGINAL (alta resolución, sin watermark) como DESCARGA.

    Lo servimos same-origin con `Content-Disposition: attachment` (en vez de
    redirigir a una URL firmada de R2) para que el navegador lo baje como
    ARCHIVO. En iOS/Safari un redirect a una imagen la abría como página ("se
    descarga como webpage"); same-origin + attachment la baja al carrete/Archivos.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest, photo_id: int) -> HttpResponseBase:
        photo = get_object_or_404(
            Photo.objects.select_related("event"),
            id=photo_id,
            status=PhotoStatus.APPROVED,
        )
        event = photo.event
        if event.visibility == EventVisibility.PRIVATE or not event.is_searchable():
            raise Http404
        # En eventos brandeados (ej. Surf City) se baja el original CON logos;
        # en el resto, el original limpio. `download_key()` elige y cae al limpio
        # si la versión con logos todavía no se generó.
        download_key = photo.download_key()
        if not download_key:
            raise Http404
        if not check_photo_download_rate_limit(request):
            return JsonResponse({"error": "rate_limited"}, status=429)

        filename = photo.original_filename or f"foto_{photo.id}.jpg"
        if not filename.lower().endswith((".jpg", ".jpeg")):
            filename = f"{filename}.jpg"

        buf = BytesIO()
        try:
            default_storage().download_fileobj(download_key, buf)
        except (R2NotConfiguredError, R2UploadError) as exc:
            raise Http404 from exc
        buf.seek(0)

        # Contamos la descarga SOLO cuando el original bajó OK de R2 (atómico, sin
        # carrera). Alimenta el contador por foto + el total por evento del dashboard.
        photo.increment_download_count()
        Event.objects.filter(pk=event.id).update(download_count=F("download_count") + 1)
        record_event_metric(event.id, Metric.DOWNLOAD)

        return FileResponse(buf, as_attachment=True, filename=filename, content_type="image/jpeg")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ids_from_csv(csv: str) -> list[str]:
    return [s for s in csv.split(",") if s.strip()]


def _clean_ids(raw: list[str]) -> list[int]:
    out: list[int] = []
    for r in raw:
        try:
            out.append(int(r))
        except (TypeError, ValueError):
            continue
    return out
