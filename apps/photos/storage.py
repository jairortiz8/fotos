"""Wrapper de Cloudflare R2 vía boto3.

Convención de keys (CLAUDE.md §3 / runbook):
    events/<event_slug>/originals/<photo_uuid>.jpg
    events/<event_slug>/previews/<photo_uuid>.webp
    events/<event_slug>/thumbnails/<photo_uuid>.webp
    events/<event_slug>/zips/<zip_uuid>.zip            (efímeros)
    event_covers/<event_slug>.webp

R2 es privado: nada se sirve sin firmar. Default TTL de URL firmada: 15 min.
"""

from __future__ import annotations

import logging
import uuid
from typing import IO, Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

logger = logging.getLogger(__name__)


PRESIGNED_URL_DEFAULT_TTL = 15 * 60  # 15 minutos


class R2UploadError(RuntimeError):
    """Subida a R2 falló (red, credenciales, bucket inexistente, etc.)."""


class R2NotConfiguredError(RuntimeError):
    """Faltan credenciales / endpoint / bucket en settings."""


class R2Storage:
    """Cliente S3-compatible apuntado a Cloudflare R2.

    Lazy: el cliente boto3 se crea recién al primer uso. Si las credenciales
    no están seteadas (típico en CI antes de cargar secrets), `__init__` no
    rompe — sólo rompe al intentar usar la API.
    """

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket: str | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url if endpoint_url is not None else settings.R2_ENDPOINT_URL
        self.access_key_id = (
            access_key_id if access_key_id is not None else settings.R2_ACCESS_KEY_ID
        )
        self.secret_access_key = (
            secret_access_key if secret_access_key is not None else settings.R2_SECRET_ACCESS_KEY
        )
        self.bucket = bucket if bucket is not None else settings.R2_BUCKET_NAME
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _build_client(self) -> Any:
        if not (self.access_key_id and self.secret_access_key and self.bucket):
            raise R2NotConfiguredError(
                "R2 no está configurado: revisá R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY "
                "y R2_BUCKET_NAME en el entorno."
            )
        # `endpoint_url` vacío significa "usar default de AWS S3" — útil en tests
        # con `moto` (intercepta s3.amazonaws.com sin tocar la red).
        # En prod siempre va el endpoint de Cloudflare.
        kwargs: dict[str, Any] = {
            "aws_access_key_id": self.access_key_id,
            "aws_secret_access_key": self.secret_access_key,
            "region_name": "auto" if self.endpoint_url else "us-east-1",
            "config": Config(signature_version="s3v4", retries={"max_attempts": 3}),
        }
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return boto3.client("s3", **kwargs)

    # ------------------------------------------------------------------
    # Upload / download
    # ------------------------------------------------------------------
    def upload(
        self,
        file_obj: IO[bytes],
        key: str,
        *,
        content_type: str = "image/jpeg",
        cache_control: str = "private, max-age=3600",
    ) -> str:
        """Sube un file-like object al bucket y devuelve el key."""
        try:
            self.client.upload_fileobj(
                file_obj,
                self.bucket,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": cache_control,
                },
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception("R2 upload failed for key %s", key)
            raise R2UploadError(str(exc)) from exc
        return key

    def download_fileobj(self, key: str, file_obj: IO[bytes]) -> None:
        """Descarga un objeto a un file-like (típicamente un BytesIO o tempfile)."""
        try:
            self.client.download_fileobj(self.bucket, key, file_obj)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("R2 download failed for key %s", key)
            raise R2UploadError(str(exc)) from exc

    def exists(self, key: str) -> bool:
        """True si el objeto existe en el bucket (HEAD, sin descargarlo)."""
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise R2UploadError(str(exc)) from exc
        except BotoCoreError as exc:
            raise R2UploadError(str(exc)) from exc

    def get_signed_url(
        self,
        key: str,
        expires_in: int = PRESIGNED_URL_DEFAULT_TTL,
        download_filename: str | None = None,
    ) -> str:
        """URL firmada para `GET`. Default 15 min (CLAUDE.md §3).

        Si `download_filename` está seteado, el navegador fuerza la DESCARGA
        (Content-Disposition: attachment) con ese nombre — se usa para bajar el
        ORIGINAL en alta resolución (no el preview con watermark).
        """
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if download_filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{download_filename}"'
        return self.client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            logger.exception("R2 delete failed for key %s", key)
            raise R2UploadError(str(exc)) from exc

    def delete_many(self, keys: list[str]) -> dict[str, Any]:
        """Batch delete (hasta 1000 keys por request)."""
        if not keys:
            return {"Deleted": []}
        try:
            return self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in keys]},
            )
        except (BotoCoreError, ClientError) as exc:
            logger.exception("R2 batch delete failed for %d keys", len(keys))
            raise R2UploadError(str(exc)) from exc

    def list_keys(self, prefix: str = "") -> list[str]:
        """Lista TODAS las keys del bucket bajo `prefix` (paginado, sin límite)."""
        keys: list[str] = []
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys.extend(obj["Key"] for obj in page.get("Contents", []))
        except (BotoCoreError, ClientError) as exc:
            logger.exception("R2 list_keys failed for prefix %s", prefix)
            raise R2UploadError(str(exc)) from exc
        return keys


# ---------------------------------------------------------------------------
# Helpers de keys
# ---------------------------------------------------------------------------
def key_for_original(event_slug: str, *, ext: str = "jpg", photo_uuid: str | None = None) -> str:
    uid = photo_uuid or uuid.uuid4().hex
    return f"events/{event_slug}/originals/{uid}.{ext}"


def key_for_preview(event_slug: str, photo_uuid: str) -> str:
    return f"events/{event_slug}/previews/{photo_uuid}.webp"


def key_for_thumbnail(event_slug: str, photo_uuid: str) -> str:
    return f"events/{event_slug}/thumbnails/{photo_uuid}.webp"


def key_for_branded(event_slug: str, photo_uuid: str) -> str:
    """Original full-res CON los logos de marca (JPEG). Sólo para eventos con
    `brand_overlay`. Es lo que se descarga en esos eventos."""
    return f"events/{event_slug}/branded/{photo_uuid}.jpg"


def key_for_zip(event_slug: str, *, zip_uuid: str | None = None) -> str:
    uid = zip_uuid or uuid.uuid4().hex
    return f"events/{event_slug}/zips/{uid}.zip"


def key_for_event_cover(event_slug: str) -> str:
    return f"event_covers/{event_slug}.webp"


def key_for_photographer_cover(link_id: int) -> str:
    return f"photographer_covers/{link_id}.webp"


def photo_uuid_from_key(key: str) -> str:
    """Extrae el UUID del filename de un key cualquiera del evento."""
    return key.rsplit("/", 1)[-1].rsplit(".", 1)[0]


# ---------------------------------------------------------------------------
# Singleton helper (lazy)
# ---------------------------------------------------------------------------
_default_storage: R2Storage | None = None


def default_storage() -> R2Storage:
    global _default_storage
    if _default_storage is None:
        _default_storage = R2Storage()
    return _default_storage


def reset_default_storage_for_tests() -> None:
    """Forza recrear el cliente. Llamar después de override de settings en tests."""
    global _default_storage
    _default_storage = None
