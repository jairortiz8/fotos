"""Pipeline de reconocimiento facial (InsightFace buffalo_l).

PRIVACIDAD (CLAUDE.md §3 — reglas no negociables):
- Los embeddings de las fotos del evento se guardan (para matching).
- El embedding del SELFIE del usuario NUNCA se guarda: vive en memoria
  durante el request y se descarta. `embedding_from_bytes` procesa en RAM.
- Nunca loggear el vector completo — solo "embedding extracted dims=512".
- Nunca exponer embeddings vía JSON al cliente.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 512
MODEL_NAME = "buffalo_l"
DET_SIZE = (640, 640)


# ---------------------------------------------------------------------------
# Errores de dominio (para que las vistas devuelvan respuestas claras)
# ---------------------------------------------------------------------------
class FaceRecognitionError(RuntimeError):
    """Base."""


class InvalidImageError(FaceRecognitionError):
    """El archivo no se pudo decodificar como imagen."""


class NoFaceDetectedError(FaceRecognitionError):
    """No se detectó ninguna cara en el selfie."""


class MultipleFacesDetectedError(FaceRecognitionError):
    """Se detectaron varias caras (ambiguo para un selfie)."""


# ---------------------------------------------------------------------------
# Tipo de salida
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FaceDetection:
    """Una cara detectada en una imagen."""

    embedding: np.ndarray  # (512,) float32 — normalizado L2
    bbox: list[float]  # [x1, y1, x2, y2] en pixels
    det_score: float
    age: int
    gender: str  # "M" | "F"


# ---------------------------------------------------------------------------
# Modelo singleton (lazy, thread-safe)
# ---------------------------------------------------------------------------
_model_lock = threading.Lock()
_model: Any | None = None


def get_face_model() -> Any:
    """Singleton de InsightFace FaceAnalysis. Descarga buffalo_l el primer uso."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                import insightface

                kwargs: dict[str, Any] = {
                    "name": MODEL_NAME,
                    "providers": ["CPUExecutionProvider"],
                }
                # En prod el modelo viene pre-cacheado en /opt/insightface
                # (ver Dockerfile). Si la env var está, usamos ese root para
                # no re-descargar buffalo_l en cada arranque del dyno.
                root = os.environ.get("INSIGHTFACE_ROOT")
                if root:
                    kwargs["root"] = root

                app = insightface.app.FaceAnalysis(**kwargs)
                app.prepare(ctx_id=0, det_size=DET_SIZE)
                _model = app
    return _model


def reset_model_for_tests() -> None:
    global _model
    _model = None


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """L2 normalize → cosine similarity == producto interno."""
    arr = np.asarray(embedding, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return arr
    return arr / norm


# ---------------------------------------------------------------------------
# Extracción
# ---------------------------------------------------------------------------
def _detections_from_faces(faces: list[Any]) -> list[FaceDetection]:
    out: list[FaceDetection] = []
    for face in faces:
        out.append(
            FaceDetection(
                embedding=normalize_embedding(face.embedding),
                bbox=[float(v) for v in face.bbox.tolist()],
                det_score=float(face.det_score),
                age=int(getattr(face, "age", 0) or 0),
                gender=str(getattr(face, "sex", "") or ""),
            )
        )
    return out


def extract_faces(image_path: Path) -> list[FaceDetection]:
    """Detecta todas las caras de una imagen en disco. [] si no hay."""
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        logger.warning("extract_faces: no pude leer %s", image_path)
        return []
    faces = get_face_model().get(img)
    detections = _detections_from_faces(faces)
    logger.info("extract_faces: %d cara(s) en %s", len(detections), image_path.name)
    return detections


def embedding_from_bytes(image_bytes: bytes) -> np.ndarray:
    """Extrae el embedding de UN selfie desde bytes EN MEMORIA.

    Nunca toca disco ni R2. Devuelve el embedding normalizado de la cara
    principal. Lanza NoFaceDetectedError / MultipleFacesDetectedError /
    InvalidImageError según corresponda.
    """
    import cv2

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise InvalidImageError("No se pudo decodificar la imagen.")

    faces = get_face_model().get(img)
    if not faces:
        raise NoFaceDetectedError("No se detectó ninguna cara en el selfie.")
    if len(faces) > 1:
        raise MultipleFacesDetectedError(
            f"Se detectaron {len(faces)} caras; subí una selfie con una sola cara."
        )

    logger.info("embedding_from_bytes: embedding extracted dims=%d", EMBEDDING_DIM)
    return normalize_embedding(faces[0].embedding)
