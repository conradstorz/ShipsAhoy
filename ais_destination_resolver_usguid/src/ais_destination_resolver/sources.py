"""Import stubs for official UNECE, USACE, and NOAA data sources.

These functions intentionally avoid guessing field mappings. They provide the integration points for the next step: loading official upstream files into the same Destination model.
"""

from __future__ import annotations

from pathlib import Path

from .models import Destination


def import_unece_unlocode_csv(_path: Path | str) -> list[Destination]:
    """Import UNECE UN/LOCODE CSV data.

    Use this for the official UN/LOCODE country or full-release CSV files. The importer should:

    - filter country code `US`
    - retain rows whose Function field contains water transport marker `1`
    - preserve UNECE status and coordinate values
    - later classify coastal vs inland using USACE/NOAA overlays
    """

    raise NotImplementedError("UNECE importer is a planned integration point.")


def import_usace_navigation_facilities(_path: Path | str) -> list[Destination]:
    """Import USACE Navigation Infrastructure / Navigation Facilities data.

    Use this for docks, anchorages, fleeting areas, river miles, waterway names, port polygons,
    waterway links, and related inland navigation features.
    """

    raise NotImplementedError("USACE importer is a planned integration point.")


def import_noaa_inland_enc(_path: Path | str) -> list[Destination]:
    """Import NOAA/USACE Inland ENC-derived features.

    Use this for geospatial waterway context and later geofence matching.
    """

    raise NotImplementedError("NOAA/IENC importer is a planned integration point.")
