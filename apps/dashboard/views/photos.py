"""Cola de aprobación, drawer de detalle y acciones de moderación."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import ListView

from apps.core.models import AuditLog
from apps.dashboard import services
from apps.dashboard.forms import AddBibForm, RejectPhotoForm
from apps.dashboard.mixins import DashboardContextMixin, StaffRequiredMixin
from apps.events.models import Event
from apps.photographers.models import PhotographerLink
from apps.photos.models import Bib, BibSource, Photo, PhotoStatus

MAX_BULK = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def confidence_label(photo: Photo) -> tuple[str, str]:
    """(tono, etiqueta) según la mejor confianza de OCR de los dorsales."""
    bibs = [b for b in photo.bibs.all() if not b.rejected]
    if not bibs:
        return ("amber", "Sin detectar")
    best = max(b.confidence for b in bibs)
    if best >= 0.8:
        return ("green", "Alta confianza")
    if best >= 0.5:
        return ("amber", "Media")
    return ("red", "Baja")


def _photographer_stats(link: PhotographerLink | None) -> dict[str, Any] | None:
    if link is None:
        return None
    uploaded = link.photos_uploaded or link.photos.count()
    approved = link.photos.filter(status=PhotoStatus.APPROVED).count()
    pct = round(approved / uploaded * 100) if uploaded else 0
    return {"link": link, "uploaded": uploaded, "approved_pct": pct}


def _next_pending(photo: Photo) -> Photo | None:
    return (
        Photo.objects.filter(
            event=photo.event,
            status=PhotoStatus.PENDING_REVIEW,
            created_at__gt=photo.created_at,
        )
        .order_by("created_at")
        .first()
    )


def _next_or_done(request: HttpRequest, photo: Photo) -> HttpResponse:
    """Tras aprobar/rechazar vía HTMX: cargar el siguiente pendiente o volver."""
    if not request.htmx:  # type: ignore[attr-defined]
        return JsonResponse({"success": True, "photo_id": photo.id})
    nxt = _next_pending(photo)
    if nxt is None:
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = reverse("dashboard:pending_photos")
        return resp
    return render(request, "dashboard/partials/photo_drawer.html", _drawer_context(nxt))


def _drawer_context(photo: Photo) -> dict[str, Any]:
    tone, label = confidence_label(photo)
    faces = photo.face_embeddings.all()
    return {
        "photo": photo,
        "bibs": [b for b in photo.bibs.all() if not b.rejected],
        "confidence_tone": tone,
        "confidence_label": label,
        "photographer": _photographer_stats(photo.photographer_link),
        "face_count": len(faces),
        "has_minor": photo.has_minors_detected or photo.needs_minor_review,
        "add_bib_form": AddBibForm(),
        "reject_form": RejectPhotoForm(),
        "next_pending_id": (np := _next_pending(photo)) and np.id,
    }


# ---------------------------------------------------------------------------
# Cola de aprobación
# ---------------------------------------------------------------------------
class PendingPhotosView(DashboardContextMixin, ListView):
    template_name = "dashboard/pending_photos.html"
    context_object_name = "photos"
    active_nav = "approval"
    paginate_by = 20

    def get_queryset(self) -> Any:
        qs = Photo.objects.filter(status=PhotoStatus.PENDING_REVIEW).prefetch_related(
            "bibs", "photographer_link"
        )
        event = self.request.GET.get("event")
        if event:
            qs = qs.filter(event__slug=event)
        photographer = self.request.GET.get("photographer")
        if photographer and photographer.isdigit():
            qs = qs.filter(photographer_link_id=int(photographer))

        rng = self.request.GET.get("range", "7d")
        if rng in ("7d", "30d"):
            days = 7 if rng == "7d" else 30
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))
        # Cronológico por hora de disparo (las que no tienen capture_time van al
        # final); el admin revisa en orden de carrera.
        return qs.order_by("capture_time", "created_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        photos = ctx["photos"]
        for p in photos:
            p.conf_tone, p.conf_label = confidence_label(p)
        base = Photo.objects.filter(status=PhotoStatus.PENDING_REVIEW)
        ctx["total_pending"] = base.count()
        ctx["distinct_photographers"] = base.values("photographer_link").distinct().count()
        ctx["distinct_events"] = base.values("event").distinct().count()
        ctx["events"] = list(
            Event.objects.filter(photos__status=PhotoStatus.PENDING_REVIEW)
            .distinct()
            .order_by("name")
        )
        ctx["photographers"] = list(
            PhotographerLink.objects.filter(photos__status=PhotoStatus.PENDING_REVIEW)
            .distinct()
            .order_by("photographer_name")
        )
        ctx["filter_event"] = self.request.GET.get("event", "")
        ctx["filter_photographer"] = self.request.GET.get("photographer", "")
        ctx["filter_range"] = self.request.GET.get("range", "7d")
        return ctx


# ---------------------------------------------------------------------------
# Drawer / detalle
# ---------------------------------------------------------------------------
class PhotoDetailView(StaffRequiredMixin, View):
    """Página completa (o partial HTMX) del detalle de una foto pendiente."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        photo = get_object_or_404(Photo.objects.prefetch_related("bibs", "face_embeddings"), pk=pk)
        ctx = _drawer_context(photo)
        template = (
            "dashboard/partials/photo_drawer.html"
            if request.htmx  # type: ignore[attr-defined]
            else "dashboard/photo_detail.html"
        )
        if not request.htmx:  # type: ignore[attr-defined]
            ctx["active_nav"] = "approval"
            ctx["nav_pending_count"] = Photo.objects.filter(
                status=PhotoStatus.PENDING_REVIEW
            ).count()
        return render(request, template, ctx)


# ---------------------------------------------------------------------------
# Acciones individuales
# ---------------------------------------------------------------------------
class ApprovePhotoView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        photo = get_object_or_404(Photo, pk=pk)
        if photo.status != PhotoStatus.PENDING_REVIEW:
            return JsonResponse({"error": "invalid_status"}, status=400)
        photo.mark_approved(by_admin=True)
        AuditLog.log("photo.approved", target=photo, user=self.staff_user)
        services.recalculate_event_counters(photo.event)
        return _next_or_done(request, photo)


class RejectPhotoView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        photo = get_object_or_404(Photo, pk=pk)
        if photo.status != PhotoStatus.PENDING_REVIEW:
            return JsonResponse({"error": "invalid_status"}, status=400)
        reason = request.POST.get("reason", "").strip()[:255]
        photo.status = PhotoStatus.REJECTED
        photo.rejected_reason = reason
        photo.save(update_fields=["status", "rejected_reason", "updated_at"])
        AuditLog.log(
            "photo.rejected", target=photo, user=self.staff_user, metadata={"reason": reason}
        )
        services.recalculate_event_counters(photo.event)
        return _next_or_done(request, photo)


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------
class _BulkBase(StaffRequiredMixin, View):
    target_status = PhotoStatus.APPROVED
    action_name = "photo.bulk_approved"

    def post(self, request: HttpRequest) -> HttpResponse:
        ids = request.POST.getlist("photo_ids[]") or request.POST.getlist("photo_ids")
        if not ids:
            return JsonResponse({"error": "no_ids"}, status=400)
        if len(ids) > MAX_BULK:
            return JsonResponse({"error": "too_many", "max": MAX_BULK}, status=400)

        with transaction.atomic():
            # select_for_update no admite DISTINCT, así que lockeamos los IDs y
            # consultamos los event_ids con un queryset aparte (sin FOR UPDATE).
            locked_ids = list(
                Photo.objects.select_for_update()
                .filter(id__in=ids, status=PhotoStatus.PENDING_REVIEW)
                .values_list("id", flat=True)
            )
            target = Photo.objects.filter(id__in=locked_ids)
            event_ids = list(target.values_list("event_id", flat=True).distinct())
            extra: dict[str, Any] = {}
            if self.target_status == PhotoStatus.APPROVED:
                extra = {"approved_at": timezone.now(), "approved_by_admin": True}
            count = target.update(status=self.target_status, **extra)

        AuditLog.log(
            self.action_name,
            user=self.staff_user,
            metadata={"count": count, "ids": [int(i) for i in ids[:20]]},
        )
        for event in Event.objects.filter(id__in=event_ids):
            services.recalculate_event_counters(event)

        return JsonResponse({"updated": count})


class BulkApproveView(_BulkBase):
    target_status = PhotoStatus.APPROVED
    action_name = "photo.bulk_approved"


class BulkRejectView(_BulkBase):
    target_status = PhotoStatus.REJECTED
    action_name = "photo.bulk_rejected"


# ---------------------------------------------------------------------------
# Aprobar TODAS las del filtro actual (p. ej. todas las de un fotógrafo)
# ---------------------------------------------------------------------------
class ApproveAllPendingView(StaffRequiredMixin, View):
    """Aprueba TODAS las pendientes que matchean el filtro (fotógrafo / evento /
    rango), sin tener que seleccionarlas de a una. Una sola UPDATE."""

    def post(self, request: HttpRequest) -> HttpResponse:
        qs = Photo.objects.filter(status=PhotoStatus.PENDING_REVIEW)
        event = request.POST.get("event", "")
        photographer = request.POST.get("photographer", "")
        rng = request.POST.get("range", "7d")
        if event:
            qs = qs.filter(event__slug=event)
        if photographer.isdigit():
            qs = qs.filter(photographer_link_id=int(photographer))
        if rng in ("7d", "30d"):
            days = 7 if rng == "7d" else 30
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))

        with transaction.atomic():
            ids = list(qs.select_for_update().values_list("id", flat=True))
            target = Photo.objects.filter(id__in=ids)
            event_ids = list(target.values_list("event_id", flat=True).distinct())
            count = target.update(
                status=PhotoStatus.APPROVED,
                approved_at=timezone.now(),
                approved_by_admin=True,
            )

        if count:
            AuditLog.log(
                "photo.bulk_approved",
                user=self.staff_user,
                metadata={
                    "count": count,
                    "scope": "approve_all",
                    "photographer": photographer,
                    "event": event,
                },
            )
            for ev in Event.objects.filter(id__in=event_ids):
                services.recalculate_event_counters(ev)

        messages.success(request, _("%(n)s fotos aprobadas.") % {"n": count})

        kept = {
            k: v for k, v in (("event", event), ("photographer", photographer), ("range", rng)) if v
        }
        url = reverse("dashboard:pending_photos")
        if kept:
            url = f"{url}?{urlencode(kept)}"
        return redirect(url)


# ---------------------------------------------------------------------------
# Dorsales (CRUD en el drawer)
# ---------------------------------------------------------------------------
class AddBibView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        photo = get_object_or_404(Photo, pk=pk)
        form = AddBibForm(request.POST)
        if form.is_valid():
            Bib.objects.create(
                photo=photo,
                number=form.cleaned_data["number"],
                confidence=1.0,
                source=BibSource.MANUAL_ADMIN,
                is_validated=True,
            )
            photo.has_bibs_detected = True
            photo.save(update_fields=["has_bibs_detected", "updated_at"])
            AuditLog.log(
                "bib.added",
                target=photo,
                user=self.staff_user,
                metadata={"number": form.cleaned_data["number"]},
            )
        return render(request, "dashboard/partials/bibs_section.html", _drawer_context(photo))


class RemoveBibView(StaffRequiredMixin, View):
    """Marca un dorsal como falso positivo (no lo borra: queda auditado)."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        bib = get_object_or_404(Bib, pk=pk)
        photo = bib.photo
        bib.rejected = True
        bib.save(update_fields=["rejected", "updated_at"])
        AuditLog.log(
            "bib.rejected", target=photo, user=self.staff_user, metadata={"number": bib.number}
        )
        return render(request, "dashboard/partials/bibs_section.html", _drawer_context(photo))
