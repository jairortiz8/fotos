"""Vistas del dashboard admin (re-exportadas para `urls.py`)."""

from __future__ import annotations

from apps.dashboard.views.analytics import AnalyticsView
from apps.dashboard.views.auth import DashboardLoginView, DashboardLogoutView
from apps.dashboard.views.events import (
    EventCreateView,
    EventDetailView,
    EventListView,
    EventUpdateView,
    GenerateLinkView,
    RegenerateThumbnailsView,
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
    BibsSectionView,
    BulkApproveView,
    BulkRejectView,
    PendingPhotosView,
    PhotoDetailView,
    RejectPhotoView,
    RemoveBibView,
    RerunOcrView,
)

__all__ = [
    "AddBibView",
    "AnalyticsView",
    "ApproveAllPendingView",
    "ApprovePhotoView",
    "AuditLogView",
    "BibsSectionView",
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
    "RegenerateThumbnailsView",
    "RejectPhotoView",
    "RemoveBibView",
    "RerunOcrView",
    "RevokeLinkView",
    "SettingsView",
    "StatsView",
]
