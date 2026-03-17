"""Database access layer for ShipsAhoy.

All SQLite operations for all four services are defined here.
Uses WAL journal mode to support concurrent access from multiple processes.

Connection contract:
    Each service opens one connection at startup via init_db() and holds it
    for the process lifetime. WAL mode allows concurrent reads from multiple
    processes with one writer at a time. check_same_thread is not needed
    (one thread per service process).

Usage::

    conn = init_db("/path/to/ships.db")
    upsert_ship(conn, ship_info)
"""

import sqlite3
from typing import Optional

from ships_ahoy.ship_tracker import ShipInfo


_CREATE_SHIPS = """
CREATE TABLE IF NOT EXISTS ships (
    mmsi         INTEGER PRIMARY KEY,
    name         TEXT,
    ship_type    INTEGER,
    flag         TEXT,
    latitude     REAL,
    longitude    REAL,
    speed        REAL,
    heading      REAL,
    course       REAL,
    status       INTEGER,
    destination  TEXT,
    first_seen   DATETIME,
    last_seen    DATETIME,
    visit_count  INTEGER DEFAULT 0,
    enriched     BOOLEAN DEFAULT FALSE
)
"""

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi         INTEGER,
    event_type   TEXT,
    detail       TEXT,
    created_at   DATETIME,
    displayed_at DATETIME
)
"""

_CREATE_ENRICHMENT = """
CREATE TABLE IF NOT EXISTS enrichment (
    mmsi            INTEGER PRIMARY KEY,
    vessel_name     TEXT,
    imo             TEXT,
    call_sign       TEXT,
    flag            TEXT,
    ship_type_label TEXT,
    length_m        REAL,
    build_year      INTEGER,
    owner           TEXT,
    photo_url       TEXT,
    photo_path      TEXT,
    source          TEXT,
    fetched_at      DATETIME,
    fetch_attempts  INTEGER DEFAULT 0
)
"""

_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
)
"""

_CREATE_SHIP_VISITS = """
CREATE TABLE IF NOT EXISTS ship_visits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi        INTEGER,
    arrived_at  DATETIME,
    departed_at DATETIME
)
"""

_DEFAULT_SETTINGS = {
    "home_lat": None,
    "home_lon": None,
    "distance_km": "50",
    "scroll_speed_px_per_sec": "40",
    "stale_ship_hours": "1",
    "enrichment_delay_sec": "10",
    "enrichment_max_attempts": "3",
}


def init_db(path: str) -> sqlite3.Connection:
    """Create all tables, enable WAL mode, seed default settings, and return the connection.

    Parameters
    ----------
    path:
        Filesystem path to the SQLite database file, or ``":memory:"`` for tests.

    Returns
    -------
    sqlite3.Connection
        Open connection with WAL mode enabled and row_factory set to sqlite3.Row.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(_CREATE_SHIPS)
    conn.execute(_CREATE_EVENTS)
    conn.execute(_CREATE_ENRICHMENT)
    conn.execute(_CREATE_SETTINGS)
    conn.execute(_CREATE_SHIP_VISITS)
    for key, value in _DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    return conn


def upsert_ship(conn: sqlite3.Connection, ship: ShipInfo) -> None:
    """Insert or update a ship row from a ShipInfo object.

    Updates all known fields. first_seen is only set on first insert.
    visit_count is managed separately via record_visit/close_visit.
    """
    now = ship.last_seen.isoformat()
    conn.execute(
        """
        INSERT INTO ships (mmsi, name, ship_type, flag, latitude, longitude,
                           speed, heading, course, status, destination,
                           first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mmsi) DO UPDATE SET
            name        = excluded.name,
            ship_type   = excluded.ship_type,
            flag        = excluded.flag,
            latitude    = excluded.latitude,
            longitude   = excluded.longitude,
            speed       = excluded.speed,
            heading     = excluded.heading,
            course      = excluded.course,
            status      = excluded.status,
            destination = excluded.destination,
            last_seen   = excluded.last_seen
        """,
        (
            ship.mmsi, ship.name, ship.ship_type, ship.flag,
            ship.latitude, ship.longitude, ship.speed, ship.heading,
            ship.course, ship.status, ship.destination, now, now,
        ),
    )
    conn.commit()


def get_ship(conn: sqlite3.Connection, mmsi: int) -> Optional[sqlite3.Row]:
    """Return the ships row for *mmsi*, or None if not found."""
    return conn.execute("SELECT * FROM ships WHERE mmsi=?", (mmsi,)).fetchone()


def get_enrichment(conn: sqlite3.Connection, mmsi: int) -> Optional[sqlite3.Row]:
    """Return the enrichment row for *mmsi*, or None if not found."""
    return conn.execute("SELECT * FROM enrichment WHERE mmsi=?", (mmsi,)).fetchone()


def get_unenriched_ships(conn: sqlite3.Connection, max_attempts: int) -> list[int]:
    """Return MMSIs where enriched=FALSE and fetch_attempts < max_attempts."""
    rows = conn.execute(
        """
        SELECT s.mmsi FROM ships s
        LEFT JOIN enrichment e ON s.mmsi = e.mmsi
        WHERE s.enriched = FALSE
          AND COALESCE(e.fetch_attempts, 0) < ?
        """,
        (max_attempts,),
    ).fetchall()
    return [r["mmsi"] for r in rows]


def save_enrichment(conn: sqlite3.Connection, mmsi: int, data: dict) -> None:
    """Write or update an enrichment row and mark ships.enriched=TRUE.

    Parameters
    ----------
    data:
        Dict with any subset of enrichment table columns as keys.
        Only keys present in data are written.
    """
    from datetime import datetime

    # Only these column names are ever written — defined as a tuple of literals
    # so the SQL template is built from a fixed, auditable set, never from caller input.
    _ALLOWED_COLS = (
        "vessel_name", "imo", "call_sign", "flag", "ship_type_label",
        "length_m", "build_year", "owner", "photo_url", "photo_path", "source",
    )
    fields = {k: v for k, v in data.items() if k in _ALLOWED_COLS}
    fields["fetched_at"] = datetime.now().isoformat()

    # Build SQL from the fixed literal column set — no caller-controlled strings in template
    col_names = list(fields.keys())
    placeholders = ", ".join("?" * len(col_names))
    values = list(fields.values())

    existing = conn.execute("SELECT mmsi FROM enrichment WHERE mmsi=?", (mmsi,)).fetchone()
    if existing:
        set_clause = ", ".join(f"{c}=?" for c in col_names)
        conn.execute(
            f"UPDATE enrichment SET {set_clause} WHERE mmsi=?",  # noqa: S608
            (*values, mmsi),
        )
    else:
        col_list = ", ".join(["mmsi"] + col_names)
        conn.execute(
            f"INSERT INTO enrichment ({col_list}) VALUES (?, {placeholders})",  # noqa: S608
            (mmsi, *values),
        )

    conn.execute("UPDATE ships SET enriched=TRUE WHERE mmsi=?", (mmsi,))
    conn.commit()


def _write_event_sql(conn: sqlite3.Connection, mmsi: int, event_type: str, detail: str) -> None:
    """Execute the INSERT for an event row without committing."""
    from datetime import datetime

    conn.execute(
        "INSERT INTO events (mmsi, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
        (mmsi, event_type, detail, datetime.now().isoformat()),
    )


def write_event(
    conn: sqlite3.Connection,
    mmsi: int,
    event_type: str,
    detail: str,
) -> None:
    """Append a new event row with created_at=now() and displayed_at=NULL."""
    _write_event_sql(conn, mmsi, event_type, detail)
    conn.commit()


def get_pending_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all events where displayed_at IS NULL, ordered by created_at ASC."""
    return conn.execute(
        "SELECT * FROM events WHERE displayed_at IS NULL ORDER BY created_at ASC"
    ).fetchall()


def get_recent_events(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """Return the most recent *limit* events ordered by created_at DESC."""
    return conn.execute(
        "SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


def mark_event_displayed(conn: sqlite3.Connection, event_id: int) -> None:
    """Set displayed_at=now() for the given event id."""
    from datetime import datetime

    conn.execute(
        "UPDATE events SET displayed_at=? WHERE id=?",
        (datetime.now().isoformat(), event_id),
    )
    conn.commit()


def get_ships_in_range(
    conn: sqlite3.Connection,
    home_lat: float,
    home_lon: float,
    km: float,
) -> list[sqlite3.Row]:
    """Return ships rows where the haversine distance from (home_lat, home_lon) is <= km.

    Note: distance filtering is done in Python after fetching ships with known
    positions (SQLite cannot compute haversine natively).
    """
    from ships_ahoy.distance import haversine_km

    rows = conn.execute(
        "SELECT * FROM ships WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    ).fetchall()
    return [
        r for r in rows
        if haversine_km(home_lat, home_lon, r["latitude"], r["longitude"]) <= km
    ]


def get_visit_history(conn: sqlite3.Connection, mmsi: int) -> list[sqlite3.Row]:
    """Return all ship_visits rows for *mmsi*, newest first."""
    return conn.execute(
        "SELECT * FROM ship_visits WHERE mmsi=? ORDER BY id DESC", (mmsi,)
    ).fetchall()


def record_visit(conn: sqlite3.Connection, mmsi: int) -> None:
    """Insert an open ship_visits row (departed_at NULL) and increment visit_count."""
    from datetime import datetime

    conn.execute(
        "INSERT INTO ship_visits (mmsi, arrived_at) VALUES (?, ?)",
        (mmsi, datetime.now().isoformat()),
    )
    conn.execute(
        "UPDATE ships SET visit_count = visit_count + 1 WHERE mmsi=?", (mmsi,)
    )
    conn.commit()


def _close_visit_sql(conn: sqlite3.Connection, mmsi: int) -> None:
    """Execute the UPDATE for closing the most recent open visit without committing."""
    from datetime import datetime

    conn.execute(
        """
        UPDATE ship_visits SET departed_at=?
        WHERE id = (
            SELECT id FROM ship_visits
            WHERE mmsi=? AND departed_at IS NULL
            ORDER BY id DESC LIMIT 1
        )
        """,
        (datetime.now().isoformat(), mmsi),
    )


def close_visit(conn: sqlite3.Connection, mmsi: int) -> None:
    """Set departed_at=now() on the most recent open visit row for *mmsi*."""
    _close_visit_sql(conn, mmsi)
    conn.commit()


def mark_ship_departed(conn: sqlite3.Connection, mmsi: int) -> None:
    """Write a DEPARTED event and close the open visit in one atomic transaction.

    Does NOT delete the ships row — history is preserved permanently.
    """
    _write_event_sql(conn, mmsi, "DEPARTED", f"Ship {mmsi} departed")
    _close_visit_sql(conn, mmsi)
    conn.commit()


def increment_fetch_attempts(conn: sqlite3.Connection, mmsi: int) -> None:
    """Increment fetch_attempts for a ship's enrichment row without marking it enriched.

    Creates the enrichment row if it does not exist. Use this on scrape failures
    instead of save_enrichment() to avoid prematurely setting enriched=TRUE.
    """
    existing = conn.execute(
        "SELECT mmsi FROM enrichment WHERE mmsi=?", (mmsi,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE enrichment SET fetch_attempts = fetch_attempts + 1 WHERE mmsi=?",
            (mmsi,),
        )
    else:
        conn.execute(
            "INSERT INTO enrichment (mmsi, fetch_attempts) VALUES (?, 1)", (mmsi,)
        )
    conn.commit()
