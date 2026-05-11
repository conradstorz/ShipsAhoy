"""Standalone ship message formatter.

Accepts a plain dict of ship facts and returns a list of display strings
for a scrolling ticker. No project-specific imports.

Usage::

    from ships_ahoy.message_builder import format_ship_display

    facts = {
        "name": "MV Example",
        "type_label": "cargo vessel",
        "flag": "US",
        "speed_knots": 8.5,
        "heading_word": "west",
        "distance_km": 2.3,
        "bearing_word": "southwest",
        "status_label": None,
        "destination": "Rotterdam",
        "visit_count": 3,
        "length_m": 185.0,
        "build_year": 2003,
        "owner": "Maersk Line",
    }
    verbose = format_ship_display(facts, mode="verbose")
    # ["MV Example is a cargo vessel flying the US flag",
    #  "MV Example is traveling at 8.5 knots heading west", ...]

    compact = format_ship_display(facts, mode="compact")
    # ["MV Example is a cargo vessel flying the US flag, traveling at 8.5 knots
    #   heading west, 2.3 km away to the southwest, bound for Rotterdam, having
    #   visited this area 3 times, 185 meters long built in 2003, operated by
    #   Maersk Line"]
"""


def format_ship_display(facts: dict, mode: str = "verbose") -> list[str]:
    """Return display strings for one ship given a dict of known facts.

    Parameters
    ----------
    facts : dict
        name (str)                 — vessel name
        type_label (str)           — e.g. "cargo vessel", "tanker"
        flag (str | None)          — flag country/code; None to omit
        speed_knots (float | None) — speed over ground; None to omit
        heading_word (str | None)  — e.g. "west", "north-northeast"; None to omit
        distance_km (float | None) — distance from home; None to omit
        bearing_word (str | None)  — e.g. "southwest"; None to omit
        status_label (str | None)  — e.g. "at anchor"; None to omit
        destination (str | None)   — destination name; None to omit
        visit_count (int)          — number of visits recorded (default 1)
        length_m (float | None)    — vessel length in metres; None to omit
        build_year (int | None)    — year of construction; None to omit
        owner (str | None)         — operator name; None to omit
    mode : str
        "verbose" — one string per available fact; vessel name in every string
        "compact" — all facts in one string; vessel name appears only once

    Returns
    -------
    list[str]
        verbose: up to 8 strings, one per available fact category.
        compact: exactly 1 string with all facts joined as clauses.
    """
    name        = facts.get("name", "Unknown vessel")
    type_label  = facts.get("type_label", "vessel")
    flag        = facts.get("flag")
    speed       = facts.get("speed_knots")
    heading     = facts.get("heading_word")
    distance    = facts.get("distance_km")
    bearing     = facts.get("bearing_word")
    status      = facts.get("status_label")
    destination = facts.get("destination")
    visits      = facts.get("visit_count", 1)
    length      = facts.get("length_m")
    build_year  = facts.get("build_year")
    owner       = facts.get("owner")

    if mode == "compact":
        return _compact(name, type_label, flag, speed, heading, distance, bearing,
                        status, destination, visits, length, build_year, owner)
    return _verbose(name, type_label, flag, speed, heading, distance, bearing,
                    status, destination, visits, length, build_year, owner)


def _verbose(name, type_label, flag, speed, heading, distance, bearing,
             status, destination, visits, length, build_year, owner) -> list[str]:
    chunks: list[str] = []

    if flag:
        chunks.append(f"{name} is a {type_label} flying the {flag} flag")
    else:
        chunks.append(f"{name} is a {type_label}")

    if speed is not None and heading is not None:
        chunks.append(f"{name} is traveling at {speed:.1f} knots heading {heading}")

    if distance is not None and bearing is not None:
        chunks.append(f"{name} is {distance:.1f} km away, to the {bearing}")

    if status:
        chunks.append(f"{name} is currently {status}")

    if destination:
        chunks.append(f"{name} is bound for {destination}")

    if visits == 1:
        chunks.append(f"This is {name}'s first visit to this area")
    else:
        chunks.append(f"{name} has visited this area {visits} times")

    if length is not None:
        if build_year is not None:
            chunks.append(f"{name} is {int(length)} meters long, built in {build_year}")
        else:
            chunks.append(f"{name} is {int(length)} meters long")

    if owner:
        chunks.append(f"{name} is operated by {owner}")

    return chunks


def _compact(name, type_label, flag, speed, heading, distance, bearing,
             status, destination, visits, length, build_year, owner) -> list[str]:
    base = f"a {type_label}"
    if flag:
        base += f" flying the {flag} flag"
    clauses: list[str] = [f"{name} is {base}"]

    if speed is not None and heading is not None:
        clauses.append(f"traveling at {speed:.1f} knots heading {heading}")

    if distance is not None and bearing is not None:
        clauses.append(f"{distance:.1f} km away to the {bearing}")

    if status:
        clauses.append(f"currently {status}")

    if destination:
        clauses.append(f"bound for {destination}")

    if visits == 1:
        clauses.append("making its first visit to this area")
    else:
        clauses.append(f"having visited this area {visits} times")

    if length is not None:
        size = f"{int(length)} meters long"
        if build_year is not None:
            size += f" built in {build_year}"
        clauses.append(size)

    if owner:
        clauses.append(f"operated by {owner}")

    return [", ".join(clauses)]
