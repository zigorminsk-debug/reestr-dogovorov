from __future__ import annotations

import sqlite3
from datetime import datetime
from io import BytesIO
from pathlib import Path

from reestr.backups import (
    backup_due,
    create_backup,
    load_backup_settings,
    run_scheduled_backup,
    save_backup_settings,
    validate_backup,
)


def test_settings_retention_and_scheduled_backup(app, client, headers, tmp_path):
    custom = tmp_path / "custom-backup-location"
    invalid = client.put(
        "/api/backup-settings",
        json={"enabled": True, "time": "03:00", "directory": "relative/path", "retention": 2},
        headers=headers,
    )
    assert invalid.status_code == 400

    saved = client.put(
        "/api/backup-settings",
        json={"enabled": True, "time": "03:00", "directory": str(custom), "retention": 2},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json["directory"] == str(custom)
    assert saved.json["updated_by"] == "Иван Тестовый"
    assert (Path(app.config["DATA_DIR"]) / "backup_settings.json").exists()

    for _ in range(3):
        create_backup(app.config["DATA_DIR"], apply_retention=True)
    assert len(list(custom.glob("reestr_backup_*.db"))) == 2

    now = datetime.now().astimezone().replace(hour=4, minute=0, second=0, microsecond=0)
    settings = load_backup_settings(app.config["DATA_DIR"])
    assert backup_due(settings, now)
    result = run_scheduled_backup(app.config["DATA_DIR"], app.extensions["database_gate"], now)
    assert result is not None
    assert result["name"].startswith("reestr_scheduled_")
    assert Path(result["location"]).parent == custom
    assert run_scheduled_backup(app.config["DATA_DIR"], app.extensions["database_gate"], now) is None
    assert len(list(custom.glob("*.db"))) == 2
    settings = load_backup_settings(app.config["DATA_DIR"])
    assert settings["last_status"] == "success"
    assert settings["last_success_at"]


def test_restore_from_list_creates_safety_copy_and_keeps_settings(
    app, client, headers, contract_payload, tmp_path
):
    custom = tmp_path / "scheduled"
    save_backup_settings(
        app.config["DATA_DIR"],
        {"enabled": True, "time": "02:30", "directory": str(custom), "retention": 7},
        "Администратор",
    )
    assert client.post("/api/contracts", json=contract_payload, headers=headers).status_code == 201
    created = client.post("/api/backups/create", headers=headers, json={})
    assert created.status_code == 201
    backup_identifier = created.json["id"]

    later = dict(contract_payload, contract_number="Д-После-Копии", counterparty="Новые данные")
    assert client.post("/api/contracts", json=later, headers=headers).status_code == 201
    assert client.get("/api/contracts").json["total"] == 2

    rejected = client.post(
        "/api/backups/restore",
        json={"backup_id": backup_identifier, "confirmation": "да"},
        headers=headers,
    )
    assert rejected.status_code == 400
    assert client.get("/api/contracts").json["total"] == 2

    restored = client.post(
        "/api/backups/restore",
        json={"backup_id": backup_identifier, "confirmation": "ВОССТАНОВИТЬ"},
        headers=headers,
    )
    assert restored.status_code == 200, restored.json
    assert restored.json["contracts"] == 1
    assert restored.json["restored_by"] == "Иван Тестовый"
    assert app.extensions["database_gate"].is_maintenance is False

    items = client.get("/api/contracts").json["items"]
    assert len(items) == 1
    assert items[0]["contract_number"] == contract_payload["contract_number"]
    settings = client.get("/api/backup-settings").json
    assert settings["enabled"] is True
    assert settings["time"] == "02:30"
    assert settings["directory"] == str(custom)

    safety = Path(restored.json["safety_backup"]["location"])
    assert safety.exists()
    validate_backup(safety)
    connection = sqlite3.connect(safety)
    try:
        assert connection.execute("SELECT count(*) FROM contracts").fetchone()[0] == 2
    finally:
        connection.close()


def test_restore_uploaded_downloaded_backup_and_reject_invalid_file(
    client, headers, contract_payload
):
    assert client.post("/api/contracts", json=contract_payload, headers=headers).status_code == 201
    downloaded = client.get("/api/backup")
    assert downloaded.status_code == 200

    later = dict(contract_payload, contract_number="Временный")
    assert client.post("/api/contracts", json=later, headers=headers).status_code == 201
    restored = client.post(
        "/api/backups/restore-upload",
        data={
            "confirmation": "ВОССТАНОВИТЬ",
            "file": (BytesIO(downloaded.data), "reestr_backup_downloaded.db"),
        },
        headers=headers,
        content_type="multipart/form-data",
    )
    assert restored.status_code == 200, restored.json
    assert restored.json["contracts"] == 1
    assert client.get("/api/contracts").json["total"] == 1

    invalid = client.post(
        "/api/backups/restore-upload",
        data={
            "confirmation": "ВОССТАНОВИТЬ",
            "file": (BytesIO(b"not a sqlite database" * 20), "broken.db"),
        },
        headers=headers,
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 400
    assert client.get("/api/contracts").json["total"] == 1


def test_requests_are_paused_during_maintenance(app, client):
    gate = app.extensions["database_gate"]
    with gate.maintenance():
        response = client.get("/api/contracts")
        assert response.status_code == 503
        assert response.json["code"] == "maintenance"
    assert client.get("/api/contracts").status_code == 200
