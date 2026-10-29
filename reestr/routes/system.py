from __future__ import annotations

from flask import Blueprint, jsonify, send_file

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
