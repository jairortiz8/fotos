"""Ajustá el umbral de similitud facial con fotos reales.

Uso:
    python manage.py tune_threshold \
        --selfie /ruta/selfie.jpg \
        --positives /ruta/carpeta_misma_persona/ \
        --negatives /ruta/carpeta_otras_personas/

Reporta la distribución de similitudes coseno entre el selfie y:
- positivos (fotos donde SÍ está la persona) → deberían dar alta similitud
- negativos (otras personas) → deberían dar baja similitud

Y sugiere un umbral que separe ambos grupos. Documentá el valor elegido en
docs/adr/0006-face-recognition-threshold.md.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand, CommandParser


class Command(BaseCommand):
    help = "Ajusta el umbral de similitud facial con fotos reales."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--selfie", required=True, help="Selfie de referencia.")
        parser.add_argument(
            "--positives", required=True, help="Carpeta con fotos de la MISMA persona."
        )
        parser.add_argument(
            "--negatives", required=True, help="Carpeta con fotos de OTRAS personas."
        )

    def handle(self, *args: object, **opts: object) -> None:
        from apps.ml.face_recognition import embedding_from_bytes, extract_faces

        selfie_path = Path(str(opts["selfie"]))
        self.stdout.write(f"Extrayendo embedding del selfie: {selfie_path.name}")
        ref = embedding_from_bytes(selfie_path.read_bytes())

        pos = self._similarities(Path(str(opts["positives"])), ref, extract_faces)
        neg = self._similarities(Path(str(opts["negatives"])), ref, extract_faces)

        self.stdout.write("")
        self._report("POSITIVOS (misma persona — esperamos ALTO)", pos)
        self._report("NEGATIVOS (otras personas — esperamos BAJO)", neg)

        if pos and neg:
            suggested = (min(pos) + max(neg)) / 2
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Umbral sugerido: {suggested:.3f}  "
                    f"(min positivo={min(pos):.3f}, max negativo={max(neg):.3f})"
                )
            )
            if min(pos) <= max(neg):
                self.stdout.write(
                    self.style.WARNING(
                        "⚠ Los grupos se solapan — no hay umbral perfecto. "
                        "Más fotos o mejor selfie ayudarían."
                    )
                )

    def _similarities(self, folder: Path, ref: np.ndarray, extract) -> list[float]:
        sims: list[float] = []
        for f in sorted(folder.glob("*")):
            if f.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            dets = extract(f)
            if not dets:
                self.stdout.write(f"  {f.name}: sin cara")
                continue
            best = max(float(np.dot(ref, d.embedding)) for d in dets)
            sims.append(best)
            self.stdout.write(f"  {f.name}: similitud={best:.3f}")
        return sims

    def _report(self, label: str, sims: list[float]) -> None:
        if not sims:
            self.stdout.write(f"{label}: (sin datos)")
            return
        arr = np.array(sims)
        self.stdout.write(
            f"{label}: n={len(sims)} min={arr.min():.3f} max={arr.max():.3f} mean={arr.mean():.3f}"
        )
