from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

import pytest

from reestr import create_app


@pytest.fixture()
def app(tmp_path):
    application = create_app({"TESTING": True, "DATA_DIR": str(tmp_path / "separate-data")})
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def headers():
    return {"X-Operator": quote("Иван Тестовый")}


@pytest.fixture()
def contract_payload():
    return {
        "party_type": "К",
        "counterparty": "ООО «Пример»",
        "country": "РФ",
        "contract_number": "Д-101",
        "contract_date": "2026-01-15",
        "request_number": "З-15",
        "request_date": "2026-01-16",
        "invoice_number": "С-20",
        "invoice_date": "2026-01-20",
        "invoice_status": "Н",
        "payment_due_date": (date.today() + timedelta(days=10)).isoformat(),
        "payment_terms": "",
        "avr_number": "А-20",
        "avr_date": "2026-01-20",
        "avr_amount": "12345.67",
        "vat_amount": "2057.61",
        "currency": "RUB",
        "client": "Клиент А",
        "notes": "Тестовая запись",
        "payment_reference": "",
    }
