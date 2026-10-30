from __future__ import annotations

import json

import pytest

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME
from reestr import create_app
from reestr.auth import (
    SESSION_COOKIE,
    AuthError,
    auth_path,
    initialize_admin,
    load_admin,
    verify_admin,
)


def test_backups_require_admin_but_contracts_remain_open(app, headers, contract_payload):
    anonymous = app.test_client()
    assert anonymous.get("/api/admin/session").json["authenticated"] is False
    assert anonymous.get("/api/contracts").status_code == 200
    created = anonymous.post("/api/contracts", json=contract_payload, headers=headers)
    assert created.status_code == 201
    assert created.json["created_by"] == "Иван Тестовый"

    # A display name, even "admin", is only audit metadata and must not grant access.
    spoofed_operator = {"X-Operator": "admin"}
    protected_requests = [
        anonymous.get("/api/backup-settings", headers=spoofed_operator),
        anonymous.get("/api/backups", headers=spoofed_operator),
        anonymous.get("/api/backup", headers=spoofed_operator),
        anonymous.get("/api/backups/download?id=unknown", headers=spoofed_operator),
        anonymous.post("/api/backups/create", json={}, headers=spoofed_operator),
        anonymous.put("/api/backup-settings", json={}, headers=spoofed_operator),
        anonymous.post("/api/backups/restore", json={}, headers=spoofed_operator),
        anonymous.post("/api/backups/restore-upload", data={}, headers=spoofed_operator),
    ]
    assert all(response.status_code == 401 for response in protected_requests)
    assert all(response.json["code"] == "admin_required" for response in protected_requests)


def test_login_cookie_logout_and_password_hash(app):
    anonymous = app.test_client()
    wrong = anonymous.post(
        "/api/admin/login",
        json={"username": TEST_ADMIN_USERNAME, "password": "wrong-password"},
    )
    assert wrong.status_code == 401

    logged_in = anonymous.post(
        "/api/admin/login",
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
    )
    assert logged_in.status_code == 200
    cookie = logged_in.headers["Set-Cookie"]
    assert SESSION_COOKIE in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie
    assert anonymous.get("/api/admin/session").json["username"] == TEST_ADMIN_USERNAME
    assert anonymous.get("/api/backup-settings").status_code == 200

    assert anonymous.post("/api/admin/logout").status_code == 200
    assert anonymous.get("/api/admin/session").json["authenticated"] is False
    assert anonymous.get("/api/backups").status_code == 401

    auth_text = auth_path(app.config["DATA_DIR"]).read_text(encoding="utf-8")
    assert TEST_ADMIN_PASSWORD not in auth_text
    stored = json.loads(auth_text)
    assert stored["password_hash"].startswith("pbkdf2_sha256$600000$")
    assert stored["username"] == TEST_ADMIN_USERNAME


def test_unconfigured_admin_locks_only_backup_management(tmp_path, contract_payload):
    application = create_app({"TESTING": True, "DATA_DIR": str(tmp_path / "without-admin")})
    anonymous = application.test_client()
    session = anonymous.get("/api/admin/session").json
    assert session == {"configured": False, "authenticated": False, "username": None}
    locked = anonymous.get("/api/backups")
    assert locked.status_code == 503
    assert locked.json["code"] == "admin_not_configured"
    assert anonymous.post("/api/admin/login", json={}).status_code == 503
    assert anonymous.get("/api/contracts").status_code == 200


def test_installer_bootstrap_file_is_removed(tmp_path, monkeypatch):
    from run import initialize_admin_account

    data_dir = tmp_path / "cli-data"
    monkeypatch.setenv("REESTR_DATA_DIR", str(data_dir))
    credentials = tmp_path / "bootstrap-admin.json"
    credentials.write_text(
        # Inno writes ASCII-only JSON with Unicode escaped as \uXXXX.
        json.dumps({"username": "Администратор", "password": "SetupПароль!3"}),
        encoding="utf-8",
    )
    assert "\\u0410" in credentials.read_text(encoding="ascii")
    result = initialize_admin_account(str(credentials), False)
    assert result["username"] == "Администратор"
    assert not credentials.exists()
    assert verify_admin(data_dir, "Администратор", "SetupПароль!3")


def test_admin_reset_and_duplicate_protection(app, client):
    with pytest.raises(AuthError):
        initialize_admin(app.config["DATA_DIR"], "another", "AnotherPassword!1")
    initialize_admin(
        app.config["DATA_DIR"],
        "newadmin",
        "NewStrongPassword!2",
        overwrite=True,
    )
    assert load_admin(app.config["DATA_DIR"])["username"] == "newadmin"
    assert verify_admin(app.config["DATA_DIR"], "newadmin", "NewStrongPassword!2")
    assert not verify_admin(app.config["DATA_DIR"], TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)
    assert client.get("/api/backups").status_code == 401
    assert client.get("/api/admin/session").json["authenticated"] is False
