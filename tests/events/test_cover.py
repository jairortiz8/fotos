"""Tests de la portada del evento (R2) + redes del organizador."""

from __future__ import annotations

import boto3
import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from moto import mock_aws

from apps.events.models import Event, EventStatus, _social_url
from apps.photos import storage as storage_module
from tests.factories import EventFactory

BUCKET = "test-bucket"


@pytest.fixture
def r2(settings):  # type: ignore[no-untyped-def]
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = "AKIA-TEST"
    settings.R2_SECRET_ACCESS_KEY = "SECRET-TEST"
    settings.R2_BUCKET_NAME = BUCKET
    storage_module.reset_default_storage_for_tests()
    cache.clear()
    with mock_aws():
        client = boto3.client(
            "s3",
            aws_access_key_id="AKIA-TEST",
            aws_secret_access_key="SECRET-TEST",
            region_name="us-east-1",
        )
        client.create_bucket(Bucket=BUCKET)
        yield client
    storage_module.reset_default_storage_for_tests()
    cache.clear()


# ---------------------------------------------------------------------------
# process_event_cover
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_process_event_cover_uploads_webp(r2) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.synthetic import synthetic_jpeg_bytes
    from apps.photos.imaging import process_event_cover

    key = process_event_cover(synthetic_jpeg_bytes("1"), "mi-evento")
    assert key == "event_covers/mi-evento.webp"
    obj = r2.get_object(Bucket=BUCKET, Key=key)
    assert obj["ContentType"] == "image/webp"
    assert obj["Body"].read()[:4] == b"RIFF"  # cabecera WEBP


# ---------------------------------------------------------------------------
# cover_url (modelo)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_cover_url_empty_when_no_cover() -> None:
    assert EventFactory(cover_key="").cover_url() == ""


@pytest.mark.django_db
def test_cover_url_is_versioned() -> None:
    event = EventFactory(cover_key="event_covers/x.webp")
    url = event.cover_url()
    assert reverse("events:cover", kwargs={"slug": event.slug}) in url
    assert "?v=" in url  # bustea cache al cambiar la portada


# ---------------------------------------------------------------------------
# EventCoverView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_cover_view_serves_webp_with_cache(r2) -> None:  # type: ignore[no-untyped-def]
    from apps.ml.synthetic import synthetic_jpeg_bytes
    from apps.photos.imaging import process_event_cover

    event = EventFactory(slug="con-portada")
    event.cover_key = process_event_cover(synthetic_jpeg_bytes("1"), event.slug)
    event.save(update_fields=["cover_key"])

    resp = Client().get(reverse("events:cover", kwargs={"slug": event.slug}))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "image/webp"
    assert "max-age" in resp["Cache-Control"]
    assert b"".join(resp.streaming_content)[:4] == b"RIFF"


@pytest.mark.django_db
def test_cover_view_404_without_cover(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(cover_key="")
    resp = Client().get(reverse("events:cover", kwargs={"slug": event.slug}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cover_view_404_for_deleted_event(r2) -> None:  # type: ignore[no-untyped-def]
    event = EventFactory(cover_key="event_covers/x.webp", status=EventStatus.DELETED)
    resp = Client().get(reverse("events:cover", kwargs={"slug": event.slug}))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Redes del organizador
# ---------------------------------------------------------------------------
def test_social_url_handle() -> None:
    assert _social_url("@evento", "instagram.com") == "https://instagram.com/evento"
    assert _social_url("evento", "facebook.com") == "https://facebook.com/evento"


def test_social_url_full_link_passthrough() -> None:
    assert _social_url("https://instagram.com/x/", "instagram.com") == "https://instagram.com/x/"


def test_social_url_empty() -> None:
    assert _social_url("", "instagram.com") == ""
    assert _social_url("  ", "instagram.com") == ""


def test_event_social_methods() -> None:
    event = Event(organizer_instagram="@maraton", organizer_facebook="")
    assert event.instagram_url() == "https://instagram.com/maraton"
    assert event.facebook_url() == ""
    assert event.has_organizer() is True
    assert Event().has_organizer() is False
