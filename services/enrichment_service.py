"""Enrichment Service for ShipsAhoy.

Scrapes free internet sources to gather additional details about ships
and caches results in the enrichment table and static/photos/.

Runs as a persistent systemd service.

Responsibilities:
- Poll get_unenriched_ships() in a loop
- For each unenriched MMSI: attempt scrape from sources in priority order
- Sleep enrichment_delay_sec between each request (rate limiting)
- Download first available photo to static/photos/<mmsi>.jpg
- Mark ship enriched and write ENRICHED event on success
- Increment fetch_attempts on failure; stop retrying at enrichment_max_attempts

Scrape source priority order:
1. ShipXplorer: https://www.shipxplorer.com/vessel/<mmsi>
2. MyShipTracking: https://www.myshiptracking.com/vessels/<mmsi>
3. MarineTraffic (may block): https://www.marinetraffic.com/en/ais/details/ships/mmsi:<mmsi>
4. ITU MMSI lookup (form POST): https://www.itu.int/mmsapp/ShipSearch.do

HTTP client: requests + BeautifulSoup (html.parser)

Usage::

    uv run python services/enrichment_service.py [--db PATH] [--photos-dir DIR] [--verbose]
"""

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger

from ships_ahoy.config import Config
from ships_ahoy.db import init_db, get_unenriched_ships, increment_fetch_attempts, save_enrichment, write_event
from ships_ahoy.events import EventType
from ships_ahoy.service_utils import DEFAULT_DB_PATH, configure_logging

DEFAULT_PHOTOS_DIR = "static/photos"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ShipsAhoy/1.0)"}
_TIMEOUT = 10


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enrichment_service",
        description="ShipsAhoy Enrichment Service",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, metavar="PATH")
    parser.add_argument("--photos-dir", default=DEFAULT_PHOTOS_DIR, metavar="DIR")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--reset-enrichment",
        action="store_true",
        help="Clear enriched flag and reset fetch_attempts for ships with no vessel name, "
             "then run the service normally.",
    )
    return parser


_SERVICE_SCRIPTS = {
    "ais_service.py",
    "enrichment_service.py",
    "ticker_service.py",
    "web_service.py",
}


def _find_competing_services() -> list[str]:
    """Return a list of ShipsAhoy service command-lines running in other processes."""
    my_pid = os.getpid()
    competing = []
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == my_pid:
                continue
            cmdline_file = entry / "cmdline"
            try:
                cmdline = cmdline_file.read_text().replace("\0", " ").strip()
            except OSError:
                continue
            if any(svc in cmdline for svc in _SERVICE_SCRIPTS):
                competing.append(cmdline)
    except OSError:
        pass
    return competing


def _check_db_writable(conn) -> bool:
    """Return True if a write lock can be acquired on the database within 2 seconds.

    Logs an error and returns False if the database is locked by another process.
    """
    try:
        conn.execute("PRAGMA busy_timeout = 2000")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError as exc:
        logger.error(
            "Database is locked or unavailable (another process may be holding a write lock): {}",
            exc,
        )
        return False


def _reset_enrichment(conn) -> None:
    """Reset enriched=FALSE and fetch_attempts=0 for ships with no vessel name."""
    result = conn.execute(
        """
        UPDATE ships SET enriched = FALSE
        WHERE mmsi IN (
            SELECT s.mmsi FROM ships s
            LEFT JOIN enrichment e ON s.mmsi = e.mmsi
            WHERE e.vessel_name IS NULL OR e.vessel_name = ''
        )
        """
    )
    ships_reset = result.rowcount
    result = conn.execute(
        "UPDATE enrichment SET fetch_attempts = 0 WHERE vessel_name IS NULL OR vessel_name = ''"
    )
    attempts_reset = result.rowcount
    conn.commit()
    logger.info(
        "Reset enrichment: {} ships unmarked, {} fetch_attempt counters cleared",
        ships_reset, attempts_reset,
    )


def _scrape_shipxplorer(mmsi: int) -> Optional[dict]:
    """Attempt to scrape vessel data from ShipXplorer.

    Returns a dict with any of: vessel_name, imo, call_sign, flag,
    ship_type_label, length_m, build_year, owner, photo_url, source.
    Returns None on any failure.
    """
    url = f"https://www.shipxplorer.com/vessel/{mmsi}"
    resp = requests.get(url, timeout=_TIMEOUT, headers=_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    data: dict = {"source": "shipxplorer"}

    h1 = soup.find("h1")
    if h1:
        data["vessel_name"] = h1.get_text(strip=True)

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        key = cells[0].get_text(strip=True).lower()
        val = cells[1].get_text(strip=True)
        if not val:
            continue
        if "flag" in key:
            data["flag"] = val
        elif "imo" in key:
            data["imo"] = val
        elif "call" in key:
            data["call_sign"] = val
        elif "type" in key:
            data["ship_type_label"] = val
        elif "length" in key:
            try:
                data["length_m"] = float(val.split()[0])
            except (ValueError, IndexError):
                pass
        elif "built" in key or "year" in key:
            try:
                data["build_year"] = int(val[:4])
            except ValueError:
                pass

    img = soup.find("img", src=lambda s: s and ("vessel" in s.lower() or "/ships/" in s))
    if img and img.get("src"):
        src = img["src"]
        data["photo_url"] = src if src.startswith("http") else f"https://www.shipxplorer.com{src}"

    return data if len(data) > 1 else None


def _scrape_marinetraffic(mmsi: int) -> Optional[dict]:
    """Attempt to scrape vessel data from MarineTraffic public pages.

    May return 403 or Cloudflare challenge — returns None on any failure.
    Returns same dict shape as _scrape_shipxplorer.
    """
    url = f"https://www.marinetraffic.com/en/ais/details/ships/mmsi:{mmsi}"
    resp = requests.get(url, timeout=_TIMEOUT, headers=_HEADERS)
    resp.raise_for_status()  # raises on 4xx/5xx including 403

    # raise_for_status() won't catch Cloudflare challenge pages (200 with JS wall)
    if "cloudflare" in resp.text.lower():
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    data: dict = {"source": "marinetraffic"}

    title = soup.find("title")
    if title:
        name = title.get_text(strip=True).split("|")[0].strip()
        if name:
            data["vessel_name"] = name

    for item in soup.find_all(class_=lambda c: c and "vessel-detail" in c):
        label_el = item.find(class_=lambda c: c and "label" in c)
        value_el = item.find(class_=lambda c: c and "value" in c)
        if not label_el or not value_el:
            continue
        key = label_el.get_text(strip=True).lower()
        val = value_el.get_text(strip=True)
        if "flag" in key:
            data["flag"] = val
        elif "imo" in key:
            data["imo"] = val
        elif "call" in key:
            data["call_sign"] = val

    return data if len(data) > 1 else None


def _scrape_myshiptracking(mmsi: int) -> Optional[dict]:
    """Attempt to scrape vessel data from MyShipTracking.

    Returns a dict with any of: vessel_name, imo, call_sign, flag,
    ship_type_label, length_m, build_year, source.
    Returns None on any failure.
    """
    url = f"https://www.myshiptracking.com/vessels/{mmsi}"
    resp = requests.get(url, timeout=_TIMEOUT, headers=_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    data: dict = {"source": "myshiptracking"}

    h1 = soup.find("h1")
    if h1:
        data["vessel_name"] = h1.get_text(strip=True)

    # Ship type is rendered as an <h2> beneath the vessel name
    h2 = soup.find("h2")
    if h2:
        ship_type = h2.get_text(strip=True)
        if ship_type:
            data["ship_type_label"] = ship_type

    # "Info" section is a key-value table
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        key = cells[0].get_text(strip=True).lower()
        val = cells[1].get_text(strip=True)
        if not val or val == "---":
            continue
        if "flag" in key:
            # Value may be rendered as "Flag Marshall Is" — strip the prefix
            data["flag"] = val.removeprefix("Flag ").strip()
        elif key == "imo":
            data["imo"] = val
        elif "call" in key:
            data["call_sign"] = val
        elif key == "type":
            if val:
                data["ship_type_label"] = val
        elif key == "size":
            # "192 x 30 m" → take first number as length
            try:
                data["length_m"] = float(val.split()[0])
            except (ValueError, IndexError):
                pass
        elif key == "build":
            try:
                data["build_year"] = int(val[:4])
            except ValueError:
                pass

    return data if len(data) > 1 else None


def _scrape_itu(mmsi: int) -> Optional[dict]:
    """Attempt MMSI lookup via ITU MMSI database (form POST).

    Returns dict with vessel_name, call_sign, flag at minimum.
    Returns None on any failure.
    """
    url = "https://www.itu.int/mmsapp/ShipSearch.do"
    resp = requests.post(
        url,
        data={"maritimeId": str(mmsi), "action": "search"},
        timeout=_TIMEOUT,
        headers=_HEADERS,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    data: dict = {"source": "itu"}
    table = soup.find("table")
    if not table:
        return None

    for row in table.find_all("tr")[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) >= 3:
            data["vessel_name"] = cells[0].get_text(strip=True)
            data["call_sign"] = cells[1].get_text(strip=True)
            data["flag"] = cells[2].get_text(strip=True)
            break

    return data if len(data) > 1 else None


def _download_photo(photo_url: str, mmsi: int, photos_dir: Path) -> Optional[str]:
    """Download photo_url to photos_dir/<mmsi>.jpg.

    Returns the local file path string on success, None on failure.
    """
    resp = requests.get(photo_url, timeout=_TIMEOUT, headers=_HEADERS, stream=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "image" not in content_type:
        return None
    dest = photos_dir / f"{mmsi}.jpg"
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return str(dest)


def _process_one_ship(conn, mmsi: int, photos_dir: Path, attempt: int, max_attempts: int) -> None:
    """Enrich one ship: try scrapers, save result or increment fetch attempts."""
    logger.info("Enriching MMSI {} (attempt {}/{})", mmsi, attempt, max_attempts)
    data = _enrich_ship(mmsi, photos_dir)
    if data:
        if data.get("photo_url"):
            local_path = _download_photo(data["photo_url"], mmsi, photos_dir)
            if local_path:
                data["photo_path"] = local_path
        save_enrichment(conn, mmsi, data)
        write_event(conn, mmsi, EventType.ENRICHED,
                    f"New enrichment data for MMSI {mmsi}")
        name = data.get("vessel_name") or "no name found"
        logger.info("Enriched MMSI {} — '{}' (source: {})", mmsi, name, data.get("source"))
    else:
        increment_fetch_attempts(conn, mmsi)
        if attempt >= max_attempts:
            logger.warning("MMSI {}: all {} scrape attempts exhausted, giving up", mmsi, max_attempts)
        else:
            logger.info("MMSI {}: no data found this attempt ({} remaining)", mmsi, max_attempts - attempt)


def _enrich_ship(mmsi: int, photos_dir: Path) -> Optional[dict]:
    """Try each scrape source in priority order. Return first successful result, or None."""
    for scraper in (_scrape_shipxplorer, _scrape_myshiptracking, _scrape_marinetraffic, _scrape_itu):
        name = getattr(scraper, "__name__", repr(scraper))
        logger.debug("Trying {} for MMSI {}", name, mmsi)
        try:
            result = scraper(mmsi)
            if result:
                return result
            logger.debug("{}: no usable data for MMSI {}", name, mmsi)
        except Exception as exc:
            logger.debug("{} failed for MMSI {}: {}", name, mmsi, exc)
    return None


def main() -> None:
    """Service entry point. Loops forever enriching unenriched ships."""
    args = _build_parser().parse_args()
    configure_logging(args.verbose)

    photos_dir = Path(args.photos_dir)
    photos_dir.mkdir(parents=True, exist_ok=True)

    if args.reset_enrichment:
        competing = _find_competing_services()
        if competing:
            logger.error(
                "--reset-enrichment requires exclusive database access, but {} "
                "ShipsAhoy service(s) are still running:",
                len(competing),
            )
            for cmd in competing:
                logger.error("  {}", cmd)
            logger.error(
                "Run: sudo systemctl stop ships-ahoy.target  "
                "(then kill any remaining processes)"
            )
            sys.exit(1)

    conn = init_db(args.db)

    if not _check_db_writable(conn):
        logger.error(
            "Cannot acquire database write lock. "
            "Stop all other ShipsAhoy services before running with --reset-enrichment."
        )
        sys.exit(1)

    cfg = Config(conn)

    if args.reset_enrichment:
        _reset_enrichment(conn)

    logger.info("Enrichment service starting.")

    while True:
        try:
            max_attempts = cfg.enrichment_max_attempts
            delay = cfg.enrichment_delay_sec
            mmsi_list = get_unenriched_ships(conn, max_attempts)

            if not mmsi_list:
                logger.debug("No ships to enrich; sleeping {}s", delay)
                time.sleep(delay)
                continue

            logger.info("Enrichment batch starting: {} ships queued", len(mmsi_list))
            enriched_count = 0
            failed_count = 0

            for mmsi in mmsi_list:
                row = conn.execute(
                    "SELECT COALESCE(fetch_attempts, 0) FROM enrichment WHERE mmsi=?", (mmsi,)
                ).fetchone()
                attempt = (row[0] + 1) if row else 1
                try:
                    _process_one_ship(conn, mmsi, photos_dir, attempt, max_attempts)
                    # Check if enrichment succeeded (enriched flag set)
                    ship = conn.execute("SELECT enriched FROM ships WHERE mmsi=?", (mmsi,)).fetchone()
                    if ship and ship["enriched"]:
                        enriched_count += 1
                    else:
                        failed_count += 1
                except Exception:
                    logger.exception("Error enriching MMSI {}", mmsi)
                    failed_count += 1

                time.sleep(delay)

            logger.info(
                "Enrichment batch complete: {} enriched, {} failed/deferred",
                enriched_count, failed_count,
            )

        except KeyboardInterrupt:
            logger.info("Enrichment service stopped by user.")
            sys.exit(0)
        except Exception:
            logger.exception("Enrichment service outer loop error")
            time.sleep(5)


if __name__ == "__main__":
    main()
