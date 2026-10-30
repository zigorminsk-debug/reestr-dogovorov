from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any, Mapping

from .domain import row_to_contract


DATE_FILTER_FIELDS = {
    "contract_date",
    "invoice_date",
    "payment_date",
    "payment_due_date",
    "avr_date",
}

SORT_FIELDS = {
    "id",
    "counterparty",
    "contract_number",
    "contract_date",
    "invoice_number",
    "payment_due_date",
    "payment_date",
    "avr_amount",
    "currency",
    "updated_at",
}


def load_contracts(
    db: sqlite3.Connection,
    filters: Mapping[str, Any] | None = None,
    *,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    filters = filters or {}
    where = "" if include_deleted else "WHERE deleted_at IS NULL"
    rows = db.execute(f"SELECT * FROM contracts {where}").fetchall()
    items = [row_to_contract(row) for row in rows]

    query = str(filters.get("q", "")).strip().casefold()
    if query:
        searchable = (
            "counterparty",
            "country",
            "contract_number",
            "request_number",
            "invoice_number",
            "avr_number",
            "client",
            "notes",
            "payment_reference",
        )
        items = [
            item
            for item in items
            if any(query in str(item.get(field) or "").casefold() for field in searchable)
        ]

    for field in ("counterparty", "currency", "party_type"):
        value = str(filters.get(field, "")).strip()
        if value:
            items = [item for item in items if item.get(field) == value]

    status = str(filters.get("status", "")).strip()
    if status == "paid":
        items = [item for item in items if item["invoice_status"] == "О"]
    elif status == "unpaid":
        items = [item for item in items if item["invoice_status"] == "Н"]
    elif status == "overdue":
        items = [item for item in items if item["is_overdue"]]
    elif status == "overdue_unpaid":
        items = [item for item in items if item["code"] == "overdue"]
    elif status == "paid_late":
        items = [item for item in items if item["code"] == "paid_late"]
    elif status == "due_soon":
        items = [item for item in items if item["code"] == "due_soon"]

    date_field = str(filters.get("date_field", "contract_date"))
    if date_field not in DATE_FILTER_FIELDS:
        date_field = "contract_date"
    date_from = str(filters.get("date_from", "")).strip()
    date_to = str(filters.get("date_to", "")).strip()
    if date_from:
        items = [item for item in items if item.get(date_field) and item[date_field] >= date_from]
    if date_to:
        items = [item for item in items if item.get(date_field) and item[date_field] <= date_to]

    sort = str(filters.get("sort", "updated_at"))
    if sort not in SORT_FIELDS:
        sort = "updated_at"
    direction = str(filters.get("direction", "desc")).lower()
    reverse = direction != "asc"

    def sort_key(item: dict[str, Any]) -> tuple[bool, Any]:
        value = item.get(sort)
        # Empty dates and numbers are always placed after populated values.
        return (value is None or value == "", value)

    items.sort(key=sort_key, reverse=reverse)
    return items


def dashboard_data(db: sqlite3.Connection) -> dict[str, Any]:
    items = load_contracts(db)
    today = date.today().isoformat()
    currencies = sorted({item["currency"] for item in items})
    totals = []
    for currency in currencies:
        group = [item for item in items if item["currency"] == currency]
        totals.append(
            {
                "currency": currency,
                "amount": round(sum(item["avr_amount"] for item in group), 2),
                "outstanding": round(
                    sum(item["avr_amount"] for item in group if item["is_outstanding"]), 2
                ),
                "overdue": round(
                    sum(item["avr_amount"] for item in group if item["code"] == "overdue"), 2
                ),
            }
        )

    upcoming = sorted(
        (
            item
            for item in items
            if item["invoice_status"] == "Н"
            and item.get("payment_due_date")
            and item["payment_due_date"] >= today
        ),
        key=lambda item: item["payment_due_date"],
    )[:8]
    overdue = sorted(
        (item for item in items if item["code"] == "overdue"),
        key=lambda item: item["payment_due_date"] or "",
    )[:8]
    history = [
        dict(row)
        for row in db.execute(
            """
            SELECT h.id, h.contract_id, h.version, h.action, h.actor, h.changed_at,
                   json_extract(h.snapshot_json, '$.counterparty') AS counterparty,
                   json_extract(h.snapshot_json, '$.contract_number') AS contract_number
            FROM contract_history h
            ORDER BY h.id DESC LIMIT 8
            """
        ).fetchall()
    ]
    return {
        "totals": {
            "contracts": len(items),
            "counterparties": len({item["counterparty"] for item in items}),
            "unpaid": sum(item["invoice_status"] == "Н" for item in items),
            "overdue": sum(item["code"] == "overdue" for item in items),
            "paid_late": sum(item["code"] == "paid_late" for item in items),
            "due_soon": sum(item["code"] == "due_soon" for item in items),
        },
        "amounts": totals,
        "upcoming": upcoming,
        "overdue_items": overdue,
        "history": history,
    }
