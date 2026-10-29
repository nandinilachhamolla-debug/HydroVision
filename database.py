"""SQLite helpers for HydroVision. Uses Python's built-in sqlite3 (no ORM).

The database file lives in <project>/database/hydrovision.db and is created on first run.
Override the location with the HYDROVISION_DB environment variable (the tests do this).
All data stored here is SIMULATED demo data, not real municipal data.
"""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent          # works from any working directory
DEFAULT_DB_PATH = Path(os.environ.get("HYDROVISION_DB", PROJECT_DIR / "database" / "hydrovision.db"))

# code, name, latitude, longitude, expected flow (L/h), normal pressure (bar)  -- same zones as the website
SEED_ZONES = [
    ("HV-01", "Gachibowli", 17.4401, 78.3489, 6200, 3.2), ("HV-02", "Financial District", 17.4172, 78.3433, 7400, 3.4),
    ("HV-03", "Kokapet", 17.3930, 78.3270, 4800, 3.0), ("HV-04", "Miyapur", 17.4969, 78.3548, 5600, 3.1),
    ("HV-05", "Kukatpally", 17.4948, 78.3996, 8200, 3.3), ("HV-06", "Kondapur", 17.4600, 78.3650, 6000, 3.2),
    ("HV-07", "Manikonda", 17.4050, 78.3790, 5200, 3.0), ("HV-08", "Tellapur", 17.4630, 78.2830, 3900, 2.9),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    latitude REAL NOT NULL, longitude REAL NOT NULL,
    expected_flow_lph REAL NOT NULL, normal_pressure_bar REAL NOT NULL,
    data_source TEXT NOT NULL DEFAULT 'SIMULATED'
);
CREATE TABLE IF NOT EXISTS sensor_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id INTEGER NOT NULL REFERENCES zones(id),
    sim_hour INTEGER NOT NULL, time_label TEXT NOT NULL, recorded_at TEXT NOT NULL,
    flow_lph REAL NOT NULL, pressure_bar REAL NOT NULL, consumption_lph REAL NOT NULL,
    scenario TEXT NOT NULL,
    data_source TEXT NOT NULL DEFAULT 'SIMULATED'
);
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reading_id INTEGER NOT NULL UNIQUE REFERENCES sensor_readings(id),
    raw_score REAL NOT NULL, risk_score INTEGER NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    risk_level TEXT NOT NULL, streak INTEGER NOT NULL, pending INTEGER NOT NULL,
    comp_flow REAL NOT NULL, comp_pressure REAL NOT NULL, comp_mismatch REAL NOT NULL, comp_persistence REAL NOT NULL,
    demand_explained REAL NOT NULL,
    excess_flow_lph REAL NOT NULL CHECK (excess_flow_lph >= 0),
    cause TEXT NOT NULL, action TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'demo_rules (heuristic score, not a probability; trained ML model not connected)'
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id INTEGER NOT NULL REFERENCES zones(id),
    prediction_id INTEGER NOT NULL REFERENCES predictions(id),
    severity TEXT NOT NULL, reason TEXT NOT NULL, est_loss_lph REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ACKNOWLEDGED','RESOLVED')),
    time_label TEXT NOT NULL, created_at TEXT NOT NULL, acknowledged_at TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL REFERENCES alerts(id),
    zone_id INTEGER NOT NULL REFERENCES zones(id),
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','UNDER INVESTIGATION','RESOLVED')),
    time_label TEXT NOT NULL, opened_at TEXT NOT NULL, resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_readings_zone ON sensor_readings(zone_id, id);
"""


@contextmanager
def connect(path=None):
    """One connection per use: commits on success, rolls back on error, always closes."""
    path = Path(path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)       # creates database/ if missing
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path=None):
    """Create tables if missing and insert the seed zones once (INSERT OR IGNORE: no duplicates on restart)."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO zones (code, name, latitude, longitude, expected_flow_lph, normal_pressure_bar) "
            "VALUES (?, ?, ?, ?, ?, ?)", SEED_ZONES)