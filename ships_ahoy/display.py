"""Terminal display module for ShipsAhoy.

Formats and prints the current list of tracked ships to stdout, clearing
the screen between refreshes to produce a live-updating view.
"""

import os
from datetime import datetime
from typing import Dict

from ships_ahoy.ship_tracker import ShipInfo

# AIS navigation status codes → human-readable strings
_NAV_STATUS: Dict[int, str] = {
    0: "Under way (engine)",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way (sailing)",
    9: "Reserved (HSC)",
    10: "Reserved (WIG)",
    11: "Reserved",
    12: "Reserved",
    13: "Reserved",
    14: "AIS-SART / MOB / EPIRB",
    15: "Undefined",
}

# AIS ship-type ranges → category names
_SHIP_TYPE_RANGES = [
    (range(20, 30), "Wing In Ground"),
    (range(30, 40), "Fishing"),
    (range(40, 50), "Towing"),
    (range(50, 60), "Special Craft"),
    (range(60, 70), "Passenger"),
    (range(70, 80), "Cargo"),
    (range(80, 90), "Tanker"),
    (range(90, 100), "Other"),
]


def get_ship_type_name(ship_type: int) -> str:
    """Return a human-readable category for an AIS *ship_type* code."""
    if ship_type is None:
        return "Unknown"
    for type_range, label in _SHIP_TYPE_RANGES:
        if ship_type in type_range:
            return label
    return f"Type {ship_type}"


def get_nav_status_name(status: int) -> str:
    """Return a human-readable label for an AIS navigation *status* code."""
    return _NAV_STATUS.get(status, f"Status {status}")


def format_ship(ship: ShipInfo) -> str:
    """Format a single ship's data as a multi-line string."""
    lines = [
        f"MMSI : {ship.mmsi}",
        f"  Name    : {ship.name}",
    ]
    if ship.position is not None:
        lines.append(f"  Position: {ship.latitude:.5f}° N  {ship.longitude:.5f}° E")
    if ship.speed is not None:
        lines.append(f"  Speed   : {ship.speed:.1f} knots")
    if ship.heading is not None:
        lines.append(f"  Heading : {ship.heading:.0f}°")
    if ship.course is not None:
        lines.append(f"  Course  : {ship.course:.1f}°")
    if ship.status is not None:
        lines.append(f"  Status  : {get_nav_status_name(ship.status)}")
    if ship.ship_type is not None:
        lines.append(f"  Type    : {get_ship_type_name(ship.ship_type)}")
    lines.append(f"  Last seen: {ship.last_seen.strftime('%H:%M:%S')}")
    return "\n".join(lines)


def display_ships(ships: Dict[int, ShipInfo]) -> None:
    """Clear the terminal and print all currently tracked ships."""
    os.system("clear" if os.name == "posix" else "cls")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count = len(ships)

    print("=" * 55)
    print("  ⚓  ShipsAhoy — AIS Ship Tracker")
    print(f"  {now}   Ships tracked: {count}")
    print("=" * 55)

    if not ships:
        print("\n  No ships detected yet.  Listening for AIS broadcasts…\n")
    else:
        for mmsi in sorted(ships):
            print()
            print(format_ship(ships[mmsi]))
        print()
