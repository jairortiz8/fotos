"""Vistas públicas comunes — health checks, robots, páginas de error."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone


def robots_txt(request: HttpRequest) -> HttpResponse:
    """robots.txt permisivo (contenido público) excepto admin / portal / descargas."""
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /u/",
        "Disallow: /descargas/",
        "Disallow: /__debug__/",
        "Allow: /",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
def healthz_lite(request: HttpRequest) -> JsonResponse:
    """Health check LIVIANO para el probe de Railway: sólo DB.

    El probe de la plataforma debe ser barato y no depender de servicios
    externos (R2) ni de los workers (que pueden no estar corriendo).
    """
    ok = _check_db()["ok"]
    return JsonResponse({"status": "ok" if ok else "degraded"}, status=200 if ok else 503)


def healthz(request: HttpRequest) -> JsonResponse:
    """Health check PROFUNDO para monitoreo manual.

    503 SÓLO si DB o Redis fallan (lo crítico). R2 y Celery se reportan como
    checks informativos: que falten (worker no levantado, R2 sin credenciales en
    dev) NO debe marcar el servicio como caído ni tumbar un deploy.
    """
    checks: dict[str, dict[str, Any]] = {
        "db": _check_db(),
        "redis": _check_redis(),
        "r2": _check_r2(),
        "celery_workers": _check_celery_workers(),
        "celery_beat": _check_celery_beat(),
    }
    critical_ok = checks["db"]["ok"] and checks["redis"]["ok"]
    all_ok = all(c["ok"] for c in checks.values())

    return JsonResponse(
        {
            "status": "ok" if all_ok else ("degraded" if critical_ok else "down"),
            "checks": checks,
            "version": settings.GIT_SHA,
            "timestamp": timezone.now().isoformat(),
        },
        status=200 if critical_ok else 503,
    )


def _check_db() -> dict[str, Any]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return {"ok": False}
    return {"ok": True}


def _check_redis() -> dict[str, Any]:
    try:
        cache.set("__runfoto_healthz__", "ok", timeout=10)
        return {"ok": cache.get("__runfoto_healthz__") == "ok"}
    except Exception:
        return {"ok": False}


def _check_r2() -> dict[str, Any]:
    """Lista 1 objeto del bucket. Si R2 no está configurado, lo reporta sin romper."""
    from apps.photos.storage import R2NotConfiguredError, default_storage

    try:
        default_storage().client.list_objects_v2(Bucket=default_storage().bucket, MaxKeys=1)
    except R2NotConfiguredError:
        return {"ok": False, "configured": False}
    except Exception:
        return {"ok": False, "configured": True}
    return {"ok": True, "configured": True}


def _check_celery_workers() -> dict[str, Any]:
    """¿Hay al menos 1 worker activo? Pinga el broker con timeout corto."""
    try:
        from config.celery import app as celery_app

        replies = celery_app.control.inspect(timeout=0.5).ping() or {}
    except Exception:
        return {"ok": False, "workers": 0}
    return {"ok": bool(replies), "workers": len(replies)}


def _check_celery_beat() -> dict[str, Any]:
    """Informativo: hay un schedule de beat configurado (no verifica que corra)."""
    return {
        "ok": bool(settings.CELERY_BEAT_SCHEDULE),
        "scheduled_tasks": len(settings.CELERY_BEAT_SCHEDULE),
    }


# ---------------------------------------------------------------------------
# Páginas de error custom (handler404 / handler500 en config/urls.py)
# ---------------------------------------------------------------------------
def handler404(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return render(request, "errors/404.html", status=404)


def handler500(request: HttpRequest) -> HttpResponse:
    # handler500 corre SIN context processors; el template es self-contained.
    return render(request, "errors/500.html", status=500)
