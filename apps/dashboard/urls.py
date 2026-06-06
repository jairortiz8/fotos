"""URLs del dashboard admin (montado en /dashboard/)."""

from __future__ import annotations

from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardHomeView.as_view(), name="dashboard_home"),
    path("login/", views.DashboardLoginView.as_view(), name="dashboard_login"),
    path("logout/", views.DashboardLogoutView.as_view(), name="dashboard_logout"),
    # --- Eventos ---
    path("eventos/", views.EventListView.as_view(), name="event_list"),
    path("eventos/nuevo/", views.EventCreateView.as_view(), name="event_create"),
    path("eventos/<slug:slug>/", views.EventDetailView.as_view(), name="event_detail"),
    path("eventos/<slug:slug>/editar/", views.EventUpdateView.as_view(), name="event_update"),
    path(
        "eventos/<slug:slug>/generar-link/",
        views.GenerateLinkView.as_view(),
        name="generate_link",
    ),
    # --- Aprobación ---
    path("fotos/pendientes/", views.PendingPhotosView.as_view(), name="pending_photos"),
    path("fotos/<int:pk>/", views.PhotoDetailView.as_view(), name="photo_detail"),
    path("fotos/<int:pk>/aprobar/", views.ApprovePhotoView.as_view(), name="approve_photo"),
    path("fotos/<int:pk>/rechazar/", views.RejectPhotoView.as_view(), name="reject_photo"),
    path("fotos/<int:pk>/dorsal/agregar/", views.AddBibView.as_view(), name="add_bib"),
    path("dorsales/<int:pk>/quitar/", views.RemoveBibView.as_view(), name="remove_bib"),
    path("fotos/bulk/aprobar/", views.BulkApproveView.as_view(), name="bulk_approve"),
    path("fotos/bulk/rechazar/", views.BulkRejectView.as_view(), name="bulk_reject"),
    path(
        "fotos/bulk/aprobar-todas/",
        views.ApproveAllPendingView.as_view(),
        name="approve_all_pending",
    ),
    # --- Fotógrafos ---
    path("fotografos/", views.PhotographerLinkListView.as_view(), name="photographer_list"),
    path("fotografos/<int:pk>/revocar/", views.RevokeLinkView.as_view(), name="revoke_link"),
    path(
        "fotografos/<int:pk>/regenerar/",
        views.RegenerateLinkView.as_view(),
        name="regenerate_link",
    ),
    # --- Sistema ---
    path("estadisticas/", views.StatsView.as_view(), name="stats"),
    path("audit-log/", views.AuditLogView.as_view(), name="audit_log"),
    path("configuracion/", views.SettingsView.as_view(), name="settings"),
]
