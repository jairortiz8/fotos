"""Login / logout del dashboard."""

from __future__ import annotations

from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django_ratelimit.core import is_ratelimited


def _login_rate_limited(request: HttpRequest) -> bool:
    """5 intentos POST por IP cada 15 minutos (CLAUDE.md §3)."""
    return is_ratelimited(
        request,
        group="dashboard-login",
        key="ip",
        rate="5/15m",
        method="POST",
        increment=True,
    )


class DashboardLoginView(LoginView):
    template_name = "dashboard/login.html"
    redirect_authenticated_user = True
    # LOGIN_REDIRECT_URL = dashboard:dashboard_home (settings); `next` se respeta.

    def post(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if _login_rate_limited(request):
            # Mensaje por contexto (no via form): evita disparar `authenticate()`
            # del AuthenticationForm.clean() con un form sin datos.
            ctx = self.get_context_data(form=self.get_form_class()(request=request))
            ctx["rate_limit_error"] = _(
                "Demasiados intentos. Esperá 15 minutos antes de volver a probar."
            )
            return self.render_to_response(ctx)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form: AuthenticationForm) -> HttpResponse:
        # Solo cuentas staff entran al panel (el sistema tiene 1 super admin).
        user = form.get_user()
        if not user.is_staff:
            form.add_error(None, _("Esta cuenta no tiene acceso al panel."))
            return self.form_invalid(form)
        return super().form_valid(form)


class DashboardLogoutView(LogoutView):
    next_page = reverse_lazy("core:index")  # type: ignore[assignment]
