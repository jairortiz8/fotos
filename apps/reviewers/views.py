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

from io import BytesIO
from typing import Any

from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView
from django_ratelimit.core import is_ratelimited

from apps.events.models import Event, EventStatus
from apps.photos.models import Photo, PhotoStatus
from apps.photos.storage import R2NotConfiguredError, R2UploadError, default_storage

GALLERY_PAGE_SIZE = 60


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
    next_page = reverse_lazy("reviewer:login")


class ReviewerIndexView(ReviewerRequiredMixin, TemplateView):
    template_name = "reviewer/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["events"] = list(
            Event.objects.exclude(status=EventStatus.DELETED)
            .annotate(n_aprobadas=Count("photos", filter=Q(photos__status=PhotoStatus.APPROVED)))
            .filter(n_aprobadas__gt=0)
            .order_by("-date", "name")
        )
        return ctx


class ReviewerGalleryView(ReviewerRequiredMixin, View):
    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event.objects.exclude(status=EventStatus.DELETED), slug=slug)
        qs = Photo.objects.filter(event=event, status=PhotoStatus.APPROVED).order_by(
            "capture_time", "created_at"
        )
        page = Paginator(qs, GALLERY_PAGE_SIZE).get_page(request.GET.get("page"))
        ctx = {"event": event, "page_obj": page, "photos": page.object_list}
        template = (
            "reviewer/_grid.html" if getattr(request, "htmx", False) else "reviewer/gallery.html"
        )
        return render(request, template, ctx)


class ReviewerPhotoDownloadView(ReviewerRequiredMixin, View):
    """Descarga el ORIGINAL LIMPIO (sin logos): `original_key`, NO `download_key()`."""

    http_method_names = ["get"]

    def get(self, request: HttpRequest, photo_id: int) -> HttpResponseBase:
        photo = get_object_or_404(
            Photo.objects.select_related("event"), id=photo_id, status=PhotoStatus.APPROVED
        )
        if photo.event.status == EventStatus.DELETED or not photo.original_key:
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
