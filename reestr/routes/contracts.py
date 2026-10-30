from __future__ import annotations

import json
import sqlite3
from math import ceil
from typing import Any
from urllib.parse import unquote

from flask import Blueprint, jsonify, request

from ..db import add_history, get_db
from ..domain import ValidationError, normalize_contract, row_to_contract, utc_now
from ..query import dashboard_data, load_contracts


bp = Blueprint("contracts", __name__, url_prefix="/api")

STORAGE_FIELDS = (
    "party_type",
    "counterparty",
    "country",
    "contract_number",
    "contract_date",
    "request_number",
    "request_date",
    "invoice_number",
    "invoice_date",
    "invoice_status",
    "payment_date",
    "payment_due_date",
    "payment_terms",
    "avr_number",
    "avr_date",
    "avr_amount_minor",
    "vat_amount_minor",
    "currency",
    "client",
    "notes",
    "payment_reference",
)


def operator_name() -> str:
    # Browsers require ASCII HTTP headers; the UI sends encodeURIComponent(name).
    raw = str(request.headers.get("X-Operator", ""))
    decoded = unquote(raw, encoding="utf-8", errors="replace").strip()
    return decoded[:120] or "Не указан"


def active_contract(contract_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM contracts WHERE id = ? AND deleted_at IS NULL", (contract_id,)
    ).fetchone()


def expected_version(payload: dict[str, Any]) -> int:
    try:
        version = int(payload.get("version"))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"version": "Не указана версия записи"}) from exc
    if version < 1:
        raise ValidationError({"version": "Некорректная версия записи"})
    return version


@bp.get("/contracts")
def list_contracts():
    items = load_contracts(get_db(), request.args)
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(200, max(5, int(request.args.get("page_size", 50))))
    except ValueError:
        page, page_size = 1, 50
    total = len(items)
    start = (page - 1) * page_size
    return jsonify(
        {
            "items": items[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, ceil(total / page_size)),
        }
    )


@bp.get("/contracts/<int:contract_id>")
def get_contract(contract_id: int):
    row = active_contract(contract_id)
    if row is None:
        return jsonify({"error": "Запись не найдена или удалена"}), 404
    return jsonify(row_to_contract(row))


@bp.post("/contracts")
def create_contract():
    payload = request.get_json(silent=True) or {}
    data = normalize_contract(payload)
    operator = operator_name()
    timestamp = utc_now()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        columns = STORAGE_FIELDS + ("created_by", "updated_by", "created_at", "updated_at")
        values = [data[field] for field in STORAGE_FIELDS] + [operator, operator, timestamp, timestamp]
        placeholders = ", ".join("?" for _ in columns)
        cursor = db.execute(
            f"INSERT INTO contracts ({', '.join(columns)}) VALUES ({placeholders})", values
        )
        contract_id = cursor.lastrowid
        row = db.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
        add_history(db, contract_id, 1, "create", operator, timestamp, dict(row))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify(row_to_contract(row)), 201


@bp.put("/contracts/<int:contract_id>")
def update_contract(contract_id: int):
    payload = request.get_json(silent=True) or {}
    version = expected_version(payload)
    data = normalize_contract(payload)
    operator = operator_name()
    timestamp = utc_now()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM contracts WHERE id = ? AND deleted_at IS NULL", (contract_id,)
        ).fetchone()
        if row is None:
            db.rollback()
            return jsonify({"error": "Запись не найдена или удалена"}), 404
        if row["version"] != version:
            current = row_to_contract(row)
            db.rollback()
            return (
                jsonify(
                    {
                        "error": "Запись уже изменена другим пользователем",
                        "code": "version_conflict",
                        "current": current,
                    }
                ),
                409,
            )
        next_version = version + 1
        assignments = ", ".join(f"{field} = ?" for field in STORAGE_FIELDS)
        values = [data[field] for field in STORAGE_FIELDS]
        values.extend([operator, timestamp, next_version, contract_id])
        db.execute(
            f"""
            UPDATE contracts SET {assignments}, updated_by = ?, updated_at = ?, version = ?
            WHERE id = ?
            """,
            values,
        )
        row = db.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
        add_history(db, contract_id, next_version, "update", operator, timestamp, dict(row))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify(row_to_contract(row))


@bp.delete("/contracts/<int:contract_id>")
def delete_contract(contract_id: int):
    payload = request.get_json(silent=True) or {}
    if not payload and request.args.get("version"):
        payload = {"version": request.args["version"]}
    version = expected_version(payload)
    operator = operator_name()
    timestamp = utc_now()
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM contracts WHERE id = ? AND deleted_at IS NULL", (contract_id,)
        ).fetchone()
        if row is None:
            db.rollback()
            return jsonify({"error": "Запись не найдена или удалена"}), 404
        if row["version"] != version:
            current = row_to_contract(row)
            db.rollback()
            return (
                jsonify(
                    {
                        "error": "Запись уже изменена другим пользователем",
                        "code": "version_conflict",
                        "current": current,
                    }
                ),
                409,
            )
        next_version = version + 1
        db.execute(
            """
            UPDATE contracts
            SET deleted_at = ?, updated_at = ?, updated_by = ?, version = ?
            WHERE id = ?
            """,
            (timestamp, timestamp, operator, next_version, contract_id),
        )
        row = db.execute("SELECT * FROM contracts WHERE id = ?", (contract_id,)).fetchone()
        add_history(db, contract_id, next_version, "delete", operator, timestamp, dict(row))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True, "id": contract_id, "version": next_version})


@bp.get("/contracts/<int:contract_id>/history")
def contract_history(contract_id: int):
    rows = get_db().execute(
        """
        SELECT id, contract_id, version, action, actor, changed_at, snapshot_json
        FROM contract_history WHERE contract_id = ? ORDER BY id DESC LIMIT 100
        """,
        (contract_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["snapshot"] = json.loads(item.pop("snapshot_json"))
        result.append(item)
    return jsonify({"items": result})


@bp.get("/meta")
def metadata():
    db = get_db()
    counterparties = [
        row[0]
        for row in db.execute(
            """
            SELECT DISTINCT counterparty FROM contracts
            WHERE deleted_at IS NULL ORDER BY counterparty COLLATE NOCASE
            """
        ).fetchall()
    ]
    currencies = [
        row[0]
        for row in db.execute(
            """
            SELECT DISTINCT currency FROM contracts
            WHERE deleted_at IS NULL ORDER BY currency
            """
        ).fetchall()
    ]
    return jsonify({"counterparties": counterparties, "currencies": currencies})


@bp.get("/dashboard")
def dashboard():
    return jsonify(dashboard_data(get_db()))
