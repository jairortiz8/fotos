"""Tests de EventMetric + record_event_metric (los baldes de las curvas)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.events.metrics import Metric, record_event_metric
from apps.events.models import EventMetric
from tests.factories import EventFactory


@pytest.mark.django_db
def test_record_creates_hourly_bucket() -> None:
    event = EventFactory()
    record_event_metric(event.id, Metric.DOWNLOAD)
    m = EventMetric.objects.get(event=event, metric="download")
    assert m.count == 1
    # El balde queda anclado al inicio de la hora (UTC).
    assert (m.bucket.minute, m.bucket.second, m.bucket.microsecond) == (0, 0, 0)


@pytest.mark.django_db
def test_record_accumulates_within_same_hour() -> None:
    event = EventFactory()
    when = timezone.now()
    record_event_metric(event.id, Metric.VIEW, when=when)
    record_event_metric(event.id, Metric.VIEW, count=3, when=when)
    assert EventMetric.objects.filter(event=event, metric="view").count() == 1
    assert EventMetric.objects.get(event=event, metric="view").count == 4


@pytest.mark.django_db
def test_record_separate_buckets_per_hour() -> None:
    event = EventFactory()
    now = timezone.now()
    record_event_metric(event.id, Metric.SEARCH, when=now)
    record_event_metric(event.id, Metric.SEARCH, when=now - dt.timedelta(hours=1))
    assert EventMetric.objects.filter(event=event, metric="search").count() == 2


@pytest.mark.django_db
def test_record_separates_by_metric() -> None:
    event = EventFactory()
    record_event_metric(event.id, Metric.DOWNLOAD)
    record_event_metric(event.id, Metric.UPLOAD)
    assert EventMetric.objects.filter(event=event).count() == 2


@pytest.mark.django_db
def test_record_noop_on_missing_event() -> None:
    record_event_metric(None, Metric.DOWNLOAD)
    record_event_metric(0, Metric.DOWNLOAD)
    assert EventMetric.objects.count() == 0


@pytest.mark.django_db
def test_record_zero_count_is_noop() -> None:
    event = EventFactory()
    record_event_metric(event.id, Metric.UPLOAD, count=0)
    assert EventMetric.objects.count() == 0
