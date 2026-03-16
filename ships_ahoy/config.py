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
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:
        """Write a setting. Inserts or replaces the row."""
        raise NotImplementedError

    @property
    def home_location(self) -> Optional[tuple]:
        """Return (lat, lon) when both are set, otherwise None.

        When None, callers should log a warning and treat all ships as noteworthy.
        """
        raise NotImplementedError

    @property
    def distance_km(self) -> float:
        """Return the noteworthy-ship distance threshold in kilometres."""
        raise NotImplementedError

    @property
    def stale_ship_hours(self) -> float:
        """Return hours before an absent ship fires a DEPARTED event."""
        raise NotImplementedError

    @property
    def scroll_speed(self) -> float:
        """Return LED ticker scroll speed in pixels per second."""
        raise NotImplementedError

    @property
    def enrichment_delay_sec(self) -> float:
        """Return seconds to wait between enrichment scrape requests."""
        raise NotImplementedError

    @property
    def enrichment_max_attempts(self) -> int:
        """Return max scrape attempts per ship before permanently skipping."""
        raise NotImplementedError
