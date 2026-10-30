from __future__ import annotations

import time

from conftest import TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME
from reestr.auth import initialize_admin


def test_admin_rate_limit_blocks_after_five_failures(anonymous_client):
    remote = {"REMOTE_ADDR": "198.51.100.77"}
    for _ in range(5):
        response = anonymous_client.post(
            "/api/admin/login",
            json={"username": TEST_ADMIN_USERNAME, "password": "bad-password"},
            environ_overrides=remote,
        )
        assert response.status_code == 401
    blocked = anonymous_client.post(
        "/api/admin/login",
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
        environ_overrides=remote,
    )
    assert blocked.status_code == 429
    assert "повтор" in blocked.json["error"].lower()


def test_admin_session_expires_after_twelve_hours(anonymous_client, monkeypatch):
    response = anonymous_client.post(
        "/api/admin/login",
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    assert "Max-Age=43200" in response.headers["Set-Cookie"]
    real_time = time.time
    monkeypatch.setattr("reestr.auth.time.time", lambda: real_time() + 43_201)
    assert anonymous_client.get("/api/admin/session").json["authenticated"] is False
    assert anonymous_client.get("/api/backups").status_code == 401


def test_cyrillic_admin_credentials_are_supported(app, anonymous_client):
    initialize_admin(app.config["DATA_DIR"], "Администратор", "НадёжныйПароль!123", overwrite=True)
    response = anonymous_client.post(
        "/api/admin/login",
        json={"username": "Администратор", "password": "НадёжныйПароль!123"},
    )
    assert response.status_code == 200
    assert response.json["username"] == "Администратор"
    assert anonymous_client.get("/api/backups").status_code == 200


def test_index_contains_admin_and_developer_ui(app):
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'id="admin-button"' in html
    assert 'id="admin-dialog"' in html
    assert 'id="admin-login-form"' in html
    assert 'id="backups-nav" class="nav-item" data-page="backups" hidden' in html
    assert 'id="developer-button"' in html
    assert 'id="developer-dialog"' in html
    assert "Zakharevich Igor" in html
    assert 'href="mailto:ziv@csl.by"' in html
    assert 'href="http://csl.by"' in html
    assert 'href="tel:+375293371412"' in html
