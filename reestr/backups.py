from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .db import connect_database, init_database
from .maintenance import DatabaseGate, MaintenanceBlocked


logger = logging.getLogger(__name__)
SETTINGS_LOCK = threading.RLock()
REQUIRED_TABLES = {"contracts", "contract_history"}
REQUIRED_CONTRACT_COLUMNS = {"id", "counterparty", "contract_number", "version"}


class BackupError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).replace(microsecond=0).isoformat()


def default_backup_settings(data_dir: str | Path) -> dict[str, Any]:
    root = Path(data_dir)
    return {
        "enabled": False,
        "time": "03:00",
        "directory": str(root / "backups"),
        "retention": 10,
        "updated_at": "",
        "updated_by": "",
        "last_attempt_at": "",
        "last_success_at": "",
        "last_status": "never",
        "last_error": "",
        "last_file": "",
    }


def settings_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "backup_settings.json"


def load_backup_settings(data_dir: str | Path) -> dict[str, Any]:
    data_dir = Path(data_dir)
    with SETTINGS_LOCK:
        result = default_backup_settings(data_dir)
        path = settings_path(data_dir)
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    result.update({key: value for key, value in saved.items() if key in result})
            except (OSError, ValueError, TypeError) as exc:
                result["last_status"] = "error"
                result["last_error"] = f"Не удалось прочитать настройки: {exc}"
        return result


def _write_settings(data_dir: Path, settings: dict[str, Any]) -> None:
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def ensure_directory_writable(directory: str | Path) -> Path:
    path = Path(directory)
    try:
        path.mkdir(parents=True, exist_ok=True)
        marker = path / f".reestr_write_test_{uuid.uuid4().hex}"
        marker.write_bytes(b"ok")
        marker.unlink()
    except OSError as exc:
        raise BackupError(
            f"Каталог недоступен для записи: {path}. Проверьте путь и права учётной записи SYSTEM."
        ) from exc
    return path


def save_backup_settings(
    data_dir: str | Path,
    payload: dict[str, Any],
    operator: str,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    directory = str(payload.get("directory", "")).strip()
    if not directory or len(directory) > 1000 or "\x00" in directory:
        raise BackupError("Укажите каталог для резервных копий")
    path = Path(directory).expanduser()
    if not path.is_absolute():
        raise BackupError("Укажите абсолютный путь, например D:\\Backups\\Reestr или \\\\NAS\\Share\\Reestr")

    backup_time = str(payload.get("time", "")).strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", backup_time):
        raise BackupError("Укажите время в формате ЧЧ:ММ")
    try:
        retention = int(payload.get("retention", 10))
    except (TypeError, ValueError) as exc:
        raise BackupError("Количество хранимых копий должно быть числом") from exc
    if not 1 <= retention <= 100:
        raise BackupError("Количество хранимых копий должно быть от 1 до 100")
    ensure_directory_writable(path)

    with SETTINGS_LOCK:
        settings = load_backup_settings(data_dir)
        settings.update(
            {
                "enabled": bool(payload.get("enabled")),
                "time": backup_time,
                "directory": str(path),
                "retention": retention,
                "updated_at": _iso(),
                "updated_by": operator,
                "last_error": "",
            }
        )
        _write_settings(data_dir, settings)
        return settings


def update_backup_status(data_dir: str | Path, **values: Any) -> dict[str, Any]:
    data_dir = Path(data_dir)
    with SETTINGS_LOCK:
        settings = load_backup_settings(data_dir)
        settings.update({key: value for key, value in values.items() if key in settings})
        _write_settings(data_dir, settings)
        return settings


def next_scheduled_run(settings: dict[str, Any], now: datetime | None = None) -> str | None:
    if not settings.get("enabled"):
        return None
    now = now or _now()
    hour, minute = map(int, settings["time"].split(":"))
    if backup_due(settings, now):
        return _iso(now)
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if scheduled <= now:
        scheduled += timedelta(days=1)
    return _iso(scheduled)


def backup_due(settings: dict[str, Any], now: datetime | None = None) -> bool:
    if not settings.get("enabled"):
        return False
    now = now or _now()
    try:
        hour, minute = map(int, str(settings["time"]).split(":"))
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, TypeError):
        return False
    if now < scheduled:
        return False
    last_attempt_text = str(settings.get("last_attempt_at") or "")
    if not last_attempt_text:
        return True
    try:
        last_attempt = datetime.fromisoformat(last_attempt_text)
    except ValueError:
        return True
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=now.tzinfo)
    return last_attempt < scheduled


def backup_id(path: str | Path) -> str:
    normalized = os.path.normcase(str(Path(path).resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def backup_metadata(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    stat = path.stat()
    return {
        "id": backup_id(path),
        "name": path.name,
        "directory": str(path.parent),
        "location": str(path),
        "size": stat.st_size,
        "created_at": _iso(datetime.fromtimestamp(stat.st_mtime).astimezone()),
    }


def list_backups(data_dir: str | Path) -> list[dict[str, Any]]:
    data_dir = Path(data_dir)
    settings = load_backup_settings(data_dir)
    local = data_dir / "backups"
    configured = Path(settings["directory"])
    candidates: dict[str, Path] = {}
    if local.exists():
        for path in local.rglob("*.db"):
            if path.is_file():
                candidates[backup_id(path)] = path
    if configured.exists() and configured != local:
        for path in configured.glob("*.db"):
            if path.is_file():
                candidates[backup_id(path)] = path
    result = []
    for path in candidates.values():
        try:
            result.append(backup_metadata(path))
        except OSError:
            pass
    result.sort(key=lambda item: item["created_at"], reverse=True)
    return result[:200]


def find_backup(data_dir: str | Path, identifier: str) -> Path:
    for item in list_backups(data_dir):
        if item["id"] == identifier:
            return Path(item["location"])
    raise BackupError("Резервная копия не найдена. Обновите список.")


def validate_backup(path: str | Path) -> None:
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise BackupError("Файл резервной копии не найден")
    if path.stat().st_size < 100:
        raise BackupError("Файл слишком мал и не похож на базу SQLite")
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise BackupError("Файл не является резервной копией SQLite")
    connection = None
    try:
        connection = sqlite3.connect(str(path), timeout=30)
        connection.execute("PRAGMA query_only = ON")
        check = connection.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise BackupError("Проверка целостности базы не пройдена")
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if not REQUIRED_TABLES.issubset(tables):
            raise BackupError("В файле нет таблиц реестра договоров")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(contracts)")}
        if not REQUIRED_CONTRACT_COLUMNS.issubset(columns):
            raise BackupError("Структура базы не соответствует этой версии программы")
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"Повреждённый или неподдерживаемый файл базы: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _unique_target(directory: Path, prefix: str) -> Path:
    stamp = _now().strftime("%Y%m%d_%H%M%S")
    target = directory / f"{prefix}_{stamp}.db"
    counter = 1
    while target.exists():
        target = directory / f"{prefix}_{stamp}_{counter:02d}.db"
        counter += 1
    return target


def prune_backups(directory: str | Path, retention: int) -> None:
    directory = Path(directory)
    files = []
    for pattern in ("reestr_backup_*.db", "reestr_scheduled_*.db"):
        files.extend(path for path in directory.glob(pattern) if path.is_file())
    files = list(set(files))
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files[retention:]:
        try:
            path.unlink()
        except OSError:
            logger.warning("Не удалось удалить старую резервную копию %s", path)


def create_backup(
    data_dir: str | Path,
    *,
    directory: str | Path | None = None,
    prefix: str = "reestr_backup",
    apply_retention: bool = False,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    settings = load_backup_settings(data_dir)
    destination_dir = Path(directory or settings["directory"])
    ensure_directory_writable(destination_dir)
    source_path = data_dir / "data" / "reestr.db"
    if not source_path.exists():
        raise BackupError("Основная база не найдена")
    target = _unique_target(destination_dir, prefix)
    temporary = destination_dir / f".{target.name}.{uuid.uuid4().hex}.tmp"
    source = None
    destination = None
    try:
        source = connect_database(source_path)
        destination = sqlite3.connect(str(temporary))
        source.backup(destination)
        destination.close()
        destination = None
        source.close()
        source = None
        validate_backup(temporary)
        os.replace(temporary, target)
        if apply_retention:
            prune_backups(destination_dir, int(settings["retention"]))
        return backup_metadata(target)
    except Exception as exc:
        if temporary.exists():
            temporary.unlink()
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"Не удалось создать резервную копию: {exc}") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()


def restore_backup(data_dir: str | Path, candidate: str | Path, gate: DatabaseGate) -> dict[str, Any]:
    data_dir = Path(data_dir)
    candidate = Path(candidate)
    validate_backup(candidate)
    database = data_dir / "data" / "reestr.db"
    safety = None
    with gate.maintenance():
        # A standalone pre-restore copy is created before any original file is moved.
        safety = create_backup(
            data_dir,
            directory=data_dir / "backups" / "safety",
            prefix="reestr_before_restore",
        )
        staging = data_dir / "restore-staging" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=True)
        moved: list[tuple[Path, Path]] = []
        temporary = database.parent / f".reestr_restore_{uuid.uuid4().hex}.tmp"
        try:
            for suffix in ("", "-wal", "-shm"):
                original = Path(str(database) + suffix)
                if original.exists():
                    saved = staging / original.name
                    os.replace(original, saved)
                    moved.append((saved, original))
            shutil.copyfile(candidate, temporary)
            validate_backup(temporary)
            os.replace(temporary, database)
            init_database(data_dir)
            connection = connect_database(database)
            try:
                check = connection.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise BackupError("Новая база не прошла проверку после восстановления")
                count = connection.execute("SELECT count(*) FROM contracts").fetchone()[0]
            finally:
                connection.close()
        except Exception as exc:
            for suffix in ("", "-wal", "-shm"):
                new_file = Path(str(database) + suffix)
                if new_file.exists():
                    new_file.unlink()
            if temporary.exists():
                temporary.unlink()
            for saved, original in reversed(moved):
                if saved.exists():
                    os.replace(saved, original)
            logger.exception("Ошибка восстановления; прежняя база возвращена")
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f"Не удалось восстановить базу: {exc}") from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return {
        "ok": True,
        "contracts": count,
        "restored_at": _iso(),
        "safety_backup": safety,
    }


def run_scheduled_backup(data_dir: str | Path, gate: DatabaseGate, now: datetime | None = None) -> dict[str, Any] | None:
    data_dir = Path(data_dir)
    with gate.background():
        settings = load_backup_settings(data_dir)
        now = now or _now()
        if not backup_due(settings, now):
            return None
        update_backup_status(
            data_dir,
            last_attempt_at=_iso(now),
            last_status="running",
            last_error="",
        )
        try:
            result = create_backup(
                data_dir,
                directory=settings["directory"],
                prefix="reestr_scheduled",
                apply_retention=True,
            )
        except Exception as exc:
            update_backup_status(data_dir, last_status="error", last_error=str(exc))
            raise
        update_backup_status(
            data_dir,
            last_status="success",
            last_success_at=_iso(),
            last_error="",
            last_file=result["location"],
        )
        return result


class BackupScheduler:
    def __init__(self, data_dir: str | Path, gate: DatabaseGate) -> None:
        self.data_dir = Path(data_dir)
        self.gate = gate
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="backup-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                run_scheduled_backup(self.data_dir, self.gate)
            except MaintenanceBlocked:
                pass
            except Exception:
                logger.exception("Ошибка планового резервного копирования")
            self.stop_event.wait(30)
