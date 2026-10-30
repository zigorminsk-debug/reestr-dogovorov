from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from reestr.importer import SAMPLE_HEADERS, parse_import


SAMPLE = Path(__file__).resolve().parents[1] / "Реестр договоров1.xlsx"


def upload(client, path, url, headers=None):
    with path.open("rb") as stream:
        return client.post(url, data={"file": (stream, path.name)}, headers=headers or {}, content_type="multipart/form-data")


def test_repository_sample_preview_and_commit(client, headers):
    parsed = parse_import(SAMPLE.name, SAMPLE.read_bytes())
    assert parsed["total"] == 2
    assert parsed["valid"] == 2
    assert parsed["invalid"] == 0
    first, second = parsed["rows"]
    assert first["data"]["contract_number"] == "К88"
    assert first["data"]["contract_date"] == "2026-03-01"
    assert first["data"]["request_number"] == "1"
    assert first["data"]["request_date"] == "2026-03-04"
    assert first["data"]["invoice_number"] == "К88-1"
    assert first["data"]["invoice_date"] == "2026-03-06"
    assert second["data"]["request_number"] == "без заявки"
    assert second["data"]["avr_amount"] == 1307.82
    assert second["data"]["vat_amount"] == 217.84

    preview = upload(client, SAMPLE, "/api/import/preview")
    assert preview.status_code == 200
    assert preview.json["valid"] == 2
    assert client.get("/api/contracts").json["total"] == 0

    committed = upload(client, SAMPLE, "/api/import/commit", headers)
    assert committed.status_code == 201
    assert committed.json["imported"] == 2
    assert client.get("/api/contracts").json["total"] == 2
    assert client.get("/api/contracts").json["items"][0]["created_by"] == "Иван Тестовый"

    duplicate_preview = upload(client, SAMPLE, "/api/import/preview").json
    assert duplicate_preview["already_imported"] is not None
    duplicate = upload(client, SAMPLE, "/api/import/commit", headers)
    assert duplicate.status_code == 409
    assert duplicate.json["code"] == "already_imported"


def test_import_template(client):
    response = client.get("/api/import/template")
    assert response.status_code == 200
    assert response.data[:2] == b"PK"
    from io import BytesIO

    workbook = load_workbook(BytesIO(response.data))
    assert [cell.value for cell in workbook.active[1]] == SAMPLE_HEADERS
