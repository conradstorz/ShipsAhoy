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
import json
import logging
import os
import subprocess
import time

from flask import Flask, Response, render_template, request, redirect, url_for

from ships_ahoy.config import Config
from ships_ahoy.db import (
    init_db,
    get_all_ships,
    get_ship,
    get_enrichment,
    get_ships_in_range,
    get_recent_events,
    get_visit_history,
    get_display_state,
)
import geonamescache as _gnc
from ships_ahoy.distance import distance_info, haversine_km
from ships_ahoy.matrix_driver import PreviewDriver, ESP32_DISPLAY_WIDTH, ESP32_DISPLAY_HEIGHT
from ships_ahoy.service_utils import DEFAULT_DB_PATH, configure_logging

logger = logging.getLogger(__name__)

DEFAULT_PORT = 5000

ESP32_UART_DEVICE = "/dev/ttyUSB0"  # matches ships-ahoy-ticker.service ExecStart

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INSTALL_LOG = os.path.join(_REPO_DIR, "setup", "install.log")

_SERVICES = [
    "ships-ahoy-rtl-ais",
    "ships-ahoy-ais",
    "ships-ahoy-enrichment",
    "ships-ahoy-ticker",
]


def _service_status(name: str) -> str:
    """Return 'active', 'inactive', or 'unknown' for a systemd unit."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=2
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _system_uptime() -> str:
    """Return a human-readable system uptime string from /proc/uptime."""
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)
    except Exception:
        return "unknown"


def _system_status() -> dict:
    """Collect status data passed to every page that needs it."""
    return {
        "uptime": _system_uptime(),
        "services": {name: _service_status(name) for name in _SERVICES},
        "esp32_attached": os.path.exists(ESP32_UART_DEVICE),
    }


def _rtl_ais_journal(lines: int = 40) -> str:
    """Return the last *lines* lines from the ships-ahoy-rtl-ais journal."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", "ships-ahoy-rtl-ais", f"-n{lines}", "--no-pager",
             "--output=short-monotonic"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or "(no journal entries found)"
    except Exception as exc:
        return f"(error reading journal: {exc})"


def _fm_scan() -> dict:
    """Stop rtl_ais, sweep the FM broadcast band, restart rtl_ais.

    Returns {'stations': [{freq_mhz, db}, ...], 'raw': str, 'error': str|None}.
    Stations are sorted by frequency.
    """
    rtl_power = subprocess.run(["which", "rtl_power"], capture_output=True, text=True).stdout.strip()
    if not rtl_power:
        return {"stations": [], "raw": "", "error": "rtl_power not found — install the rtl-sdr package."}

    raw = ""
    error = None
    stations = []
    try:
        stop = subprocess.run(
            ["sudo", "systemctl", "stop", "ships-ahoy-rtl-ais"],
            capture_output=True, timeout=6,
        )
        if stop.returncode != 0:
            error = f"Could not stop rtl_ais service (exit {stop.returncode})"
        else:
            time.sleep(0.5)
            result = subprocess.run(
                [rtl_power, "-f", "87.5M:108M:200k", "-g", "40", "-i", "2", "-1", "-"],
                capture_output=True, text=True, timeout=20,
            )
            raw = result.stdout
            if result.returncode != 0:
                error = result.stderr.strip() or f"rtl_power exited {result.returncode}"
            else:
                # Parse CSV: date, time, start_hz, end_hz, step_hz, samples, db...
                by_freq: dict[float, float] = {}
                for line in raw.splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < 7:
                        continue
                    try:
                        start_hz = float(parts[2])
                        step_hz = float(parts[4])
                        db_values = [float(v) for v in parts[6:] if v]
                        for i, db in enumerate(db_values):
                            freq_hz = start_hz + step_hz * i + step_hz / 2
                            freq_mhz = round(freq_hz / 1e6, 1)
                            if 87.5 <= freq_mhz <= 108.0:
                                if freq_mhz not in by_freq or db > by_freq[freq_mhz]:
                                    by_freq[freq_mhz] = db
                    except (ValueError, IndexError):
                        continue
                stations = sorted(
                    [{"freq_mhz": f, "db": round(db, 1)} for f, db in by_freq.items()],
                    key=lambda x: x["freq_mhz"],
                )
    except subprocess.TimeoutExpired as exc:
        error = f"Timed out: {exc}"
    except Exception as exc:
        error = str(exc)
    finally:
        subprocess.run(["sudo", "systemctl", "start", "ships-ahoy-rtl-ais"], timeout=6)

    return {"stations": stations, "raw": raw, "error": error}


def _ais_band_scan() -> dict:
    """Stop rtl_ais, sweep 159–165 MHz at 25 kHz resolution, restart rtl_ais.

    Returns {'bins': [{freq_mhz, db}, ...], 'raw': str, 'error': str|None}.
    AIS channels are at 161.975 MHz (Ch 87B) and 162.025 MHz (Ch 88B).
    NOAA weather radio occupies 162.400–162.550 MHz and will appear as a strong peak.
    """
    rtl_power = subprocess.run(["which", "rtl_power"], capture_output=True, text=True).stdout.strip()
    if not rtl_power:
        return {"bins": [], "raw": "", "error": "rtl_power not found — install the rtl-sdr package."}

    raw = ""
    error = None
    bins = []
    try:
        stop = subprocess.run(
            ["sudo", "systemctl", "stop", "ships-ahoy-rtl-ais"],
            capture_output=True, timeout=6,
        )
        if stop.returncode != 0:
            error = f"Could not stop rtl_ais service (exit {stop.returncode})"
        else:
            time.sleep(0.5)
            result = subprocess.run(
                [rtl_power, "-f", "159M:165M:25k", "-g", "50", "-i", "5", "-1", "-"],
                capture_output=True, text=True, timeout=30,
            )
            raw = result.stdout
            if result.returncode != 0:
                error = result.stderr.strip() or f"rtl_power exited {result.returncode}"
            else:
                by_freq: dict[float, float] = {}
                for line in raw.splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < 7:
                        continue
                    try:
                        start_hz = float(parts[2])
                        step_hz = float(parts[4])
                        db_values = [float(v) for v in parts[6:] if v]
                        for i, db in enumerate(db_values):
                            freq_hz = start_hz + step_hz * i + step_hz / 2
                            freq_mhz = round(freq_hz / 1e6, 3)
                            if 159.0 <= freq_mhz <= 165.0:
                                if freq_mhz not in by_freq or db > by_freq[freq_mhz]:
                                    by_freq[freq_mhz] = db
                    except (ValueError, IndexError):
                        continue
                bins = sorted(
                    [{"freq_mhz": f, "db": round(db, 1)} for f, db in by_freq.items()],
                    key=lambda x: x["freq_mhz"],
                )
    except subprocess.TimeoutExpired as exc:
        error = f"Timed out: {exc}"
    except Exception as exc:
        error = str(exc)
    finally:
        subprocess.run(["sudo", "systemctl", "start", "ships-ahoy-rtl-ais"], timeout=6)

    return {"bins": bins, "raw": raw, "error": error}


def _install_log_entries(n: int = 75) -> list[tuple[str, str]]:
    """Return the last n log entries from setup/install.log as (level, line) pairs."""
    entries: list[tuple[str, str]] = []
    try:
        with open(_INSTALL_LOG) as f:
            for raw_line in f:
                line = raw_line.rstrip()
                for level in ("INFO", "WARN", "ERROR"):
                    if f"[{level}" in line:
                        entries.append((level, line))
                        break
    except FileNotFoundError:
        return [("ERROR", "(setup/install.log not found)")]
    except Exception as exc:
        return [("ERROR", f"(error: {exc})")]
    return entries[-n:][::-1]


_gc = _gnc.GeonamesCache()


def _cities_in_range(home_lat: float, home_lon: float, radius_km: float, n: int = 3) -> list[dict]:
    """Return the n most populous cities within radius_km of home."""
    nearby = []
    for city in _gc.get_cities().values():
        dist = haversine_km(home_lat, home_lon, float(city["latitude"]), float(city["longitude"]))
        if dist <= radius_km:
            nearby.append({
                "name": city["name"],
                "population": city["population"],
                "distance_km": round(dist, 1),
            })
    nearby.sort(key=lambda c: c["population"], reverse=True)
    return nearby[:n]


app = Flask(__name__, template_folder="../templates", static_folder="../static")

# Module-level connection — set in main() before app.run()
_conn = None
_cfg = None
_db_path = DEFAULT_DB_PATH  # set in main(); used by SSE generator


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

    ships = []
    for row in get_all_ships(conn):
        ship = dict(row)
        if home and ship["latitude"] and ship["longitude"]:
            ship["distance_km"], ship["bearing"] = distance_info(
                home[0], home[1], ship["latitude"], ship["longitude"]
            )
        else:
            ship["distance_km"] = None
            ship["bearing"] = None
        ships.append(ship)

    nearby_cities = _cities_in_range(home[0], home[1], cfg.distance_km) if home else []

    return render_template("index.html", ships=ships, home=home,
                           status=_system_status(),
                           log_entries=_install_log_entries(),
                           nearby_cities=nearby_cities)


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
        distance_km, bearing = distance_info(home[0], home[1], ship["latitude"], ship["longitude"])

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
    ship_names = {r["mmsi"]: r["name"] for r in get_all_ships(conn)}
    event_list = []
    for row in get_recent_events(conn):
        e = dict(row)
        e["ship_name"] = ship_names.get(row["mmsi"]) or str(row["mmsi"])
        event_list.append(e)
    return render_template("events.html", events=event_list)


@app.route("/ticker/preview")
def ticker_preview():
    """Server-Sent Events stream of rendered ticker frames at ~30 FPS.

    Each SSE client opens its own SQLite connection and PreviewDriver instance.
    The generator polls display_state every ~250 ms for content updates,
    and ticks the PreviewDriver at ~30 FPS.
    """
    max_frames = request.args.get("_max_frames", type=int)  # test hook

    def generate():
        import sqlite3
        conn = sqlite3.connect(_db_path)
        conn.row_factory = sqlite3.Row
        preview = PreviewDriver(
            display_width=ESP32_DISPLAY_WIDTH,
            display_height=ESP32_DISPLAY_HEIGHT,
        )
        last_updated_at = None
        last_frame_time = time.monotonic()
        frames_sent = 0
        poll_counter = 0

        try:
            while True:
                # Poll display_state every ~250 ms (every 8 frames at 30 FPS)
                poll_counter += 1
                if poll_counter >= 8:
                    poll_counter = 0
                    row = get_display_state(conn)
                    if row and row["updated_at"] != last_updated_at:
                        last_updated_at = row["updated_at"]
                        if row["mode"] == "scroll":
                            preview.scroll_text(row["text"] or "", speed_px_per_sec=row["speed"] or 40.0)
                        else:
                            preview.show_static(
                                row["text"] or "",
                                (row["duration_ms"] or 2000) / 1000.0,
                            )

                # Advance scroll and get frame
                now = time.monotonic()
                elapsed = now - last_frame_time
                last_frame_time = now
                frame = preview.get_current_frame(elapsed_sec=elapsed)

                # Flatten row-major and emit
                flat = [list(px) for pixel_row in frame for px in pixel_row]
                data = json.dumps({
                    "pixels": flat,
                    "width": ESP32_DISPLAY_WIDTH,
                    "height": ESP32_DISPLAY_HEIGHT,
                })
                yield f"data: {data}\n\n"

                frames_sent += 1
                if max_frames is not None and frames_sent >= max_frames:
                    break

                time.sleep(1 / 30)
        finally:
            conn.close()

    return Response(
        generate(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/ticker")
def ticker_page():
    """Ticker live preview page."""
    return render_template("ticker_preview.html")


@app.route("/sdr-verify")
def sdr_verify():
    """SDR hardware verification page: journal output + FM scan button."""
    journal = _rtl_ais_journal()
    return render_template("sdr_verify.html", journal=journal, status=_system_status())


@app.route("/sdr-scan-fm", methods=["POST"])
def sdr_scan_fm():
    """Run an FM band sweep and return JSON results."""
    result = _fm_scan()
    return json.dumps(result), 200, {"Content-Type": "application/json"}


@app.route("/sdr-scan-ais", methods=["POST"])
def sdr_scan_ais():
    """Run an AIS-band power sweep (159–165 MHz) and return JSON results."""
    result = _ais_band_scan()
    return json.dumps(result), 200, {"Content-Type": "application/json"}


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
    global _conn, _cfg, _db_path
    args = _build_parser().parse_args()
    configure_logging(args.verbose)

    _db_path = args.db
    _conn = init_db(args.db, check_same_thread=False)
    _cfg = Config(_conn)

    logger.info("Web service starting on port %d", args.port)
    # threaded=True allows SSE connections to stream while other routes remain
    # responsive. Each SSE generator opens its own SQLite connection (WAL mode
    # supports concurrent reads) so _conn is not accessed from SSE threads.
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
