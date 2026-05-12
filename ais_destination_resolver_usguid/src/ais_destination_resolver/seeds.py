"""Seed-data loading helpers."""

from __future__ import annotations

import csv
from pathlib import Path

from .models import Destination

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "seeds" / "inland_destinations.csv"


def _float_or_none(value: str) -> float | None:
    if value == "" or value is None:
        return None
    return float(value)


def load_seed_destinations(seed_path: Path | str = DEFAULT_SEED_PATH) -> list[Destination]:
    """Load starter inland destinations from CSV."""

    path = Path(seed_path)
    destinations: list[Destination] = []
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            aliases = [alias.strip() for alias in row["aliases"].split("|") if alias.strip()]
            destinations.append(
                Destination(
                    id=None,
                    locode=row.get("locode") or None,
                    canonical_name=row["canonical_name"],
                    aliases=aliases,
                    state=row.get("state") or None,
                    country_code=row.get("country_code") or "US",
                    waterway=row.get("waterway") or None,
                    river_mile=_float_or_none(row.get("river_mile", "")),
                    latitude=_float_or_none(row.get("latitude", "")),
                    longitude=_float_or_none(row.get("longitude", "")),
                    destination_type=row.get("destination_type") or "unknown",
                    status=row.get("status") or None,
                    source=row.get("source") or "manual_seed",
                    source_updated=row.get("source_updated") or None,
                    is_active=row.get("is_active", "1") == "1",
                    notes=row.get("notes") or None,
                )
            )
    return destinations
