"""Vistas públicas comunes — health check + robots."""

from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse


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


def healthz(request: HttpRequest) -> JsonResponse:
    """Health check para Railway / load balancer / Docker.

    Devuelve 200 si la DB y Redis están alcanzables; 503 si alguno falla.
    """
    db_ok = _check_db()
    redis_ok = _check_redis()

    payload: dict[str, Any] = {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": "ok" if db_ok else "fail",
        "redis": "ok" if redis_ok else "fail",
    }
    status_code = 200 if (db_ok and redis_ok) else 503
    return JsonResponse(payload, status=status_code)


def _check_db() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return False
    return True


def _check_redis() -> bool:
    try:
        sentinel = "__runfoto_healthz__"
        cache.set(sentinel, "ok", timeout=10)
        return cache.get(sentinel) == "ok"
    except Exception:
        return False
