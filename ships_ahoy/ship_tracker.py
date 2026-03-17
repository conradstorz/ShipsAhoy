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

# Maritime Identification Digits (MID) → ISO 3166-1 alpha-2 country code.
# First 3 digits of an MMSI identify the ship's country of registration.
# Source: ITU List of ITU-T Recommendation E.212 Annex to Appendix 1 (partial).
_MID_TO_FLAG: dict[int, str] = {
    201: "AL", 202: "AD", 203: "AT", 204: "PT", 205: "BE", 206: "BY",
    207: "BG", 208: "VA", 209: "CY", 210: "CY", 211: "DE", 212: "CY",
    213: "GE", 214: "MD", 215: "MT", 216: "AM", 218: "DE", 219: "DK",
    220: "DK", 224: "ES", 225: "ES", 226: "FR", 227: "FR", 228: "FR",
    229: "MT", 230: "FI", 231: "FO", 232: "GB", 233: "GB", 234: "GB",
    235: "GB", 236: "GI", 237: "GR", 238: "HR", 239: "GR", 240: "GR",
    241: "GR", 242: "MA", 243: "HU", 244: "NL", 245: "NL", 246: "NL",
    247: "IT", 248: "MT", 249: "MT", 250: "IE", 251: "IS", 252: "LI",
    253: "LU", 254: "MC", 255: "PT", 256: "MT", 257: "NO", 258: "NO",
    259: "NO", 261: "PL", 262: "ME", 263: "PT", 264: "RO", 265: "SE",
    266: "SE", 267: "SK", 268: "SM", 269: "CH", 270: "CZ", 271: "TR",
    272: "UA", 273: "RU", 274: "MK", 275: "LV", 276: "EE", 277: "LT",
    278: "SI", 279: "RS", 301: "AG", 303: "US", 304: "AG", 305: "AG",
    306: "NL", 307: "AW", 308: "BS", 309: "BS", 310: "BM", 311: "BS",
    312: "BZ", 314: "BB", 316: "CA", 319: "KY", 321: "CR", 323: "CU",
    325: "DM", 327: "DO", 329: "GP", 330: "GD", 331: "GL", 332: "GT",
    334: "HN", 336: "HT", 338: "US", 339: "JM", 341: "KN", 343: "LC",
    345: "MX", 347: "MQ", 348: "MS", 350: "NI", 351: "PA", 352: "PA",
    353: "PA", 354: "PA", 355: "PA", 356: "PA", 357: "PA", 358: "PR",
    359: "SV", 361: "PM", 362: "TT", 364: "TC", 366: "US", 367: "US",
    368: "US", 369: "US", 370: "PA", 371: "PA", 372: "PA", 373: "PA",
    374: "PA", 375: "VC", 376: "VC", 377: "VC", 378: "VG", 379: "VI",
    401: "AF", 403: "SA", 405: "BD", 408: "BH", 410: "BT", 412: "CN",
    413: "CN", 414: "CN", 416: "TW", 422: "IR", 423: "AZ", 425: "IQ",
    428: "IL", 431: "JP", 432: "JP", 434: "TM", 436: "KZ", 438: "JO",
    440: "KR", 441: "KR", 443: "PS", 445: "KP", 447: "KW", 450: "LB",
    451: "KY", 453: "MO", 455: "MV", 457: "MN", 459: "NP", 461: "OM",
    463: "PK", 466: "QA", 468: "SY", 470: "AE", 471: "AE", 472: "TJ",
    473: "YE", 477: "HK", 478: "BA", 501: "AQ", 503: "AU", 506: "MM",
    508: "BN", 510: "FM", 511: "PW", 512: "NZ", 514: "KH", 515: "KH",
    516: "CX", 518: "CK", 520: "FJ", 523: "CC", 525: "ID", 529: "KI",
    531: "LA", 533: "MY", 536: "MP", 538: "MH", 540: "NC", 542: "NZ",
    544: "NR", 546: "FR", 548: "PH", 553: "PG", 555: "PN", 557: "SB",
    559: "WS", 561: "SG", 563: "SG", 564: "SG", 565: "SG", 566: "SG",
    567: "TH", 570: "TO", 572: "TV", 574: "VN", 576: "VU", 578: "WF",
    601: "ZA", 603: "AO", 605: "DZ", 607: "FR", 608: "IO", 609: "BI",
    610: "BJ", 611: "BW", 612: "CF", 613: "CM", 615: "CG", 616: "KM",
    617: "CV", 618: "AQ", 619: "CI", 620: "KM", 621: "DJ", 622: "EG",
    624: "ET", 625: "ER", 626: "GA", 627: "GH", 629: "GM", 630: "GW",
    631: "GQ", 632: "GN", 633: "BF", 634: "KE", 635: "AQ", 636: "LR",
    637: "LR", 638: "SS", 642: "LY", 644: "LS", 645: "MU", 647: "MG",
    649: "ML", 650: "MZ", 654: "MR", 655: "MW", 656: "MA", 657: "TN",
    659: "NA", 660: "FR", 661: "NE", 662: "NG", 663: "SO", 664: "SC",
    665: "SL", 666: "ST", 667: "SN", 668: "SO", 669: "ZW", 670: "SD",
    671: "SD", 672: "TZ", 674: "TG", 675: "AO", 676: "UG", 677: "TZ",
    678: "ZM", 679: "ZW",
}


def _mmsi_to_flag(mmsi: int) -> Optional[str]:
    """Derive ISO country code from the first 3 digits (MID) of an MMSI."""
    mid = mmsi // 1_000_000
    return _MID_TO_FLAG.get(mid)


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
    destination: Optional[str] = None  # port of destination from AIS type-5
    flag: Optional[str] = None         # country flag code from AIS type-24
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

        # destination from AIS type-5 messages
        destination = getattr(msg, "destination", None)
        if destination:
            dest = str(destination).strip()
            if dest:
                ship.destination = dest

        # flag derived from MMSI MID prefix (set once; MMSI never changes)
        if ship.flag is None:
            ship.flag = _mmsi_to_flag(mmsi)

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
