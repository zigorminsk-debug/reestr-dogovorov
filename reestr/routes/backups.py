from __future__ import annotations

import uuid
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file

from ..auth import require_admin
from ..backups import (
    BackupError,
    create_backup,
    find_backup,
    list_backups,
    load_backup_settings,
    next_scheduled_run,
    restore_backup,
    save_backup_settings,
    validate_backup,
)


bp = Blueprint("backups", __name__, url_prefix="/api")
RESTORE_ENDPOINTS = {"backups.restore_selected_backup", "backups.restore_uploaded_backup"}


def data_dir() -> Path:
    return Path(current_app.config["DATA_DIR"])


def database_gate():
    return current_app.extensions["database_gate"]


def require_confirmation(value: object) -> None:
    if str(value or "").strip().upper() != "ВОССТАНОВИТЬ":
        raise BackupError("Для подтверждения введите слово ВОССТАНОВИТЬ")


@bp.get("/backup-settings")
@require_admin
def get_backup_settings():
    settings = load_backup_settings(data_dir())
    settings["next_run_at"] = next_scheduled_run(settings)
    settings["maintenance"] = database_gate().is_maintenance
    return jsonify(settings)


@bp.put("/backup-settings")
@require_admin
def put_backup_settings():
    payload = request.get_json(silent=True) or {}
    settings = save_backup_settings(data_dir(), payload, g.admin_user)
    settings["next_run_at"] = next_scheduled_run(settings)
    return jsonify(settings)


@bp.get("/backups")
@require_admin
def backups_list():
    return jsonify({"items": list_backups(data_dir())})


@bp.post("/backups/create")
@require_admin
def backup_create():
    settings = load_backup_settings(data_dir())
    result = create_backup(
        data_dir(),
        directory=settings["directory"],
        prefix="reestr_backup",
        apply_retention=True,
    )
    return jsonify(result), 201


@bp.get("/backups/download")
@require_admin
def backup_download_existing():
    identifier = request.args.get("id", "")
    path = find_backup(data_dir(), identifier)
    return send_file(path, as_attachment=True, download_name=path.name, mimetype="application/x-sqlite3")


@bp.get("/backup")
@require_admin
def backup_download_new():
    # Kept for the sidebar link and backward compatibility with version 1.0.
    result = create_backup(
        data_dir(),
        directory=data_dir() / "backups",
        prefix="reestr_backup",
        apply_retention=True,
    )
    return send_file(
        result["location"],
        as_attachment=True,
        download_name=result["name"],
        mimetype="application/x-sqlite3",
    )


@bp.post("/backups/restore")
@require_admin
def restore_selected_backup():
    payload = request.get_json(silent=True) or {}
    require_confirmation(payload.get("confirmation"))
    path = find_backup(data_dir(), str(payload.get("backup_id", "")))
    result = restore_backup(data_dir(), path, database_gate())
    result["restored_by"] = g.admin_user
    result["restored_from"] = path.name
    current_app.logger.warning(
        "База восстановлена пользователем %s из %s; страховочная копия %s",
        result["restored_by"], path, result["safety_backup"]["location"],
    )
    return jsonify(result)


@bp.post("/backups/restore-upload")
@require_admin
def restore_uploaded_backup():
    require_confirmation(request.form.get("confirmation"))
    file = request.files.get("file")
    if file is None or not file.filename:
        raise BackupError("Выберите файл резервной копии .db")
    upload_dir = data_dir() / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"restore_{uuid.uuid4().hex}.db"
    try:
        file.save(target)
        validate_backup(target)
        result = restore_backup(data_dir(), target, database_gate())
        result["restored_by"] = g.admin_user
        result["restored_from"] = Path(file.filename).name
        current_app.logger.warning(
            "База восстановлена пользователем %s из загруженного файла %s; страховочная копия %s",
            result["restored_by"], result["restored_from"], result["safety_backup"]["location"],
        )
        return jsonify(result)
    finally:
        target.unlink(missing_ok=True)
