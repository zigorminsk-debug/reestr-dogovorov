from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from .backups import BackupError
from .db import close_db, default_data_dir, init_database
from .domain import ValidationError
from .importer import ImportFileError
from .maintenance import DatabaseGate, MaintenanceBlocked
from .resources import resource_path


__version__ = "1.1.0"


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(resource_path("reestr/static")),
        static_url_path="/static",
    )
    data_dir = Path((test_config or {}).get("DATA_DIR") or default_data_dir())
    app.config.update(
        DATA_DIR=str(data_dir),
        DATABASE="",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024 * 1024,
        JSON_AS_ASCII=False,
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)
    app.config["DATA_DIR"] = str(Path(app.config["DATA_DIR"]).expanduser().resolve())
    app.config["DATABASE"] = str(init_database(app.config["DATA_DIR"]))
    app.extensions["database_gate"] = DatabaseGate()

    log_dir = Path(app.config["DATA_DIR"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    if not app.debug and not any(isinstance(h, logging.FileHandler) for h in app.logger.handlers):
        handler = logging.FileHandler(log_dir / "server.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler.setLevel(logging.INFO)
        app.logger.addHandler(handler)

    from .routes import backups, contracts, imports, reports, system

    app.register_blueprint(system.bp)
    app.register_blueprint(contracts.bp)
    app.register_blueprint(imports.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(backups.bp)

    @app.before_request
    def pause_during_restore():
        if not request.path.startswith("/api/") or request.endpoint in backups.RESTORE_ENDPOINTS:
            return None
        gate = app.extensions["database_gate"]
        if gate.enter():
            g.database_gate_entered = True
            return None
        return (
            jsonify(
                {
                    "error": "Выполняется восстановление базы. Повторите запрос через несколько секунд.",
                    "code": "maintenance",
                }
            ),
            503,
        )

    def close_and_release(exception):
        close_db(exception)
        if g.pop("database_gate_entered", False):
            app.extensions["database_gate"].exit()

    app.teardown_appcontext(close_and_release)

    @app.errorhandler(ValidationError)
    def validation_error(error: ValidationError):
        return jsonify({"error": "Проверьте поля формы", "fields": error.errors}), 422

    @app.errorhandler(ImportFileError)
    def import_error(error: ImportFileError):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(BackupError)
    def backup_error(error: BackupError):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(MaintenanceBlocked)
    def maintenance_error(error: MaintenanceBlocked):
        return jsonify({"error": str(error), "code": "maintenance"}), 409

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error: RequestEntityTooLarge):
        return jsonify({"error": "Превышен максимальный размер файла: 2 ГБ для базы или 15 МБ для Excel"}), 413

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return app
