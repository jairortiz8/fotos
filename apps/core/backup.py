"""Backup de la base de datos a R2 (Fase 6, ADR 0010).

PRIMARIO: los snapshots automáticos de Railway (ver runbook). Esto es un backup
SECUNDARIO/adicional: `pg_dump` → gzip → R2 bajo `backups/db/`.

Nota prod: `pg_dump` necesita ser de una versión >= a la del server (Railway = pg18).
La imagen Docker trae `postgresql-client`; si el server es más nuevo que el cliente,
`pg_dump` falla y la task lo loggea sin tumbar nada (Railway snapshots cubre el hueco).
"""

from __future__ import annotations

import datetime as dt
import gzip
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.utils import timezone

from apps.photos.storage import R2NotConfiguredError, default_storage

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "backups/db/"
BACKUP_RETENTION_DAYS = 30


def run_db_backup() -> dict[str, object]:
    """Hace `pg_dump`, comprime, sube a R2 y limpia backups viejos. Idempotente."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.warning("backup_db: DATABASE_URL no seteada; salto el backup")
        return {"ok": False, "reason": "no_database_url"}

    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    key = f"{BACKUP_PREFIX}{stamp}.sql.gz"

    with tempfile.TemporaryDirectory() as tmp:
        dump_path = Path(tmp) / f"{stamp}.sql"
        gz_path = Path(tmp) / f"{stamp}.sql.gz"
        try:
            subprocess.run(
                ["pg_dump", db_url, "-f", str(dump_path), "--no-owner", "--no-privileges"],
                check=True,
                capture_output=True,
                timeout=600,
            )
        except FileNotFoundError:
            logger.error("backup_db: pg_dump no está instalado en la imagen")
            return {"ok": False, "reason": "pg_dump_missing"}
        except subprocess.CalledProcessError as exc:
            logger.error(
                "backup_db: pg_dump falló: %s", exc.stderr.decode("utf-8", "replace")[:500]
            )
            return {"ok": False, "reason": "pg_dump_failed"}

        with dump_path.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        size = gz_path.stat().st_size

        try:
            with gz_path.open("rb") as f:
                default_storage().upload(f, key, content_type="application/gzip")
        except R2NotConfiguredError:
            logger.warning("backup_db: R2 no configurado; el dump quedó local y se descarta")
            return {"ok": False, "reason": "r2_not_configured"}

    removed = _prune_old_backups()
    logger.info("backup_db: subido %s (%d bytes), %d backups viejos borrados", key, size, removed)
    return {"ok": True, "key": key, "size_bytes": size, "pruned": removed}


def _prune_old_backups() -> int:
    """Borra backups en R2 más viejos que BACKUP_RETENTION_DAYS (por el stamp del nombre)."""
    cutoff = timezone.now() - dt.timedelta(days=BACKUP_RETENTION_DAYS)
    storage = default_storage()
    old: list[str] = []
    for k in storage.list_keys(prefix=BACKUP_PREFIX):
        stamp = k.removeprefix(BACKUP_PREFIX).split(".")[0]  # YYYYmmdd_HHMMSS
        try:
            when = dt.datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(
                tzinfo=timezone.get_current_timezone()
            )
        except ValueError:
            continue
        if when < cutoff:
            old.append(k)
    if old:
        storage.delete_many(old)
    return len(old)
