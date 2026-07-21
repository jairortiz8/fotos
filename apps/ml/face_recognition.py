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

# Sólo cargamos los modelos del pack buffalo_l que realmente usamos:
#  - detection (det_10g): bbox + keypoints (alineación) + det_score
#  - recognition (w600k_r50): el embedding de 512-d
#  - genderage: edad (blur de menores) + género
# Omitimos landmark_3d_68 (1k3d68, ~143MB) y landmark_2d_106 (2d106det) que NO
# usamos. Esto baja el pico de RAM ~200-300MB para entrar en el dyno de 1GB y
# acelera la carga. La alineación para recognition usa los 5 keypoints del
# detector, no los 106 puntos del landmark 2D — así que esto no afecta el match.
ALLOWED_MODULES = ["detection", "recognition", "genderage"]


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
                    "allowed_modules": ALLOWED_MODULES,
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


def _oriented_bgr_from_pil(pim: Any) -> np.ndarray:
    """PIL image → ndarray BGR (lo que espera InsightFace/cv2), rotada según la
    orientación EXIF. Sin esto, `cv2.imread`/`cv2.imdecode` ignoran el tag de
    orientación y una foto vertical se detecta ACOSTADA (peor detección de caras)."""
    from PIL import ImageOps

    pim = ImageOps.exif_transpose(pim) or pim
    rgb = pim.convert("RGB")
    return np.ascontiguousarray(np.asarray(rgb)[:, :, ::-1])  # RGB → BGR


def extract_faces(image_path: Path) -> list[FaceDetection]:
    """Detecta todas las caras de una imagen en disco. [] si no hay."""
    import cv2
    from PIL import Image

    try:
        with Image.open(image_path) as pim:
            img: np.ndarray | None = _oriented_bgr_from_pil(pim)
    except Exception:
        img = cv2.imread(str(image_path))  # fallback
    if img is None:
        logger.warning("extract_faces: no pude leer %s", image_path)
        return []
    faces = get_face_model().get(img)
    detections = _detections_from_faces(faces)
    logger.info("extract_faces: %d cara(s) en %s", len(detections), image_path.name)
    return detections


def _pad_for_detection(img: np.ndarray) -> np.ndarray:
    """Escala + agrega borde a una imagen para que el detector la "vea".

    RetinaFace (det_10g) necesita CONTEXTO alrededor de la cara y un tamaño
    mínimo. Cuando el usuario sube un recorte AJUSTADO (la cara llena todo el
    cuadro, sin margen) o muy chico, el detector devuelve 0 caras aunque la
    cara esté ahí. Escalamos el lado menor a ~640px y agregamos un borde del
    35% (replicando los pixeles del borde) para darle ese contexto. Sólo se
    usa como FALLBACK cuando la detección directa no encontró nada.
    """
    import cv2

    h, w = img.shape[:2]
    scale = max(1.0, 640.0 / max(1, min(h, w)))
    if scale > 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    bh = int(img.shape[0] * 0.35)
    bw = int(img.shape[1] * 0.35)
    return cv2.copyMakeBorder(img, bh, bh, bw, bw, cv2.BORDER_REPLICATE)


def embedding_from_bytes(image_bytes: bytes) -> np.ndarray:
    """Extrae el embedding de UN selfie desde bytes EN MEMORIA.

    Nunca toca disco ni R2. Devuelve el embedding normalizado de la cara
    principal. Lanza NoFaceDetectedError / MultipleFacesDetectedError /
    InvalidImageError según corresponda.
    """
    import cv2
    from PIL import Image

    try:
        from io import BytesIO

        with Image.open(BytesIO(image_bytes)) as pim:
            # cv2.imdecode (rama except) puede devolver None → tipamos Optional y
            # lo cubre el `if img is None` de abajo.
            img: np.ndarray | None = _oriented_bgr_from_pil(pim)  # respeta EXIF del selfie
    except Exception:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise InvalidImageError("No se pudo decodificar la imagen.")

    model = get_face_model()
    faces = model.get(img)

    # Fallback: el usuario suele recortar la cara muy justa (sin margen) o la
    # imagen es chica → el detector devuelve 0 caras. Reintentamos con la
    # imagen escalada + con borde para darle contexto. (Un selfie normal pasa
    # por la rama de arriba y nunca llega acá — sin cambio de comportamiento.)
    used_fallback = False
    if not faces:
        faces = model.get(_pad_for_detection(img))
        used_fallback = True

    if not faces:
        raise NoFaceDetectedError("No se detectó ninguna cara en el selfie.")
    # En el flujo normal, varias caras es ambiguo (¿a quién busco?) → error.
    # En el fallback (recorte ajustado de UNA cara) elegimos la más prominente:
    # los reintentos con borde pueden generar detecciones espurias en el borde.
    if len(faces) > 1 and not used_fallback:
        raise MultipleFacesDetectedError(
            f"Se detectaron {len(faces)} caras; subí una selfie con una sola cara."
        )

    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    logger.info("embedding_from_bytes: embedding extracted dims=%d", EMBEDDING_DIM)
    return normalize_embedding(face.embedding)
