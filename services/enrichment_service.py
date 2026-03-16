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
from ships_ahoy.db import init_db, get_unenriched_ships, save_enrichment, write_event
from ships_ahoy.events import EventType

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "ships.db"
DEFAULT_PHOTOS_DIR = "static/photos"


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
    raise NotImplementedError


def _scrape_marinetraffic(mmsi: int) -> Optional[dict]:
    """Attempt to scrape vessel data from MarineTraffic public pages.

    May return 403 or Cloudflare challenge — returns None on any failure.
    Returns same dict shape as _scrape_shipxplorer.
    """
    raise NotImplementedError


def _scrape_itu(mmsi: int) -> Optional[dict]:
    """Attempt MMSI lookup via ITU MMSI database (form POST).

    Returns dict with vessel_name, call_sign, flag at minimum.
    Returns None on any failure.
    """
    raise NotImplementedError


def _download_photo(photo_url: str, mmsi: int, photos_dir: Path) -> Optional[str]:
    """Download photo_url to photos_dir/<mmsi>.jpg.

    Returns the local file path string on success, None on failure.
    """
    raise NotImplementedError


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
                        save_enrichment(conn, mmsi, {})
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
