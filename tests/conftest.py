from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

import pytest

from reestr import create_app
from reestr.auth import initialize_admin


TEST_ADMIN_USERNAME = "admin"
TEST_ADMIN_PASSWORD = "TestPassword!123"


@pytest.fixture()
def app(tmp_path):
    application = create_app({"TESTING": True, "DATA_DIR": str(tmp_path / "separate-data")})
    initialize_admin(application.config["DATA_DIR"], TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)
    yield application


@pytest.fixture()
def client(app):
    test_client = app.test_client()
    response = test_client.post(
        "/api/admin/login",
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return test_client


@pytest.fixture()
def anonymous_client(app):
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
