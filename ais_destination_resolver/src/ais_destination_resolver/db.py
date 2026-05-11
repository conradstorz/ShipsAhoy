"""SQLite storage for inland AIS destinations and observed matches."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Destination, MatchResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS inland_destinations (
    id INTEGER PRIMARY KEY,
    locode TEXT,
    canonical_name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    state TEXT,
    country_code TEXT NOT NULL DEFAULT 'US',
    waterway TEXT,
    river_mile REAL,
    latitude REAL,
    longitude REAL,
    destination_type TEXT NOT NULL,
    status TEXT,
    source TEXT NOT NULL,
    source_updated TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_inland_destinations_locode ON inland_destinations(locode);
CREATE INDEX IF NOT EXISTS idx_inland_destinations_name ON inland_destinations(canonical_name);
CREATE INDEX IF NOT EXISTS idx_inland_destinations_waterway ON inland_destinations(waterway);
CREATE INDEX IF NOT EXISTS idx_inland_destinations_state ON inland_destinations(state);

CREATE TABLE IF NOT EXISTS ais_destination_matches (
    id INTEGER PRIMARY KEY,
    mmsi TEXT,
    raw_destination TEXT,
    normalized_destination TEXT,
    matched_destination_id INTEGER,
    confidence REAL NOT NULL,
    match_method TEXT NOT NULL,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    observed_latitude REAL,
    observed_longitude REAL,
    observed_at TEXT,
    notes TEXT,
    FOREIGN KEY(matched_destination_id) REFERENCES inland_destinations(id)
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection and set row access by name."""

    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path: Path | str) -> None:
    """Create the database schema if needed."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as connection:
        connection.executescript(SCHEMA)


def destination_from_row(row: sqlite3.Row) -> Destination:
    """Convert a SQLite row into a Destination."""

    aliases = json.loads(row["aliases"] or "[]")
    return Destination(
        id=row["id"],
        locode=row["locode"],
        canonical_name=row["canonical_name"],
        aliases=aliases,
        state=row["state"],
        country_code=row["country_code"],
        waterway=row["waterway"],
        river_mile=row["river_mile"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        destination_type=row["destination_type"],
        status=row["status"],
        source=row["source"],
        source_updated=row["source_updated"],
        is_active=bool(row["is_active"]),
        notes=row["notes"],
    )


def upsert_destinations(db_path: Path | str, destinations: Iterable[Destination]) -> int:
    """Insert or update destinations by LOCODE/canonical-name pair."""

    count = 0
    with connect(db_path) as connection:
        for destination in destinations:
            connection.execute(
                """
                INSERT INTO inland_destinations (
                    locode, canonical_name, aliases, state, country_code, waterway,
                    river_mile, latitude, longitude, destination_type, status, source,
                    source_updated, is_active, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    destination.locode,
                    destination.canonical_name,
                    json.dumps(destination.aliases),
                    destination.state,
                    destination.country_code,
                    destination.waterway,
                    destination.river_mile,
                    destination.latitude,
                    destination.longitude,
                    destination.destination_type,
                    destination.status,
                    destination.source,
                    destination.source_updated,
                    int(destination.is_active),
                    destination.notes,
                ),
            )
            count += 1
    return count


def load_destinations(db_path: Path | str, *, active_only: bool = True) -> list[Destination]:
    """Load destinations from SQLite."""

    query = "SELECT * FROM inland_destinations"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY canonical_name"
    with connect(db_path) as connection:
        rows = connection.execute(query).fetchall()
    return [destination_from_row(row) for row in rows]


def record_match(
    db_path: Path | str,
    match: MatchResult,
    *,
    mmsi: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    observed_at: str | None = None,
) -> None:
    """Persist one observed AIS destination match."""

    matched_destination_id = match.destination.id if match.destination else None
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO ais_destination_matches (
                mmsi, raw_destination, normalized_destination, matched_destination_id,
                confidence, match_method, ambiguous, observed_latitude, observed_longitude,
                observed_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mmsi,
                match.raw_destination,
                match.normalized_destination,
                matched_destination_id,
                match.confidence,
                match.match_method,
                int(match.ambiguous),
                latitude,
                longitude,
                observed_at,
                match.notes,
            ),
        )
