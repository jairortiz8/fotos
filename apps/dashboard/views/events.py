"""Gestión de eventos + generación de links de upload."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.models import AuditLog
from apps.dashboard import services
from apps.dashboard.forms import EventForm, GenerateLinkForm
from apps.dashboard.mixins import DashboardContextMixin, StaffRequiredMixin
from apps.events.models import Event, EventStatus
from apps.photographers.models import PhotographerLink
from apps.photos.models import Bib, Photo, PhotoStatus

_TABS = ("resumen", "fotos", "fotografos", "links", "dorsales")


def _save_event_cover(event: Event | None, form: EventForm) -> None:
    """Si el form trae una portada nueva, la procesa (webp) → R2 → cover_key.

    Se hace acá (no en el ModelForm) porque la portada va a R2, no al disco
    efímero de Railway. Se llama después de guardar el evento (ya tiene slug).
    """
    cover = form.cleaned_data.get("cover")
    if not event or not cover:
        return
    from apps.photos.imaging import process_event_cover

    event.cover_key = process_event_cover(cover, event.slug)
    event.save(update_fields=["cover_key", "updated_at"])


class EventListView(DashboardContextMixin, ListView):
    template_name = "dashboard/event_list.html"
    context_object_name = "events"
    active_nav = "events"
    paginate_by = 30

    def get_queryset(self) -> Any:
        qs = Event.objects.exclude(status=EventStatus.DELETED)
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs.order_by("-date")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = EventStatus.choices
        ctx["status_filter"] = self.request.GET.get("status", "")
        return ctx


class EventCreateView(DashboardContextMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = "dashboard/event_form.html"
    active_nav = "events"

    def form_valid(self, form: EventForm) -> HttpResponse:
        response = super().form_valid(form)
        _save_event_cover(self.object, form)
        AuditLog.log("event.created", target=self.object, user=self.staff_user)
        messages.success(self.request, _("Evento creado."))
        return response

    def get_success_url(self) -> str:
        assert self.object is not None
        return reverse("dashboard:event_detail", kwargs={"slug": self.object.slug})

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["is_create"] = True
        return ctx


class EventUpdateView(DashboardContextMixin, UpdateView):
    model = Event
    form_class = EventForm
    template_name = "dashboard/event_form.html"
    slug_field = "slug"
    active_nav = "events"

    def form_valid(self, form: EventForm) -> HttpResponse:
        response = super().form_valid(form)
        _save_event_cover(self.object, form)
        AuditLog.log(
            "event.updated",
            target=self.object,
            user=self.staff_user,
            metadata={"changed": list(form.changed_data)},
        )
        messages.success(self.request, _("Evento actualizado."))
        return response

    def get_success_url(self) -> str:
        assert self.object is not None
        return reverse("dashboard:event_detail", kwargs={"slug": self.object.slug})


class EventDetailView(DashboardContextMixin, DetailView):
    model = Event
    template_name = "dashboard/event_detail.html"
    context_object_name = "event"
    slug_field = "slug"
    active_nav = "events"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        event: Event = self.object
        tab = self.request.GET.get("tab", "resumen")
        if tab not in _TABS:
            tab = "resumen"
        ctx["tab"] = tab
        ctx["tabs"] = [
            ("resumen", _("Resumen")),
            ("fotos", _("Fotos")),
            ("fotografos", _("Fotógrafos")),
            ("links", _("Links de subida")),
            ("dorsales", _("Dorsales")),
        ]
        ctx.update(self._tab_context(event, tab))
        return ctx

    def render_to_response(self, context: dict[str, Any], **kwargs: Any) -> HttpResponse:
        # Con HTMX devolvemos sólo el partial del tab (sin recargar la página).
        if self.request.htmx:  # type: ignore[attr-defined]
            return render(
                self.request,
                f"dashboard/partials/event_tab_{context['tab']}.html",
                context,
            )
        return super().render_to_response(context, **kwargs)

    def _tab_context(self, event: Event, tab: str) -> dict[str, Any]:
        photos = Photo.objects.filter(event=event)
        if tab == "resumen":
            return {
                "summary": {
                    "total": photos.exclude(status=PhotoStatus.DELETED).count(),
                    "pending": photos.filter(status=PhotoStatus.PENDING_REVIEW).count(),
                    "approved": photos.filter(status=PhotoStatus.APPROVED).count(),
                    "searches": event.search_count,
                },
                "recent_photos": list(
                    photos.exclude(status=PhotoStatus.DELETED).order_by("-created_at")[:8]
                ),
                "photographers": list(
                    PhotographerLink.objects.filter(event=event).order_by("-created_at")
                ),
            }
        if tab == "fotos":
            status = self.request.GET.get("foto_status", "")
            query = self.request.GET.get("q", "").strip()
            grid = photos.exclude(status=PhotoStatus.DELETED)
            if status:
                grid = grid.filter(status=status)
            if query:
                # Buscar por nombre de archivo (para encontrar una foto puntual,
                # p. ej. la que el fotógrafo reportó como fallida).
                grid = grid.filter(original_filename__icontains=query)
            # Cronológico (igual que la galería pública y la navegación del detalle).
            grid = grid.prefetch_related("bibs").order_by("capture_time", "created_at")
            return {
                "event_photos": list(grid[:120]),
                "event_photos_total": grid.count(),
                "foto_status": status,
                "foto_query": query,
                "photo_status_choices": PhotoStatus.choices,
            }
        if tab in ("fotografos", "links"):
            links = list(PhotographerLink.objects.filter(event=event).order_by("-created_at"))
            services.annotate_link_statuses(links)
            return {"links": links}
        if tab == "dorsales":
            bibs = (
                Bib.objects.filter(photo__event=event, rejected=False)
                .exclude(photo__status=PhotoStatus.DELETED)
                .values("number")
                .annotate(n=Count("id"))
                .order_by("-n", "number")
            )
            return {"bib_rows": list(bibs)}
        return {}


# ---------------------------------------------------------------------------
# Generar link de upload (modal HTMX)
# ---------------------------------------------------------------------------
class GenerateLinkView(StaffRequiredMixin, View):
    """GET: form en modal. POST: genera el link y devuelve el panel de éxito."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)
        return render(
            request,
            "dashboard/partials/generate_link_modal.html",
            {"event": event, "form": GenerateLinkForm()},
        )

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        event = get_object_or_404(Event, slug=slug)
        form = GenerateLinkForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "dashboard/partials/generate_link_modal.html",
                {"event": event, "form": form},
            )

        cd = form.cleaned_data
        link, raw_token = PhotographerLink.generate_token_and_create(
            event,
            cd["photographer_name"],
            email=cd.get("photographer_email") or None,
            phone=cd.get("photographer_phone") or "",
            expires_in_days=cd["expires_in_days"],
            photo_limit=cd.get("photo_limit") or None,
        )
        services.recalculate_event_counters(event)
        AuditLog.log(
            "photographer_link.generated",
            target=link,
            user=self.staff_user,
            metadata={"event": event.slug, "name": link.photographer_name},
        )

        url = request.build_absolute_uri(f"/u/{raw_token}/")
        expires_label = timezone.localtime(link.expires_at).strftime("%d/%m/%Y")
        return render(
            request,
            "dashboard/partials/generate_link_success.html",
            {
                "event": event,
                "link": link,
                "upload_url": url,
                "qr_data_uri": services.make_qr_png_data_uri(url),
                "whatsapp_message": services.whatsapp_message(
                    name=link.photographer_name,
                    event_name=event.name,
                    url=url,
                    expires_label=expires_label,
                ),
                "expires_label": expires_label,
            },
        )


def event_detail_redirect(request: HttpRequest, slug: str) -> HttpResponse:
    """Helper para redirigir a un tab puntual del detalle."""
    return redirect(reverse("dashboard:event_detail", kwargs={"slug": slug}))
