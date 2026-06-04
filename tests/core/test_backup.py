"""Tests del backup de DB a R2 (Fase 6). pg_dump y R2 mockeados."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command


def _fake_pg_dump(cmd: list[str], **kwargs: object) -> MagicMock:
    """Simula pg_dump escribiendo el archivo de salida."""
    out = cmd[cmd.index("-f") + 1]
    Path(out).write_text("-- fake dump\n")
    return MagicMock(returncode=0)


@pytest.fixture
def mock_backup_storage():  # type: ignore[no-untyped-def]
    with patch("apps.core.backup.default_storage") as factory:
        store = MagicMock()
        store.list_keys.return_value = []
        factory.return_value = store
        yield store


@pytest.mark.django_db
def test_run_db_backup_uploads_to_r2(mock_backup_storage: MagicMock) -> None:
    from apps.core.backup import run_db_backup

    with patch("apps.core.backup.subprocess.run", side_effect=_fake_pg_dump):
        result = run_db_backup()
    assert result["ok"] is True
    assert str(result["key"]).startswith("backups/db/")
    mock_backup_storage.upload.assert_called_once()


@pytest.mark.django_db
def test_run_db_backup_handles_missing_pg_dump(mock_backup_storage: MagicMock) -> None:
    from apps.core.backup import run_db_backup

    with patch("apps.core.backup.subprocess.run", side_effect=FileNotFoundError):
        result = run_db_backup()
    assert result == {"ok": False, "reason": "pg_dump_missing"}
    mock_backup_storage.upload.assert_not_called()


@pytest.mark.django_db
def test_backup_task_delegates_to_run(mock_backup_storage: MagicMock) -> None:
    from apps.core.tasks import backup_database

    with patch("apps.core.backup.subprocess.run", side_effect=_fake_pg_dump):
        result = backup_database.apply().get()
    assert result["ok"] is True


@pytest.mark.django_db
def test_backup_command_runs(mock_backup_storage: MagicMock) -> None:
    with patch("apps.core.backup.subprocess.run", side_effect=_fake_pg_dump):
        call_command("backup_db")  # no debe lanzar excepción
    mock_backup_storage.upload.assert_called_once()


@pytest.mark.django_db
def test_backup_prunes_old_backups(mock_backup_storage: MagicMock) -> None:
    # Un backup viejo (2020) en R2 → se borra al podar.
    mock_backup_storage.list_keys.return_value = ["backups/db/20200101_000000.sql.gz"]
    from apps.core.backup import run_db_backup

    with patch("apps.core.backup.subprocess.run", side_effect=_fake_pg_dump):
        result = run_db_backup()
    assert result["pruned"] == 1
    mock_backup_storage.delete_many.assert_called_once()


@pytest.mark.django_db
def test_backup_handles_r2_not_configured() -> None:
    """Si R2 no está configurado, el backup no rompe: reporta el motivo."""
    from apps.core.backup import run_db_backup
    from apps.photos.storage import R2NotConfiguredError

    with (
        patch("apps.core.backup.subprocess.run", side_effect=_fake_pg_dump),
        patch("apps.core.backup.default_storage") as factory,
    ):
        store = MagicMock()
        store.upload.side_effect = R2NotConfiguredError("sin credenciales")
        factory.return_value = store
        result = run_db_backup()
    assert result == {"ok": False, "reason": "r2_not_configured"}
