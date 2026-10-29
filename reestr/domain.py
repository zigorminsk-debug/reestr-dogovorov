from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


DATE_FIELDS = (
    "contract_date",
    "request_date",
    "invoice_date",
    "payment_date",
    "payment_due_date",
    "avr_date",
)

TEXT_FIELDS = {
    "counterparty": 300,
    "country": 120,
    "contract_number": 160,
    "request_number": 200,
    "invoice_number": 200,
    "payment_terms": 300,
    "avr_number": 160,
    "currency": 3,
    "client": 300,
    "notes": 4000,
    "payment_reference": 500,
}

MONEY_FIELDS = ("avr_amount", "vat_amount")
MINOR_FIELDS = {"avr_amount": "avr_amount_minor", "vat_amount": "vat_amount_minor"}


class ValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("Ошибка проверки данных")
        self.errors = errors


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: Any, max_length: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > max_length:
        raise ValueError(f"Не более {max_length} символов")
    return text


def parse_iso_date(value: Any) -> str | None:
    """Convert HTML/Excel/common Russian date values to YYYY-MM-DD."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    if not text:
        return None
    text = text.split("T", 1)[0]
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Ожидается дата ДД.ММ.ГГГГ или ГГГГ-ММ-ДД")


def money_to_minor(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError("Некорректная денежная сумма")
    if isinstance(value, float):
        value = str(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return 0
    if "," in text and "." in text:
        # Support both 1,234.56 and 1.234,56.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Некорректная денежная сумма") from exc
    if abs(amount) > Decimal("999999999999.99"):
        raise ValueError("Слишком большая денежная сумма")
    return int(amount * 100)


def minor_to_number(value: int | None) -> float:
    return float((Decimal(value or 0) / Decimal(100)).quantize(Decimal("0.01")))


def format_money(value: int | float | Decimal | None) -> str:
    if isinstance(value, int):
        amount = Decimal(value) / Decimal(100)
    else:
        amount = Decimal(str(value or 0))
    amount = amount.quantize(Decimal("0.01"))
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def normalize_party_type(value: Any) -> str:
    text = str(value or "К").strip().upper().replace("K", "К").replace("P", "П")
    aliases = {
        "КЛИЕНТ": "К",
        "ЗАКАЗЧИК": "К",
        "ПОДРЯДЧИК": "П",
        "ИСПОЛНИТЕЛЬ": "П",
    }
    text = aliases.get(text, text)
    if text not in {"К", "П"}:
        raise ValueError("Укажите К — клиент или П — подрядчик")
    return text


def normalize_invoice_status(value: Any) -> str:
    text = str(value or "Н").strip().upper().replace("O", "О").replace("H", "Н")
    aliases = {
        "ОПЛАЧЕН": "О",
        "ОПЛАЧЕНО": "О",
        "ДА": "О",
        "НЕ ОПЛАЧЕН": "Н",
        "НЕОПЛАЧЕН": "Н",
        "НЕТ": "Н",
    }
    text = aliases.get(text, text)
    if text not in {"О", "Н"}:
        raise ValueError("Укажите О — оплачен или Н — не оплачен")
    return text


def normalize_contract(payload: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    result: dict[str, Any] = {}

    try:
        result["party_type"] = normalize_party_type(payload.get("party_type"))
    except ValueError as exc:
        errors["party_type"] = str(exc)

    for field, max_length in TEXT_FIELDS.items():
        try:
            result[field] = clean_text(payload.get(field), max_length)
        except ValueError as exc:
            errors[field] = str(exc)
            result[field] = ""

    if not result.get("counterparty"):
        errors["counterparty"] = "Обязательное поле"
    if not result.get("contract_number"):
        errors["contract_number"] = "Обязательное поле"

    currency = str(result.get("currency") or "RUB").upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        errors["currency"] = "Трёхбуквенный код, например RUB, BYN, USD"
    result["currency"] = currency

    try:
        result["invoice_status"] = normalize_invoice_status(payload.get("invoice_status"))
    except ValueError as exc:
        errors["invoice_status"] = str(exc)

    for field in DATE_FIELDS:
        try:
            result[field] = parse_iso_date(payload.get(field))
        except ValueError as exc:
            errors[field] = str(exc)
            result[field] = None

    for field in MONEY_FIELDS:
        try:
            result[MINOR_FIELDS[field]] = money_to_minor(payload.get(field))
        except ValueError as exc:
            errors[field] = str(exc)
            result[MINOR_FIELDS[field]] = 0

    if errors:
        raise ValidationError(errors)
    return result


def payment_state(contract: dict[str, Any], on_date: date | None = None) -> dict[str, Any]:
    today = on_date or date.today()
    status = contract.get("invoice_status") or "Н"
    due_text = contract.get("payment_due_date")
    payment_text = contract.get("payment_date")
    due = date.fromisoformat(due_text) if due_text else None
    paid_at = date.fromisoformat(payment_text) if payment_text else None
    days = 0

    if status == "О":
        if due and paid_at and paid_at > due:
            days = (paid_at - due).days
            return {
                "code": "paid_late",
                "label": "Оплачен с просрочкой",
                "days_overdue": days,
                "is_overdue": True,
                "is_outstanding": False,
            }
        return {
            "code": "paid",
            "label": "Оплачен",
            "days_overdue": 0,
            "is_overdue": False,
            "is_outstanding": False,
        }

    if due and due < today:
        days = (today - due).days
        return {
            "code": "overdue",
            "label": "Просрочено",
            "days_overdue": days,
            "is_overdue": True,
            "is_outstanding": True,
        }

    if due and today <= due <= today + timedelta(days=7):
        return {
            "code": "due_soon",
            "label": "Оплатить в ближайшие 7 дней",
            "days_overdue": 0,
            "is_overdue": False,
            "is_outstanding": True,
        }

    return {
        "code": "unpaid",
        "label": "Не оплачен",
        "days_overdue": 0,
        "is_overdue": False,
        "is_outstanding": True,
    }


def row_to_contract(row: Any, on_date: date | None = None) -> dict[str, Any]:
    contract = dict(row)
    for field, minor_field in MINOR_FIELDS.items():
        contract[field] = minor_to_number(contract.pop(minor_field, 0))
    contract.update(payment_state(contract, on_date))
    return contract


def display_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return value
