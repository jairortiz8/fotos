"""Rol "invitado": acceso de solo-lectura para VER galerías y DESCARGAR los
ORIGINALES LIMPIOS (sin logos). NO da acceso al panel admin.

Un invitado es `User.is_reviewer=True` con `is_staff=False`. Inicia sesión en
`/invitados/entrar/`, ve las galerías de eventos con fotos aprobadas y baja el
original limpio (`original_key`) de cada foto — NO la versión con logos que baja
el público en eventos brandeados. Los usuarios staff también pueden entrar.

Seguridad: cada vista exige `is_reviewer` o `is_staff`; un anónimo o un usuario
común se redirige al login del invitado (no a un 403 que revele la galería).
"""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any

from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseRedirect,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView
from django_ratelimit.core import is_ratelimited

from apps.events.models import Event, EventStatus
from apps.photos.imaging import REVIEWER_CLEAN_SIZES, generate_clean_render
from apps.photos.models import Photo, PhotoStatus
from apps.photos.storage import R2NotConfiguredError, R2UploadError, default_storage
from apps.reviewers.services import attach_clean_thumb_urls

GALLERY_PAGE_SIZE = 60


def _photo_ids_json(photos: Any) -> str:
    """IDs de las fotos (en orden) para el lightbox Alpine (prev/siguiente)."""
    return json.dumps([p.id for p in photos])


def is_reviewer(user: Any) -> bool:
    """True si el usuario puede usar las galerías privadas (invitado o staff)."""
    return bool(getattr(user, "is_authenticated", False)) and bool(
        getattr(user, "is_staff", False) or getattr(user, "is_reviewer", False)
    )


class ReviewerRequiredMixin(AccessMixin):
    """Exige invitado o staff; si no, redirige al login del invitado."""

    request: HttpRequest

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not is_reviewer(request.user):
            return redirect_to_login(request.get_full_path(), str(reverse_lazy("reviewer:login")))
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]


class ReviewerLoginView(LoginView):
    template_name = "reviewer/login.html"
    redirect_authenticated_user = True

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if is_ratelimited(
            request,
            group="reviewer-login",
            key="ip",
            rate="8/15m",
            method="POST",
            increment=True,
        ):
            ctx = self.get_context_data(form=self.get_form_class()(request=request))
            ctx["rate_limit_error"] = _("Demasiados intentos. Esperá unos minutos.")
            return self.render_to_response(ctx)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form: AuthenticationForm) -> HttpResponse:
        if not is_reviewer(form.get_user()):
            form.add_error(None, _("Esta cuenta no tiene acceso."))
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return self.get_redirect_url() or str(reverse_lazy("reviewer:index"))


class ReviewerLogoutView(LogoutView):
    next_page = reverse_lazy("reviewer:login")  # type: ignore[assignment]


class ReviewerIndexView(ReviewerRequiredMixin, TemplateView):
    template_name = "reviewer/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        # Solo eventos marcados como visibles para invitados (y con fotos).
        ctx["events"] = list(
            Event.objects.filter(reviewer_visible=True)
            .exclude(status=EventStatus.DELETED)
            .annotate(n_aprobadas=Count("photos", filter=Q(photos__status=PhotoStatus.APPROVED)))
            .filter(n_aprobadas__gt=0)
            .order_by("-date", "name")
        )
        return ctx


class ReviewerGalleryView(ReviewerRequiredMixin, View):
    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        # 404 si el evento no está expuesto a invitados (no solo lo ocultamos
        # del listado: bloqueamos el acceso directo por URL).
        event = get_object_or_404(
            Event.objects.exclude(status=EventStatus.DELETED), slug=slug, reviewer_visible=True
        )

        # Búsqueda por dorsal (OCR) dentro del evento.
        bib_query = request.GET.get("bib", "").strip()
        if bib_query:
            return self._bib_search(request, event, bib_query)

        # ?cara=<id> → fotos de esa persona (click en el visor del lightbox).
        face_query = request.GET.get("cara", "").strip()
        if face_query.isdigit():
            return self._face_search(request, event, int(face_query))

        # Vista "carpetas por fotógrafo".
        if request.GET.get("vista") == "fotografos":
            folders = list(
                event.photographer_links.annotate(
                    approved_count=Count("photos", filter=Q(photos__status=PhotoStatus.APPROVED))
                )
                .filter(approved_count__gt=0)
                .order_by("-approved_count", "photographer_name")
            )
            return render(
                request,
                "reviewer/gallery.html",
                {"event": event, "folders": folders, "vista": "fotografos"},
            )

        # Foto grid (todas, o filtradas por un fotógrafo).
        photographer = None
        fid = request.GET.get("fotografo", "")
        if fid.isdigit():
            photographer = event.photographer_links.filter(id=int(fid)).first()
            if photographer is None:
                raise Http404
        qs = Photo.objects.filter(event=event, status=PhotoStatus.APPROVED)
        if photographer is not None:
            qs = qs.filter(photographer_link=photographer)
        qs = qs.prefetch_related("bibs").order_by("capture_time", "created_at")
        page = Paginator(qs, GALLERY_PAGE_SIZE).get_page(request.GET.get("page"))
        attach_clean_thumb_urls(page.object_list, event)
        ctx = {
            "event": event,
            "page_obj": page,
            "photos": page.object_list,
            "photographer": photographer,
            "photo_ids_json": _photo_ids_json(page.object_list),
        }
        # Scroll infinito: en un request de HTMX devolvemos solo el chunk de la
        # grilla (con centinela + IDs para el lightbox), no la página entera.
        if getattr(request, "htmx", False):
            return render(request, "reviewer/_grid.html", {**ctx, "append_ids": True})
        return render(request, "reviewer/gallery.html", ctx)

    def _face_search(self, request: HttpRequest, event: Event, face_id: int) -> HttpResponse:
        """Fotos de la persona de esa cara. Usa el embedding ya guardado — no
        procesa ninguna imagen nueva."""
        from apps.photos.models import FaceEmbedding
        from apps.search.views import FACE_CLICK_THRESHOLD, search_faces_by_similarity

        face = (
            FaceEmbedding.objects.filter(
                id=face_id, photo__event=event, photo__status=PhotoStatus.APPROVED
            )
            .only("id", "embedding")
            .first()
        )
        if face is None:
            raise Http404

        photos = search_faces_by_similarity(
            event, list(face.embedding), threshold=FACE_CLICK_THRESHOLD
        )
        attach_clean_thumb_urls(photos, event)
        return render(
            request,
            "reviewer/gallery.html",
            {
                "event": event,
                "photos": photos,
                "is_search": True,
                "face_search": True,
                "match_count": len(photos),
                "photo_ids_json": _photo_ids_json(photos),
            },
        )

    def _bib_search(self, request: HttpRequest, event: Event, raw: str) -> HttpResponse:
        from apps.core.utils import bib_query_variants, is_valid_bib_format, normalize_bib_query

        bib = normalize_bib_query(raw)
        photos: list[Photo] = []
        invalid = not is_valid_bib_format(bib)
        if not invalid:
            photos = list(
                Photo.objects.filter(
                    event=event,
                    status=PhotoStatus.APPROVED,
                    bibs__number__in=bib_query_variants(bib),
                    bibs__rejected=False,
                )
                .distinct()
                .prefetch_related("bibs")
                .order_by("capture_time", "created_at")[:200]
            )
        attach_clean_thumb_urls(photos, event)
        return render(
            request,
            "reviewer/gallery.html",
            {
                "event": event,
                "photos": photos,
                "is_search": True,
                "bib_query": bib,
                "invalid_bib": invalid,
                "photo_ids_json": _photo_ids_json(photos),
            },
        )


class ReviewerSelfieSearchView(ReviewerRequiredMixin, View):
    """Búsqueda por selfie para invitados. Procesa el selfie EN MEMORIA (nunca lo
    persiste — igual que la búsqueda pública, ADR 0006) y muestra los matches con
    descarga del original limpio."""

    MAX_SELFIE_BYTES = 10 * 1024 * 1024

    def _event(self, slug: str) -> Event:
        return get_object_or_404(
            Event.objects.exclude(status=EventStatus.DELETED), slug=slug, reviewer_visible=True
        )

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = self._event(slug)
        ctx = {"event": event, "disabled": not settings.FACE_SEARCH_ENABLED}
        return render(request, "reviewer/selfie.html", ctx)

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = self._event(slug)
        if not settings.FACE_SEARCH_ENABLED:
            return render(request, "reviewer/selfie.html", {"event": event, "disabled": True})

        selfie = request.FILES.get("selfie")
        if not selfie:
            return render(request, "reviewer/selfie.html", {"event": event, "error": "no_selfie"})
        if selfie.size and selfie.size > self.MAX_SELFIE_BYTES:
            return render(request, "reviewer/selfie.html", {"event": event, "error": "too_large"})

        # Procesamiento EN MEMORIA — el embedding del selfie se descarta al terminar.
        from apps.ml.face_recognition import (
            InvalidImageError,
            MultipleFacesDetectedError,
            NoFaceDetectedError,
            embedding_from_bytes,
        )
        from apps.search.views import search_faces_by_similarity

        try:
            query_embedding = embedding_from_bytes(selfie.read())
        except NoFaceDetectedError:
            return render(request, "reviewer/selfie.html", {"event": event, "error": "no_face"})
        except MultipleFacesDetectedError:
            return render(request, "reviewer/selfie.html", {"event": event, "error": "multiple"})
        except InvalidImageError:
            return render(request, "reviewer/selfie.html", {"event": event, "error": "invalid"})

        matches = search_faces_by_similarity(event, query_embedding.tolist())
        attach_clean_thumb_urls(matches, event)
        return render(
            request,
            "reviewer/gallery.html",
            {
                "event": event,
                "photos": matches,
                "is_search": True,
                "selfie_search": True,
                "match_count": len(matches),
                "photo_ids_json": _photo_ids_json(matches),
            },
        )


class ReviewerCleanImageView(ReviewerRequiredMixin, View):
    """Sirve una versión LIMPIA (sin logos) de la foto, a `thumb`/`preview`.

    On-demand + caché: la 1ª vez baja el original de R2, genera el WebP limpio y
    lo guarda en R2 bajo `reviewer_clean/<slug>/<id>_<size>.webp`; después solo
    redirige a la URL firmada de esa versión cacheada. Así el invitado ve TODO
    sin logos sin tener que reprocesar el evento entero de antemano.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest, photo_id: int, size: str) -> HttpResponseBase:
        if size not in REVIEWER_CLEAN_SIZES:
            raise Http404
        photo = get_object_or_404(
            Photo.objects.select_related("event"), id=photo_id, status=PhotoStatus.APPROVED
        )
        if (
            photo.event.status == EventStatus.DELETED
            or not photo.event.reviewer_visible
            or not photo.original_key
        ):
            raise Http404

        long_edge, quality = REVIEWER_CLEAN_SIZES[size]
        clean_key = f"reviewer_clean/{photo.event.slug}/{photo.id}_{size}.webp"
        storage = default_storage()
        try:
            if not storage.exists(clean_key):
                buf = BytesIO()
                storage.download_fileobj(photo.original_key, buf)
                data = generate_clean_render(buf.getvalue(), long_edge, quality)
                storage.upload(
                    BytesIO(data),
                    clean_key,
                    content_type="image/webp",
                    cache_control="private, max-age=604800",
                )
            url = storage.get_signed_url(clean_key, expires_in=3600)
        except (R2NotConfiguredError, R2UploadError) as exc:
            raise Http404 from exc
        return HttpResponseRedirect(url)


class ReviewerPhotoDownloadView(ReviewerRequiredMixin, View):
    """Descarga el ORIGINAL LIMPIO (sin logos): `original_key`, NO `download_key()`."""

    http_method_names = ["get"]

    def get(self, request: HttpRequest, photo_id: int) -> HttpResponseBase:
        photo = get_object_or_404(
            Photo.objects.select_related("event"), id=photo_id, status=PhotoStatus.APPROVED
        )
        # Solo se baja de eventos expuestos a invitados (evita bajar originales de
        # otros eventos adivinando el id de la foto).
        if (
            photo.event.status == EventStatus.DELETED
            or not photo.event.reviewer_visible
            or not photo.original_key
        ):
            raise Http404
        filename = photo.original_filename or f"foto_{photo.id}.jpg"
        if not filename.lower().endswith((".jpg", ".jpeg")):
            filename = f"{filename}.jpg"
        buf = BytesIO()
        try:
            default_storage().download_fileobj(photo.original_key, buf)
        except (R2NotConfiguredError, R2UploadError) as exc:
            raise Http404 from exc
        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename=filename, content_type="image/jpeg")


class ReviewerPhotoFacesView(ReviewerRequiredMixin, View):
    """JSON con las caras (avatar) de una foto, para el visor del lightbox.

    El lightbox del invitado es client-side (Alpine navega por un array de IDs),
    así que no puede renderizar el visor en el server como la galería pública:
    lo pide por acá cada vez que cambia de foto.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest, photo_id: int) -> HttpResponse:
        from django.http import JsonResponse

        from apps.photos.faces import avatar_faces_for_photo

        photo = get_object_or_404(
            Photo.objects.select_related("event"),
            id=photo_id,
            status=PhotoStatus.APPROVED,
            event__reviewer_visible=True,
        )
        faces = [
            {
                "id": face.id,
                "url": reverse("reviewers:face_avatar", kwargs={"face_id": face.id}),
            }
            for face in avatar_faces_for_photo(photo)
        ]
        return JsonResponse({"faces": faces})


class ReviewerFaceAvatarView(ReviewerRequiredMixin, View):
    """Sirve el recorte de una cara para el visor del invitado.

    Existe aparte de la vista pública porque un evento puede ser
    `reviewer_visible` sin ser público: ahí la URL pública daría 404.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest, face_id: int) -> HttpResponseBase:
        from apps.photos.models import FaceEmbedding

        face = get_object_or_404(
            FaceEmbedding.objects.select_related("photo__event").only(
                "id", "avatar_key", "photo__status", "photo__event__reviewer_visible"
            ),
            id=face_id,
            photo__status=PhotoStatus.APPROVED,
            photo__event__reviewer_visible=True,
        )
        if not face.avatar_key:
            raise Http404

        buf = BytesIO()
        try:
            default_storage().download_fileobj(face.avatar_key, buf)
        except (R2NotConfiguredError, R2UploadError) as exc:
            raise Http404 from exc
        buf.seek(0)
        resp = FileResponse(buf, content_type="image/webp")
        resp["Cache-Control"] = "private, max-age=2592000"  # key inmutable
        return resp
