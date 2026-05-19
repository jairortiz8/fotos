"""WSGI entrypoint — RunFoto.

Default a settings dev; override con env var DJANGO_SETTINGS_MODULE en prod.
"""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

application = get_wsgi_application()
