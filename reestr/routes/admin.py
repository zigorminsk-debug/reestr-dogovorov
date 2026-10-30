from __future__ import annotations

import threading
import time

from flask import Blueprint, current_app, jsonify, request

from ..auth import (
    SESSION_COOKIE,
    admin_configured,
    create_session,
    current_admin,
    destroy_session,
    load_admin,
    verify_admin,
)


bp = Blueprint("admin", __name__, url_prefix="/api/admin")
LOGIN_LOCK = threading.RLock()
FAILED_LOGINS: dict[str, list[float]] = {}
MAX_FAILURES = 5
BLOCK_SECONDS = 5 * 60


def login_key() -> str:
    return request.remote_addr or "unknown"


def login_blocked(key: str) -> bool:
    now = time.time()
    with LOGIN_LOCK:
        attempts = [value for value in FAILED_LOGINS.get(key, []) if now - value < BLOCK_SECONDS]
        FAILED_LOGINS[key] = attempts
        return len(attempts) >= MAX_FAILURES


def register_failure(key: str) -> None:
    with LOGIN_LOCK:
        FAILED_LOGINS.setdefault(key, []).append(time.time())


@bp.get("/session")
def session():
    configured = admin_configured(current_app.config["DATA_DIR"])
    username = current_admin(current_app.config["DATA_DIR"]) if configured else None
    return jsonify(
        {
            "configured": configured,
            "authenticated": bool(username),
            "username": username,
        }
    )


@bp.post("/login")
def login():
    if not admin_configured(current_app.config["DATA_DIR"]):
        return (
            jsonify(
                {
                    "error": "Администратор ещё не создан. Выполните установку или --init-admin на сервере.",
                    "code": "admin_not_configured",
                }
            ),
            503,
        )
    key = login_key()
    if login_blocked(key):
        return jsonify({"error": "Слишком много попыток. Повторите через 5 минут."}), 429
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not verify_admin(current_app.config["DATA_DIR"], username, password):
        register_failure(key)
        return jsonify({"error": "Неверный логин или пароль администратора"}), 401
    with LOGIN_LOCK:
        FAILED_LOGINS.pop(key, None)
    admin = load_admin(current_app.config["DATA_DIR"])
    if not admin:
        return jsonify({"error": "Учётная запись администратора была удалена", "code": "admin_not_configured"}), 503
    token, max_age = create_session(username, admin["password_hash"])
    response = jsonify({"ok": True, "authenticated": True, "username": username})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=request.is_secure,
        samesite="Lax",
        path="/",
    )
    return response


@bp.post("/logout")
def logout():
    destroy_session()
    response = jsonify({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
