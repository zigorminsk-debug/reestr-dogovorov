from __future__ import annotations

from datetime import date, timedelta


def test_health_static_and_separate_database(app, client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert "separate-data" in app.config["DATABASE"]
    assert app.config["DATABASE"].endswith("reestr.db")
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_crud_history_and_optimistic_concurrency(client, headers, contract_payload):
    created = client.post("/api/contracts", json=contract_payload, headers=headers)
    assert created.status_code == 201
    item = created.json
    assert item["version"] == 1
    assert item["avr_amount"] == 12345.67
    assert item["created_by"] == "Иван Тестовый"

    update = dict(contract_payload, version=1, notes="Изменено вторым пользователем")
    updated = client.put(f"/api/contracts/{item['id']}", json=update, headers=headers)
    assert updated.status_code == 200
    assert updated.json["version"] == 2
    assert updated.json["notes"] == "Изменено вторым пользователем"

    stale = client.put(f"/api/contracts/{item['id']}", json=dict(contract_payload, version=1), headers=headers)
    assert stale.status_code == 409
    assert stale.json["code"] == "version_conflict"
    assert stale.json["current"]["version"] == 2
    assert stale.json["current"]["notes"] == "Изменено вторым пользователем"

    wrong_delete = client.delete(f"/api/contracts/{item['id']}", json={"version": 1}, headers=headers)
    assert wrong_delete.status_code == 409
    deleted = client.delete(f"/api/contracts/{item['id']}", json={"version": 2}, headers=headers)
    assert deleted.status_code == 200
    assert client.get(f"/api/contracts/{item['id']}").status_code == 404

    history = client.get(f"/api/contracts/{item['id']}/history").json["items"]
    assert [entry["action"] for entry in history] == ["delete", "update", "create"]
    assert all(entry["actor"] == "Иван Тестовый" for entry in history)


def test_validation_and_filters(client, headers, contract_payload):
    invalid = dict(contract_payload, counterparty="", contract_number="", currency="РУБ")
    response = client.post("/api/contracts", json=invalid, headers=headers)
    assert response.status_code == 422
    assert set(response.json["fields"]) >= {"counterparty", "contract_number", "currency"}

    for index, (number, status) in enumerate((("Д-1", "Н"), ("Д-2", "О"))):
        payload = dict(
            contract_payload,
            contract_number=number,
            invoice_status=status,
            counterparty="Первый" if index == 0 else "Второй",
        )
        assert client.post("/api/contracts", json=payload, headers=headers).status_code == 201
    filtered = client.get("/api/contracts?status=unpaid&counterparty=Первый").json
    assert filtered["total"] == 1
    assert filtered["items"][0]["contract_number"] == "Д-1"
    assert client.get("/api/contracts?q=Д-2").json["total"] == 1


def test_overdue_and_paid_late_states(client, headers, contract_payload):
    today = date.today()
    records = [
        ("Просрочен", "Н", (today - timedelta(days=5)).isoformat(), None, "overdue"),
        ("Оплачен поздно", "О", (today - timedelta(days=20)).isoformat(), (today - timedelta(days=10)).isoformat(), "paid_late"),
        ("Оплачен вовремя", "О", (today - timedelta(days=20)).isoformat(), (today - timedelta(days=21)).isoformat(), "paid"),
    ]
    for number, status, due, paid, expected in records:
        payload = dict(contract_payload, contract_number=number, invoice_status=status, payment_due_date=due, payment_date=paid)
        created = client.post("/api/contracts", json=payload, headers=headers).json
        assert created["code"] == expected
    dashboard = client.get("/api/dashboard").json
    assert dashboard["totals"]["overdue"] == 1
    assert dashboard["totals"]["paid_late"] == 1
    assert client.get("/api/contracts?status=overdue").json["total"] == 2
    assert client.get("/api/contracts?status=overdue_unpaid").json["total"] == 1
