from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_type TEXT NOT NULL DEFAULT 'К' CHECK (party_type IN ('К', 'П')),
    counterparty TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    contract_number TEXT NOT NULL,
    contract_date TEXT,
    request_number TEXT NOT NULL DEFAULT '',
    request_date TEXT,
    invoice_number TEXT NOT NULL DEFAULT '',
    invoice_date TEXT,
    invoice_status TEXT NOT NULL DEFAULT 'Н' CHECK (invoice_status IN ('О', 'Н')),
    payment_date TEXT,
    payment_due_date TEXT,
    payment_terms TEXT NOT NULL DEFAULT '',
    avr_number TEXT NOT NULL DEFAULT '',
    avr_date TEXT,
    avr_amount_minor INTEGER NOT NULL DEFAULT 0,
    vat_amount_minor INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'RUB',
    client TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    payment_reference TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_contracts_counterparty
    ON contracts(counterparty) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_contracts_due_date
    ON contracts(payment_due_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_contracts_contract_number
    ON contracts(contract_number) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_contracts_status
    ON contracts(invoice_status) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS contract_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contract_id INTEGER,
    version INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_contract
    ON contract_history(contract_id, id DESC);

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    operator TEXT NOT NULL,
    total_rows INTEGER NOT NULL,
    imported_rows INTEGER NOT NULL,
    rejected_rows INTEGER NOT NULL
);

PRAGMA user_version = 1;
"""


def default_data_dir() -> Path:
    if os.environ.get("REESTR_DATA_DIR"):
        return Path(os.environ["REESTR_DATA_DIR"]).expanduser().resolve()
    if sys.platform == "win32":
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        return root / "ReestrDogovorov"
    return Path.home() / ".reestr-dogovorov"


def connect_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def init_database(data_dir: str | Path) -> Path:
    root = Path(data_dir)
    database_dir = root / "data"
    database_dir.mkdir(parents=True, exist_ok=True)
    (root / "backups").mkdir(exist_ok=True)
    (root / "exports").mkdir(exist_ok=True)
    path = database_dir / "reestr.db"
    connection = connect_database(path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)
        connection.commit()
    finally:
        connection.close()
    return path


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect_database(current_app.config["DATABASE"])
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def add_history(
    connection: sqlite3.Connection,
    contract_id: int,
    version: int,
    action: str,
    actor: str,
    changed_at: str,
    snapshot: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO contract_history
            (contract_id, version, action, actor, changed_at, snapshot_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            contract_id,
            version,
            action,
            actor,
            changed_at,
            json.dumps(snapshot, ensure_ascii=False, default=str),
        ),
    )
