"""Guard contra un bug recurrente: comentarios {# ... #} multilínea.

Django trata `{# ... #}` como comentario SOLO si abre y cierra en la MISMA
línea. Un `{#` que no cierra en su línea se renderiza como TEXTO VISIBLE en la
página (no como comentario). Ya pasó varias veces en este repo (Fase 3, el
scrim del hero, la portada de la galería). Para comentarios de varias líneas
hay que usar `{% comment %}...{% endcomment %}`.

Este test barre todos los templates y falla si encuentra un `{#` sin su `#}` en
la misma línea, así el error se atrapa en CI en vez de en producción.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


def _template_dirs() -> list[Path]:
    base = Path(settings.BASE_DIR)
    dirs = [base / "templates"]
    dirs += [p for p in (base / "apps").glob("*/templates") if p.is_dir()]
    return [d for d in dirs if d.is_dir()]


def test_no_multiline_django_comments() -> None:
    offenders: list[str] = []
    for root in _template_dirs():
        for path in root.rglob("*.html"):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                idx = line.rfind("{#")
                # Un {# cuya línea no contiene un #} posterior = comentario que
                # sigue en la línea de abajo → Django lo renderiza como texto.
                if idx != -1 and "#}" not in line[idx:]:
                    offenders.append(f"{path.relative_to(Path(settings.BASE_DIR))}:{lineno}")
    assert not offenders, (
        "Comentarios {# #} multilínea detectados (Django los renderiza como TEXTO "
        "visible). Usá {% comment %}…{% endcomment %} para varias líneas:\n  "
        + "\n  ".join(offenders)
    )
