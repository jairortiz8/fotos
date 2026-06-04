"""Gestión de links de fotógrafo: listar, revocar, regenerar."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import ListView

from apps.core.models import AuditLog
from apps.dashboard import services
from apps.dashboard.mixins import DashboardContextMixin, StaffRequiredMixin
from apps.photographers.models import PhotographerLink
from apps.photos.models import PhotoStatus


def _annotate(links: list[PhotographerLink]) -> list[PhotographerLink]:
    services.annotate_link_statuses(links)
    for link in links:
        uploaded = link.photos_uploaded or 0
        approved = link.photos.filter(status=PhotoStatus.APPROVED).count()
        link.approval_pct = round(approved / uploaded * 100) if uploaded else 0  # type: ignore[attr-defined]
    return links


class PhotographerLinkListView(DashboardContextMixin, ListView):
    template_name = "dashboard/photographer_list.html"
    context_object_name = "links"
    active_nav = "photographers"
    paginate_by = 50

    def get_queryset(self) -> Any:
        qs = PhotographerLink.objects.select_related("event")
        event = self.request.GET.get("event")
        if event:
            qs = qs.filter(event__slug=event)
        state = self.request.GET.get("state")
        now = timezone.now()
        if state == "active":
            qs = qs.filter(is_active=True, expires_at__gte=now)
        elif state == "expired":
            qs = qs.filter(is_active=True, expires_at__lt=now)
        elif state == "revoked":
            qs = qs.filter(is_active=False)
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        _annotate(list(ctx["links"]))
        ctx["filter_state"] = self.request.GET.get("state", "")
        ctx["filter_event"] = self.request.GET.get("event", "")
        return ctx


class RevokeLinkView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        link = get_object_or_404(PhotographerLink, pk=pk)
        reason = request.POST.get("reason", "").strip()[:255]
        link.revoke(reason=reason)  # registra el AuditLog internamente
        messages.success(request, _("Link revocado."))
        if request.htmx:  # type: ignore[attr-defined]
            resp = HttpResponse(status=204)
            resp["HX-Redirect"] = reverse("dashboard:photographer_list")
            return resp
        return redirect("dashboard:photographer_list")


class RegenerateLinkView(StaffRequiredMixin, View):
    """Crea un link nuevo (token nuevo) para el mismo fotógrafo y revoca el viejo."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        old = get_object_or_404(PhotographerLink, pk=pk)
        days = max(1, (old.expires_at - old.created_at).days) if old.expires_at else 30
        new_link, raw_token = PhotographerLink.generate_token_and_create(
            old.event,
            old.photographer_name,
            email=old.photographer_email or None,
            phone=old.photographer_phone or "",
            expires_in_days=days,
            photo_limit=old.photo_limit,
        )
        if old.is_active:
            old.revoke(reason="regenerado")
        AuditLog.log(
            "photographer_link.regenerated",
            target=new_link,
            user=self.staff_user,
            metadata={"old_id": old.id, "event": old.event.slug},
        )

        url = request.build_absolute_uri(f"/u/{raw_token}/")
        expires_label = timezone.localtime(new_link.expires_at).strftime("%d/%m/%Y")
        return render(
            request,
            "dashboard/partials/generate_link_success.html",
            {
                "event": old.event,
                "link": new_link,
                "upload_url": url,
                "qr_data_uri": services.make_qr_png_data_uri(url),
                "whatsapp_message": services.whatsapp_message(
                    name=new_link.photographer_name,
                    event_name=old.event.name,
                    url=url,
                    expires_label=expires_label,
                ),
                "expires_label": expires_label,
            },
        )
