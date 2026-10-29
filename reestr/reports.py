from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any


REPORT_TYPES = {
    "counterparties": "Отчёт по контрагентам",
    "payments": "Отчёт по срокам оплаты",
    "overdue": "Отчёт по просроченным оплатам",
}


def _sum(items: list[dict[str, Any]], field: str = "avr_amount") -> float:
    return float(sum((Decimal(str(item.get(field) or 0)) for item in items), Decimal(0)))


def _totals(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for currency in sorted({item["currency"] for item in items}):
        group = [item for item in items if item["currency"] == currency]
        result.append(
            {
                "currency": currency,
                "amount": _sum(group),
                "outstanding": _sum([item for item in group if item["is_outstanding"]]),
                "overdue": _sum([item for item in group if item["code"] == "overdue"]),
            }
        )
    return result


def _counterparties(items: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[(item["counterparty"], item["currency"])].append(item)

    rows = []
    for (counterparty, currency), group in groups.items():
        overdue = [item for item in group if item["code"] == "overdue"]
        rows.append(
            {
                "counterparty": counterparty,
                "currency": currency,
                "contract_count": len(group),
                "avr_amount": _sum(group),
                "vat_amount": _sum(group, "vat_amount"),
                "paid_amount": _sum([item for item in group if item["invoice_status"] == "О"]),
                "outstanding_amount": _sum(
                    [item for item in group if item["invoice_status"] == "Н"]
                ),
                "overdue_count": len(overdue),
                "overdue_amount": _sum(overdue),
                "paid_late_count": sum(item["code"] == "paid_late" for item in group),
            }
        )
    rows.sort(key=lambda row: (row["counterparty"].casefold(), row["currency"]))
    columns = [
        {"key": "counterparty", "title": "Контрагент", "kind": "text", "width": 28},
        {"key": "currency", "title": "Валюта", "kind": "text", "width": 8},
        {"key": "contract_count", "title": "Записей", "kind": "integer", "width": 9},
        {"key": "avr_amount", "title": "Сумма АВР", "kind": "money", "width": 15},
        {"key": "vat_amount", "title": "В том числе НДС", "kind": "money", "width": 15},
        {"key": "paid_amount", "title": "Оплачено", "kind": "money", "width": 15},
        {"key": "outstanding_amount", "title": "Остаток", "kind": "money", "width": 15},
        {"key": "overdue_count", "title": "Просрочено, шт.", "kind": "integer", "width": 12},
        {"key": "overdue_amount", "title": "Просроченная сумма", "kind": "money", "width": 16},
        {"key": "paid_late_count", "title": "Оплачено позже срока, шт.", "kind": "integer", "width": 14},
    ]
    return {"columns": columns, "rows": rows}


def _payment_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "counterparty": item["counterparty"],
        "contract_number": item["contract_number"],
        "invoice_number": item["invoice_number"],
        "payment_due_date": item["payment_due_date"],
        "payment_terms": item["payment_terms"],
        "payment_date": item["payment_date"],
        "avr_amount": item["avr_amount"],
        "currency": item["currency"],
        "status_label": item["label"],
        "days_overdue": item["days_overdue"],
        "payment_reference": item["payment_reference"],
    }


def _payment_columns() -> list[dict[str, Any]]:
    return [
        {"key": "counterparty", "title": "Контрагент", "kind": "text", "width": 24},
        {"key": "contract_number", "title": "Договор", "kind": "text", "width": 15},
        {"key": "invoice_number", "title": "Счёт", "kind": "text", "width": 16},
        {"key": "payment_due_date", "title": "Срок оплаты", "kind": "date", "width": 13},
        {"key": "payment_terms", "title": "Условия оплаты", "kind": "text", "width": 16},
        {"key": "payment_date", "title": "Дата оплаты", "kind": "date", "width": 13},
        {"key": "avr_amount", "title": "Сумма АВР", "kind": "money", "width": 14},
        {"key": "currency", "title": "Валюта", "kind": "text", "width": 8},
        {"key": "status_label", "title": "Статус", "kind": "text", "width": 20},
        {"key": "days_overdue", "title": "Дней просрочки", "kind": "integer", "width": 11},
        {"key": "payment_reference", "title": "Платёжное поручение", "kind": "text", "width": 24},
    ]


def _payments(items: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [_payment_row(item) for item in items]
    rows.sort(
        key=lambda row: (
            not bool(row["payment_due_date"]),
            row["payment_due_date"] or "",
            row["counterparty"].casefold(),
        )
    )
    return {"columns": _payment_columns(), "rows": rows}


def _overdue(items: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [_payment_row(item) for item in items]
    rows.sort(key=lambda row: (-row["days_overdue"], row["counterparty"].casefold()))
    return {"columns": _payment_columns(), "rows": rows}


def build_report(report_type: str, items: list[dict[str, Any]], filters: dict[str, Any]) -> dict[str, Any]:
    if report_type not in REPORT_TYPES:
        raise KeyError(report_type)
    builders = {
        "counterparties": _counterparties,
        "payments": _payments,
        "overdue": _overdue,
    }
    content = builders[report_type](items)
    return {
        "type": report_type,
        "title": REPORT_TYPES[report_type],
        "generated_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "columns": content["columns"],
        "rows": content["rows"],
        "row_count": len(content["rows"]),
        "source_count": len(items),
        "totals": _totals(items),
        "filters": {
            key: filters.get(key, "")
            for key in ("counterparty", "currency", "date_from", "date_to", "status")
            if filters.get(key)
        },
    }
