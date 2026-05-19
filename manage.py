#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    """Run administrative tasks."""
    base_dir = Path(__file__).resolve().parent

    # Cargar .env localmente si existe (no se commitea).
    env_file = base_dir / ".env"
    if env_file.exists():
        try:
            from environ import Env

            Env.read_env(str(env_file))
        except ImportError:
            pass

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError("No pude importar Django. ¿Está instalado y el venv activado?") from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
