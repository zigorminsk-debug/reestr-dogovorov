from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import current_app, g, jsonify, request


AUTH_FILENAME = "auth.json"
SESSION_COOKIE = "reestr_admin_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
PBKDF2_ITERATIONS = 600_000
SESSIONS: dict[str, tuple[str, float, str]] = {}
SESSION_LOCK = threading.RLock()


class AuthError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def auth_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / AUTH_FILENAME


def validate_credentials(username: Any, password: Any) -> tuple[str, str]:
    username = str(username or "").strip()
    password = str(password or "")
    if not 3 <= len(username) <= 64 or any(ord(char) < 32 for char in username):
        raise AuthError("Логин администратора должен содержать от 3 до 64 символов")
    if not 8 <= len(password) <= 256:
        raise AuthError("Пароль администратора должен содержать от 8 до 256 символов")
    return username, password


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii")
    return f"pbkdf2_sha256${iterations}${encode(salt)}${encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if not 100_000 <= iterations <= 5_000_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False


def load_admin(data_dir: str | Path) -> dict[str, Any] | None:
    path = auth_path(data_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None
        username = value.get("username")
        password_hash = value.get("password_hash")
        if not isinstance(username, str) or not username or not isinstance(password_hash, str) or not password_hash:
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def admin_configured(data_dir: str | Path) -> bool:
    return load_admin(data_dir) is not None


def _write_admin(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if temporary.exists():
            temporary.unlink()


def initialize_admin(
    data_dir: str | Path,
    username: str,
    password: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    username, password = validate_credentials(username, password)
    path = auth_path(data_dir)
    if path.exists() and not overwrite:
        raise AuthError("Администратор уже создан. Для смены пароля используйте --reset-admin.")
    previous = load_admin(data_dir)
    timestamp = _now()
    value = {
        "version": 1,
        "username": username,
        "password_hash": hash_password(password),
        "created_at": previous.get("created_at", timestamp) if previous else timestamp,
        "updated_at": timestamp,
    }
    _write_admin(path, value)
    with SESSION_LOCK:
        SESSIONS.clear()
    return {"username": username, "created_at": value["created_at"], "updated_at": timestamp}


def _text_equal(left: str, right: str) -> bool:
    # hmac.compare_digest rejects non-ASCII str values, while admin names may be Cyrillic.
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def verify_admin(data_dir: str | Path, username: str, password: str) -> bool:
    admin = load_admin(data_dir)
    if not admin:
        return False
    # Perform the same password derivation even for an unknown username.
    password_ok = verify_password(str(password or ""), admin["password_hash"])
    username_ok = _text_equal(str(username or "").strip(), admin["username"])
    return password_ok and username_ok


def create_session(username: str, password_hash: str) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    expires = time.time() + SESSION_TTL_SECONDS
    with SESSION_LOCK:
        now = time.time()
        for key, (_user, expiry, _password_hash) in list(SESSIONS.items()):
            if expiry <= now:
                SESSIONS.pop(key, None)
        SESSIONS[token] = (username, expires, password_hash)
    return token, SESSION_TTL_SECONDS


def current_admin(data_dir: str | Path) -> str | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return None
    with SESSION_LOCK:
        session = SESSIONS.get(token)
        if not session:
            return None
        username, expires, password_hash = session
        admin = load_admin(data_dir)
        if (
            expires <= time.time()
            or not admin
            or not _text_equal(username, admin["username"])
            or not _text_equal(password_hash, admin["password_hash"])
        ):
            # Expire sessions immediately after an external administrator reset too.
            SESSIONS.pop(token, None)
            return None
        return username


def destroy_session() -> None:
    token = request.cookies.get(SESSION_COOKIE, "")
    with SESSION_LOCK:
        SESSIONS.pop(token, None)


def require_admin(function: Callable) -> Callable:
    @wraps(function)
    def wrapped(*args, **kwargs):
        data_dir = current_app.config["DATA_DIR"]
        if not admin_configured(data_dir):
            return (
                jsonify(
                    {
                        "error": "Администратор не настроен. Запустите установщик или инициализацию --init-admin.",
                        "code": "admin_not_configured",
                    }
                ),
                503,
            )
        username = current_admin(data_dir)
        if not username:
            return (
                jsonify({"error": "Требуется вход администратора", "code": "admin_required"}),
                401,
            )
        g.admin_user = username
        return function(*args, **kwargs)

    return wrapped
