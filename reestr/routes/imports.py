from __future__ import annotations

from flask import Blueprint, jsonify, request, send_file

from ..db import add_history, get_db
from ..domain import normalize_contract, utc_now
from ..importer import ImportFileError, make_import_template, parse_import
from .contracts import STORAGE_FIELDS, operator_name


bp = Blueprint("imports", __name__, url_prefix="/api/import")


def uploaded_file() -> tuple[str, bytes]:
    file = request.files.get("file")
    if file is None or not file.filename:
        raise ImportFileError("Выберите файл Excel")
    # Keep the global backup-upload limit separate from the 15 MiB Excel limit.
    return file.filename, file.read(15 * 1024 * 1024 + 1)


@bp.post("/preview")
def preview_import():
    filename, content = uploaded_file()
    parsed = parse_import(filename, content)
    existing = get_db().execute(
        "SELECT id, imported_at, operator, imported_rows FROM import_log WHERE sha256 = ?",
        (parsed["sha256"],),
    ).fetchone()
    response = dict(parsed)
    response["rows"] = parsed["rows"][:250]
    response["preview_truncated"] = max(0, parsed["total"] - 250)
    response["already_imported"] = dict(existing) if existing else None
    return jsonify(response)


@bp.post("/commit")
def commit_import():
    filename, content = uploaded_file()
    parsed = parse_import(filename, content)
    valid_rows = [item for item in parsed["rows"] if not item["errors"]]
    if not valid_rows:
        return (
            jsonify(
                {
                    "error": "В файле нет корректных строк для импорта",
                    "rows": parsed["rows"][:250],
                }
            ),
            422,
        )

    db = get_db()
    operator = operator_name()
    timestamp = utc_now()
    imported_ids = []
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT id, imported_at, operator FROM import_log WHERE sha256 = ?",
            (parsed["sha256"],),
        ).fetchone()
        if existing:
            db.rollback()
            return (
                jsonify(
                    {
                        "error": "Этот файл уже был импортирован",
                        "code": "already_imported",
                        "previous_import": dict(existing),
                    }
                ),
                409,
            )

        columns = STORAGE_FIELDS + ("created_by", "updated_by", "created_at", "updated_at")
        placeholders = ", ".join("?" for _ in columns)
        for item in valid_rows:
            data = normalize_contract(item["data"])
            values = [data[field] for field in STORAGE_FIELDS] + [
                operator,
                operator,
                timestamp,
                timestamp,
            ]
            cursor = db.execute(
                f"INSERT INTO contracts ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
            contract_id = cursor.lastrowid
            imported_ids.append(contract_id)
            row = db.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
            add_history(db, contract_id, 1, "import", operator, timestamp, dict(row))

        db.execute(
            """
            INSERT INTO import_log
                (filename, sha256, imported_at, operator, total_rows, imported_rows, rejected_rows)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed["filename"],
                parsed["sha256"],
                timestamp,
                operator,
                parsed["total"],
                len(valid_rows),
                parsed["invalid"],
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return (
        jsonify(
            {
                "ok": True,
                "imported": len(valid_rows),
                "rejected": parsed["invalid"],
                "total": parsed["total"],
                "imported_ids": imported_ids,
                "errors": [
                    {"source_row": item["source_row"], "errors": item["errors"]}
                    for item in parsed["rows"]
                    if item["errors"]
                ][:250],
            }
        ),
        201,
    )


@bp.get("/template")
def import_template():
    return send_file(
        make_import_template(),
        as_attachment=True,
        download_name="Shablon_reestra_dogovorov.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
