"""Settings table wrapper for ShipsAhoy.

Re-reads the database on every property access so that changes made
via the web portal take effect immediately without restarting services.

Usage::

    conn = init_db("/path/to/ships.db")
    cfg = Config(conn)
    lat, lon = cfg.home_location or (None, None)
    threshold = cfg.distance_km
"""

import sqlite3
from typing import Optional


class Config:
    """Provides typed access to the settings table.

    Each property re-reads from the database on every access.
    No caching — this ensures web portal changes propagate immediately.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Read a setting by key. Returns *default* if the key is absent or NULL."""
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return default
        return row[0] if row[0] is not None else default

    def set(self, key: str, value: str) -> None:
        """Write a setting. Inserts or replaces the row."""
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    @property
    def home_location(self) -> Optional[tuple]:
        """Return (lat, lon) when both are set, otherwise None.

        When None, callers should log a warning and treat all ships as noteworthy.
        """
        lat = self.get("home_lat")
        lon = self.get("home_lon")
        if lat is None or lon is None:
            return None
        return (float(lat), float(lon))

    @property
    def distance_km(self) -> float:
        """Return the noteworthy-ship distance threshold in kilometres."""
        return float(self.get("distance_km", "50"))

    @property
    def stale_ship_hours(self) -> float:
        """Return hours before an absent ship fires a DEPARTED event."""
        return float(self.get("stale_ship_hours", "1"))

    @property
    def scroll_speed(self) -> float:
        """Return LED ticker scroll speed in pixels per second."""
        return float(self.get("scroll_speed_px_per_sec", "40"))

    @property
    def enrichment_delay_sec(self) -> float:
        """Return seconds to wait between enrichment scrape requests."""
        return float(self.get("enrichment_delay_sec", "10"))

    @property
    def enrichment_max_attempts(self) -> int:
        """Return max scrape attempts per ship before permanently skipping."""
        return int(self.get("enrichment_max_attempts", "3"))
