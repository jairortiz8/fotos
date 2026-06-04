"""Mixins de acceso para el dashboard admin.

Todas las vistas del dashboard requieren un usuario logueado Y `is_staff=True`.
El super admin (Jair) es la única cuenta del sistema (CLAUDE.md §1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth.mixins import AccessMixin
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.generic.base import ContextMixin

if TYPE_CHECKING:
    from apps.core.models import User


class StaffRequiredMixin(AccessMixin):
    """Exige login + `is_staff`. Si no, redirige al login con `?next=`.

    Se aplica a TODAS las vistas del dashboard. Un usuario logueado sin `is_staff`
    se trata igual que uno anónimo: lo mandamos al login en vez de un 403 que
    revelaría que el panel existe.
    """

    # `request` la inyecta `View.setup()` en runtime; lo declaramos para mypy.
    request: HttpRequest

    def dispatch(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not request.user.is_authenticated or not request.user.is_staff:
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def handle_no_permission(self) -> HttpResponseRedirect:
        # Redirigimos SIEMPRE al login (también si está logueado sin is_staff):
        # no queremos un 403 que confirme la existencia del panel.
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(
            self.request.get_full_path(),
            self.get_login_url(),
            self.get_redirect_field_name(),
        )

    @property
    def staff_user(self) -> User:
        """`request.user` garantizado autenticado+staff (post `dispatch`).

        Existe para que mypy no vea `User | AnonymousUser` al pasar el usuario a
        `AuditLog.log(user=...)`.
        """
        return cast("User", self.request.user)


class DashboardContextMixin(StaffRequiredMixin, ContextMixin):
    """Contexto común para las vistas con template del dashboard.

    Inyecta `active_nav` (qué item del sidebar resaltar) y `nav_pending_count`
    (el badge naranja de fotos pendientes). Las vistas de acción (POST sin
    template) usan sólo `StaffRequiredMixin`.
    """

    active_nav: str = ""

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.photos.models import Photo, PhotoStatus

        ctx = super().get_context_data(**kwargs)
        ctx["active_nav"] = self.active_nav
        ctx["nav_pending_count"] = Photo.objects.filter(status=PhotoStatus.PENDING_REVIEW).count()
        return ctx
