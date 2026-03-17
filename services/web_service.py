"""Web Portal Service for ShipsAhoy.

Flask application providing a browser-based interface for browsing ships,
viewing event history, and adjusting system settings.

Routes:
    GET  /              Ship list sorted by last_seen, with distance and type
    GET  /ship/<mmsi>   Ship detail: all fields + enrichment + visit history + photo
    GET  /events        Recent 50 events
    GET  /settings      Settings form pre-populated from Config
    POST /settings      Save updated settings, redirect to GET /settings
    GET  /static/photos/<filename>  Cached ship photos (served by Flask)

Flag display rule: show enrichment.flag when non-null, otherwise ships.flag.

Usage::

    uv run python services/web_service.py [--db PATH] [--port PORT] [--verbose]
"""

import argparse
import logging
import os

from flask import Flask, render_template, request, redirect, url_for

from ships_ahoy.config import Config
from ships_ahoy.db import (
    init_db,
    get_ship,
    get_enrichment,
    get_ships_in_range,
    get_recent_events,
    get_visit_history,
)
from ships_ahoy.distance import haversine_km, bearing_degrees, bearing_to_cardinal

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "ships.db"
DEFAULT_PORT = 5000

app = Flask(__name__, template_folder="../templates", static_folder="../static")

# Module-level connection — set in main() before app.run()
_conn = None
_cfg = None


def _get_conn():
    """Return the module-level DB connection. Set by main()."""
    if _conn is None:
        raise RuntimeError("Database connection not initialised. Call main() to start the service.")
    return _conn


def _get_cfg():
    """Return the module-level Config instance. Set by main()."""
    if _cfg is None:
        raise RuntimeError("Config not initialised. Call main() to start the service.")
    return _cfg


@app.route("/")
def index():
    """Ship list sorted by last_seen descending, with distance and type."""
    conn = _get_conn()
    cfg = _get_cfg()
    home = cfg.home_location

    rows = conn.execute(
        "SELECT * FROM ships ORDER BY last_seen DESC"
    ).fetchall()

    ships = []
    for row in rows:
        ship = dict(row)
        if home and ship["latitude"] and ship["longitude"]:
            km = haversine_km(home[0], home[1], ship["latitude"], ship["longitude"])
            bear = bearing_degrees(home[0], home[1], ship["latitude"], ship["longitude"])
            ship["distance_km"] = round(km, 1)
            ship["bearing"] = bearing_to_cardinal(bear)
        else:
            ship["distance_km"] = None
            ship["bearing"] = None
        ships.append(ship)

    return render_template("index.html", ships=ships, home=home)


@app.route("/ship/<int:mmsi>")
def ship_detail(mmsi: int):
    """Ship detail page: all DB fields + enrichment + visit history + photo."""
    conn = _get_conn()
    cfg = _get_cfg()

    ship_row = get_ship(conn, mmsi)
    if ship_row is None:
        return "Ship not found", 404

    enrichment_row = get_enrichment(conn, mmsi)
    visits = get_visit_history(conn, mmsi)
    home = cfg.home_location

    ship = dict(ship_row)
    enrichment = dict(enrichment_row) if enrichment_row else None

    # Flag display rule: enrichment.flag takes priority
    display_flag = (enrichment or {}).get("flag") or ship.get("flag")

    distance_km = None
    bearing = None
    if home and ship["latitude"] and ship["longitude"]:
        distance_km = round(
            haversine_km(home[0], home[1], ship["latitude"], ship["longitude"]), 1
        )
        bearing = bearing_to_cardinal(
            bearing_degrees(home[0], home[1], ship["latitude"], ship["longitude"])
        )

    photo_path = (enrichment or {}).get("photo_path")
    has_photo = photo_path is not None and os.path.exists(photo_path)

    return render_template(
        "ship.html",
        ship=ship,
        enrichment=enrichment,
        visits=visits,
        display_flag=display_flag,
        distance_km=distance_km,
        bearing=bearing,
        has_photo=has_photo,
        mmsi=mmsi,
    )


@app.route("/events")
def events():
    """Recent 50 events, newest first."""
    conn = _get_conn()
    event_rows = get_recent_events(conn, limit=50)
    event_list = []
    for row in event_rows:
        e = dict(row)
        ship_row = get_ship(conn, row["mmsi"])
        e["ship_name"] = ship_row["name"] if ship_row else str(row["mmsi"])
        event_list.append(e)
    return render_template("events.html", events=event_list)


@app.route("/settings", methods=["GET"])
def settings_get():
    """Settings form pre-populated from the settings table."""
    cfg = _get_cfg()
    settings = {
        "home_lat": cfg.get("home_lat", ""),
        "home_lon": cfg.get("home_lon", ""),
        "distance_km": cfg.get("distance_km", "50"),
        "scroll_speed_px_per_sec": cfg.get("scroll_speed_px_per_sec", "40"),
        "stale_ship_hours": cfg.get("stale_ship_hours", "1"),
        "enrichment_delay_sec": cfg.get("enrichment_delay_sec", "10"),
        "enrichment_max_attempts": cfg.get("enrichment_max_attempts", "3"),
    }
    return render_template("settings.html", settings=settings)


@app.route("/settings", methods=["POST"])
def settings_post():
    """Save submitted settings values and redirect to GET /settings."""
    cfg = _get_cfg()
    # Numeric keys validated before writing — a bad value here would crash services
    # on their next config read (float()/int() would raise ValueError).
    float_keys = [
        "home_lat", "home_lon", "distance_km", "scroll_speed_px_per_sec",
        "stale_ship_hours", "enrichment_delay_sec",
    ]
    int_keys = ["enrichment_max_attempts"]

    for key in float_keys:
        value = request.form.get(key, "").strip()
        if value:
            try:
                float(value)  # validate before storing
                cfg.set(key, value)
            except ValueError:
                logger.warning("Settings: invalid float for %s: %r — ignored", key, value)

    for key in int_keys:
        value = request.form.get(key, "").strip()
        if value:
            try:
                int(value)  # validate before storing
                cfg.set(key, value)
            except ValueError:
                logger.warning("Settings: invalid int for %s: %r — ignored", key, value)

    return redirect(url_for("settings_get"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web_service",
        description="ShipsAhoy Web Portal",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> None:
    """Service entry point. Initialises DB connection then starts Flask."""
    global _conn, _cfg
    args = _build_parser().parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    _conn = init_db(args.db)
    _cfg = Config(_conn)

    logger.info("Web service starting on port %d", args.port)
    # threaded=False enforces single-thread access to the module-level SQLite
    # connection. SQLite connections must not be shared across threads.
    # For multi-worker deployments, open a per-request connection instead.
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=False)


if __name__ == "__main__":
    main()
