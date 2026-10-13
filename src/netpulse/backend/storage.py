"""Small SQLite store. Connections are short-lived and database paths are configurable."""
import os
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.models import MeasurementCreate

EXTRA_COLUMNS = {
    "observation_id": "TEXT", "participant_id": "TEXT", "device_id": "TEXT",
    "interface_id": "TEXT", "network_changed": "INTEGER", "target_id": "TEXT",
    "latency_method": "TEXT", "dns_method": "TEXT", "probe_count": "INTEGER",
    "probe_replies": "INTEGER", "throughput_bytes": "INTEGER",
    "collection_interval_seconds": "INTEGER", "collection_errors": "TEXT NOT NULL DEFAULT '[]'",
}


class DuplicateObservation(ValueError):
    pass


def decode(row):
    values = dict(row)
    values["collection_errors"] = json.loads(values["collection_errors"])
    return values


@contextmanager
def connection():
    path = Path(os.environ.get("NETPULSE_DB_PATH", "data/netpulse.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                access_medium TEXT NOT NULL,
                medium_verified INTEGER NOT NULL,
                verification_source TEXT NOT NULL,
                isp TEXT,
                location_category TEXT,
                status TEXT NOT NULL,
                latency_ms REAL,
                packet_loss_pct REAL,
                dns_ms REAL,
                throughput_mbps REAL
            )
        """)
        # Additive migration: preserve existing rows and all legacy metric columns.
        conn.execute("BEGIN IMMEDIATE")
        existing = {row[1] for row in conn.execute("PRAGMA table_info(measurements)")}
        for name, sql_type in EXTRA_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE measurements ADD COLUMN {name} {sql_type}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS observation_identity ON measurements(observation_id) WHERE observation_id IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS measurement_time ON measurements(timestamp DESC)")
        yield conn
        conn.commit()
    finally:
        conn.close()


def create_measurement(payload: MeasurementCreate) -> dict:
    values = payload.model_dump(mode="json")
    # Uniform precision keeps SQLite text ordering correct within a second.
    values["timestamp"] = payload.timestamp.isoformat(timespec="microseconds")
    values["collection_errors"] = json.dumps(values["collection_errors"])
    with connection() as conn:
        if values["observation_id"]:
            previous = conn.execute("SELECT * FROM measurements WHERE observation_id = ?", (values["observation_id"],)).fetchone()
            if previous:
                if any(previous[key] != value for key, value in values.items()):
                    raise DuplicateObservation("Observation ID already belongs to a different payload")
                return decode(previous)
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        cursor = conn.execute(f"INSERT INTO measurements ({columns}) VALUES ({placeholders})", list(values.values()))
        return decode(conn.execute("SELECT * FROM measurements WHERE id = ?", (cursor.lastrowid,)).fetchone())


def list_measurements(limit: int, offset: int) -> dict:
    with connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        rows = conn.execute("SELECT * FROM measurements ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return {"items": [decode(row) for row in rows], "total": total, "limit": limit, "offset": offset}
