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
2. MarineTraffic (may block): https://www.marinetraffic.com/en/ais/details/ships/mmsi:<mmsi>
3. ITU MMSI lookup (form POST): https://www.itu.int/mmsapp/ShipSearch.do

HTTP client: requests + BeautifulSoup (html.parser)

Usage::

    uv run python services/enrichment_service.py [--db PATH] [--photos-dir DIR] [--verbose]
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ships_ahoy.config import Config
from ships_ahoy.db import init_db, get_unenriched_ships, increment_fetch_attempts, save_enrichment, write_event
from ships_ahoy.events import EventType

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "ships.db"
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
    return parser


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


def _enrich_ship(mmsi: int, photos_dir: Path) -> Optional[dict]:
    """Try each scrape source in priority order. Return first successful result, or None."""
    for scraper in (_scrape_shipxplorer, _scrape_marinetraffic, _scrape_itu):
        try:
            result = scraper(mmsi)
            if result:
                return result
        except Exception:
            logger.debug("Scraper %s failed for MMSI %d", scraper.__name__, mmsi)
    return None


def main() -> None:
    """Service entry point. Loops forever enriching unenriched ships."""
    args = _build_parser().parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    photos_dir = Path(args.photos_dir)
    photos_dir.mkdir(parents=True, exist_ok=True)

    conn = init_db(args.db)
    cfg = Config(conn)

    logger.info("Enrichment service starting.")

    while True:
        try:
            max_attempts = cfg.enrichment_max_attempts
            delay = cfg.enrichment_delay_sec
            mmsi_list = get_unenriched_ships(conn, max_attempts)

            if not mmsi_list:
                time.sleep(delay)
                continue

            for mmsi in mmsi_list:
                try:
                    data = _enrich_ship(mmsi, photos_dir)
                    if data:
                        if data.get("photo_url"):
                            local_path = _download_photo(data["photo_url"], mmsi, photos_dir)
                            if local_path:
                                data["photo_path"] = local_path
                        save_enrichment(conn, mmsi, data)
                        write_event(conn, mmsi, EventType.ENRICHED,
                                    f"New enrichment data for MMSI {mmsi}")
                        logger.info("Enriched MMSI %d from %s", mmsi, data.get("source"))
                    else:
                        increment_fetch_attempts(conn, mmsi)
                        logger.debug("No data found for MMSI %d", mmsi)
                except Exception:
                    logger.exception("Error enriching MMSI %d", mmsi)

                time.sleep(delay)

        except KeyboardInterrupt:
            logger.info("Enrichment service stopped by user.")
            sys.exit(0)
        except Exception:
            logger.exception("Enrichment service outer loop error")
            time.sleep(5)


if __name__ == "__main__":
    main()
