"""Ship tracking module.

Maintains a registry of all ships seen since the application started.
Each ship is identified by its MMSI (Maritime Mobile Service Identity) and
updated whenever a new AIS position or static-data message arrives.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from pyais.messages import ANY_MESSAGE

logger = logging.getLogger(__name__)

# Sentinel values defined by the AIS standard that mean "not available".
_LAT_UNAVAILABLE = 91.0
_LON_UNAVAILABLE = 181.0
_SPEED_UNAVAILABLE = 102.3
_HEADING_UNAVAILABLE = 511
_COURSE_UNAVAILABLE = 360.0


@dataclass
class ShipInfo:
    """All known information about a single ship.

    Parameters
    ----------
    mmsi:
        Maritime Mobile Service Identity — the ship's unique numeric ID.
    """

    mmsi: int
    name: str = "Unknown"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    speed: Optional[float] = None       # knots over ground
    heading: Optional[float] = None     # true heading in degrees
    course: Optional[float] = None      # course over ground in degrees
    ship_type: Optional[int] = None     # AIS numeric ship-type code
    status: Optional[int] = None        # AIS navigation status code
    last_seen: datetime = field(default_factory=datetime.now)

    @property
    def position(self) -> Optional[tuple]:
        """Return ``(latitude, longitude)`` when both values are known."""
        if self.latitude is not None and self.longitude is not None:
            return (self.latitude, self.longitude)
        return None


class ShipTracker:
    """Maintain a live registry of ships from decoded AIS messages.

    Usage::

        tracker = ShipTracker()
        for decoded_msg in receiver.messages():
            ship = tracker.update(decoded_msg)
    """

    def __init__(self) -> None:
        self._ships: Dict[int, ShipInfo] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update(self, msg: ANY_MESSAGE) -> Optional[ShipInfo]:
        """Update ship data from a decoded AIS message.

        Parameters
        ----------
        msg:
            A decoded AIS message returned by
            :py:meth:`pyais.messages.NMEAMessage.decode`.

        Returns
        -------
        ShipInfo | None
            The updated :class:`ShipInfo` for the sender, or *None* if the
            message did not contain a recognisable MMSI.
        """
        mmsi = getattr(msg, "mmsi", None)
        if mmsi is None:
            return None

        mmsi = int(mmsi)
        if mmsi not in self._ships:
            self._ships[mmsi] = ShipInfo(mmsi=mmsi)

        ship = self._ships[mmsi]
        ship.last_seen = datetime.now()

        # --- position / kinematic fields (msg types 1, 2, 3, 18) ---
        lat = getattr(msg, "lat", None)
        if lat is not None:
            lat = float(lat)
            if lat != _LAT_UNAVAILABLE:
                ship.latitude = lat

        lon = getattr(msg, "lon", None)
        if lon is not None:
            lon = float(lon)
            if lon != _LON_UNAVAILABLE:
                ship.longitude = lon

        speed = getattr(msg, "speed", None)
        if speed is not None:
            speed = float(speed)
            if speed != _SPEED_UNAVAILABLE:
                ship.speed = speed

        heading = getattr(msg, "heading", None)
        if heading is not None:
            heading_val = float(heading)
            if heading_val != _HEADING_UNAVAILABLE:
                ship.heading = heading_val

        course = getattr(msg, "course", None)
        if course is not None:
            course = float(course)
            if course != _COURSE_UNAVAILABLE:
                ship.course = course

        status = getattr(msg, "status", None)
        if status is not None:
            try:
                ship.status = int(status)
            except (TypeError, ValueError):
                pass

        # --- static / voyage data (msg types 5, 24, 21) ---
        shipname = getattr(msg, "shipname", None)
        if shipname:
            name = str(shipname).strip()
            if name:
                ship.name = name

        # msg type 21 uses "name" instead of "shipname"
        name_field = getattr(msg, "name", None)
        if name_field:
            name = str(name_field).strip()
            if name:
                ship.name = name

        ship_type = getattr(msg, "ship_type", None)
        if ship_type is not None:
            try:
                ship.ship_type = int(ship_type)
            except (TypeError, ValueError):
                pass

        return ship

    @property
    def ships(self) -> Dict[int, ShipInfo]:
        """Return a snapshot of all tracked ships keyed by MMSI."""
        return dict(self._ships)

    def get_ship(self, mmsi: int) -> Optional[ShipInfo]:
        """Return the :class:`ShipInfo` for *mmsi*, or *None* if unknown."""
        return self._ships.get(mmsi)

    def ship_count(self) -> int:
        """Return the number of unique ships seen so far."""
        return len(self._ships)
