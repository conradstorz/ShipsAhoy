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
    raise NotImplementedError


@app.route("/ship/<int:mmsi>")
def ship_detail(mmsi: int):
    """Ship detail page: all DB fields + enrichment + visit history + photo."""
    raise NotImplementedError


@app.route("/events")
def events():
    """Recent 50 events, newest first."""
    raise NotImplementedError


@app.route("/settings", methods=["GET"])
def settings_get():
    """Settings form pre-populated from the settings table."""
    raise NotImplementedError


@app.route("/settings", methods=["POST"])
def settings_post():
    """Save submitted settings values and redirect to GET /settings."""
    raise NotImplementedError


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
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
