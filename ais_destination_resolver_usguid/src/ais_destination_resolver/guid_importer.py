"""Import official USCG NAVCEN U.S. GUID CSV files."""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.request import urlretrieve

from .models import GuidLocation
from .uscg_route import normalize_guid

NAVCEN_GUID_LATLON_CSV_URL = (
    "https://navcen.uscg.gov/sites/default/files/doc/"
    "GUID-Sorted-By-Latitude-Longitude-Type-Name.csv"
)


def download_navcen_guid_csv(output_path: Path | str) -> Path:
    """Download the official NAVCEN GUID CSV to a local file.

    This function intentionally uses Python's standard library so the project
    does not need an extra HTTP dependency.
    """

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(NAVCEN_GUID_LATLON_CSV_URL, path)  # noqa: S310 - trusted official URL constant.
    return path


def load_guid_locations_from_csv(csv_path: Path | str) -> list[GuidLocation]:
    """Load USCG GUID locations from a NAVCEN-style CSV file.

    The official file currently uses columns similar to:
    ``GUID, UN LOCODE, Latitude, Longitude, Mile, Facility Type,
    Official Name, Port Name, Waterway Name``.
    Blank duplicate columns are ignored.
    """

    locations: list[GuidLocation] = []
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            guid_raw = _value(row, "GUID")
            if not guid_raw:
                continue

            full_code = normalize_guid(guid_raw)
            guid = full_code.removeprefix("US^")
            official_name = _value(row, "Official Name") or _value(row, "Name") or full_code

            locations.append(
                GuidLocation(
                    id=None,
                    guid=guid,
                    full_code=full_code,
                    unlocode=_value(row, "UN LOCODE") or _value(row, "UN/LOCODE"),
                    official_name=official_name,
                    port_name=_value(row, "Port Name"),
                    waterway_name=_value(row, "Waterway Name") or _value(row, "Waterway"),
                    facility_type=_value(row, "Facility Type") or _value(row, "Type"),
                    latitude=_optional_float(_value(row, "Latitude")),
                    longitude=_optional_float(_value(row, "Longitude")),
                    mile=_optional_float(_value(row, "Mile")),
                    source="USCG NAVCEN GUID CSV",
                    source_updated=None,
                    notes=None,
                )
            )
    return locations


def _value(row: dict[str, str | None], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None
