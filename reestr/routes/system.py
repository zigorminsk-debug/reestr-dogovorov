from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, send_file

from .. import __version__
from ..db import get_db
from ..domain import utc_now
from ..resources import resource_path


bp = Blueprint("system", __name__)


@bp.get("/")
def index():
    return send_file(resource_path("reestr/static/index.html"))


@bp.get("/api/health")
def health():
    get_db().execute("SELECT 1").fetchone()
    return jsonify(
        {
            "ok": True,
            "version": __version__,
            "server_time": utc_now(),
            "database": "SQLite (общая сетевая база)",
        }
    )


@bp.get("/api/backup")
def backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = Path(current_app.config["DATA_DIR"]) / "backups" / f"reestr_{timestamp}.db"
    source = get_db()
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
    return send_file(
        target,
        as_attachment=True,
        download_name=f"reestr_backup_{timestamp}.db",
        mimetype="application/x-sqlite3",
    )
