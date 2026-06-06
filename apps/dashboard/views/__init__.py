"""Vistas del dashboard admin (re-exportadas para `urls.py`)."""

from __future__ import annotations

from apps.dashboard.views.auth import DashboardLoginView, DashboardLogoutView
from apps.dashboard.views.events import (
    EventCreateView,
    EventDetailView,
    EventListView,
    EventUpdateView,
    GenerateLinkView,
)
from apps.dashboard.views.home import DashboardHomeView
from apps.dashboard.views.misc import AuditLogView, SettingsView, StatsView
from apps.dashboard.views.photographers import (
    PhotographerLinkListView,
    RegenerateLinkView,
    RevokeLinkView,
)
from apps.dashboard.views.photos import (
    AddBibView,
    ApproveAllPendingView,
    ApprovePhotoView,
    BulkApproveView,
    BulkRejectView,
    PendingPhotosView,
    PhotoDetailView,
    RejectPhotoView,
    RemoveBibView,
)

__all__ = [
    "AddBibView",
    "ApproveAllPendingView",
    "ApprovePhotoView",
    "AuditLogView",
    "BulkApproveView",
    "BulkRejectView",
    "DashboardHomeView",
    "DashboardLoginView",
    "DashboardLogoutView",
    "EventCreateView",
    "EventDetailView",
    "EventListView",
    "EventUpdateView",
    "GenerateLinkView",
    "PendingPhotosView",
    "PhotoDetailView",
    "PhotographerLinkListView",
    "RegenerateLinkView",
    "RejectPhotoView",
    "RemoveBibView",
    "RevokeLinkView",
    "SettingsView",
    "StatsView",
]
