"""Command-line interface for the AIS destination resolver."""

from __future__ import annotations

import csv
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .db import initialize_database, load_destinations, load_guid_locations, record_match, upsert_destinations, upsert_guid_locations
from .guid_importer import download_navcen_guid_csv, load_guid_locations_from_csv
from .resolver import DestinationResolver
from .seeds import DEFAULT_SEED_PATH, load_seed_destinations

app = typer.Typer(help="Resolve AIS destination text to U.S. inland-waterway destinations.")
console = Console()


@app.command("init-db")
def init_db(
    db: Path = typer.Option(Path("data/inland_ports.db"), help="SQLite database path."),
    seed: Path = typer.Option(DEFAULT_SEED_PATH, help="Seed CSV path."),
) -> None:
    """Create the database and load starter inland destinations."""

    initialize_database(db)
    destinations = load_seed_destinations(seed)
    count = upsert_destinations(db, destinations)
    console.print(f"Initialized {db} with {count} destinations.")


@app.command("resolve")
def resolve_one(
    destination: str = typer.Argument(..., help="Raw AIS destination text."),
    db: Path = typer.Option(Path("data/inland_ports.db"), help="SQLite database path."),
    mmsi: str | None = typer.Option(None, help="Optional MMSI to record with the match."),
    lat: float | None = typer.Option(None, help="Optional observed vessel latitude."),
    lon: float | None = typer.Option(None, help="Optional observed vessel longitude."),
    observed_at: str | None = typer.Option(None, help="Optional observation timestamp."),
    record: bool = typer.Option(True, help="Record the match in SQLite."),
) -> None:
    """Resolve a single AIS destination string."""

    resolver = DestinationResolver(load_destinations(db), load_guid_locations(db))
    match = resolver.resolve(destination, latitude=lat, longitude=lon)
    if record:
        record_match(db, match, mmsi=mmsi, latitude=lat, longitude=lon, observed_at=observed_at)
    _print_match(match)


@app.command("resolve-csv")
def resolve_csv(
    input_csv: Path = typer.Argument(..., help="Input CSV containing a destination column."),
    db: Path = typer.Option(Path("data/inland_ports.db"), help="SQLite database path."),
    out: Path = typer.Option(Path("matches.csv"), help="Output CSV path."),
    destination_column: str = typer.Option("destination", help="Destination column name."),
) -> None:
    """Resolve AIS destination text from a CSV file."""

    resolver = DestinationResolver(load_destinations(db), load_guid_locations(db))
    out.parent.mkdir(parents=True, exist_ok=True)
    with input_csv.open("r", encoding="utf-8", newline="") as input_file, out.open(
        "w", encoding="utf-8", newline=""
    ) as output_file:
        reader = csv.DictReader(input_file)
        fieldnames = [
            *(reader.fieldnames or []),
            "matched_locode",
            "matched_name",
            "matched_state",
            "matched_waterway",
            "matched_river_mile",
            "confidence",
            "match_method",
            "ambiguous",
        ]
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            lat = _optional_float(row.get("lat"))
            lon = _optional_float(row.get("lon"))
            match = resolver.resolve(row.get(destination_column, ""), latitude=lat, longitude=lon)
            record_match(
                db,
                match,
                mmsi=row.get("mmsi"),
                latitude=lat,
                longitude=lon,
                observed_at=row.get("timestamp"),
            )
            destination = match.destination
            row.update(
                {
                    "matched_locode": destination.locode if destination else "",
                    "matched_name": destination.canonical_name if destination else "",
                    "matched_state": destination.state if destination else "",
                    "matched_waterway": destination.waterway if destination else "",
                    "matched_river_mile": destination.river_mile if destination else "",
                    "confidence": match.confidence,
                    "match_method": match.match_method,
                    "ambiguous": match.ambiguous,
                }
            )
            writer.writerow(row)
    console.print(f"Wrote {out}")






@app.command("resolve-route-csv")
def resolve_route_csv(
    input_csv: Path = typer.Argument(..., help="Input CSV containing AIS route/destination fields."),
    db: Path = typer.Option(Path("data/inland_ports.db"), help="SQLite database path."),
    out: Path = typer.Option(Path("route_matches.csv"), help="Output CSV path."),
    destination_column: str = typer.Option("raw_ais_destination", help="Destination column name."),
) -> None:
    """Resolve route-style AIS destination strings from a CSV file."""

    resolver = DestinationResolver(load_destinations(db), load_guid_locations(db))
    out.parent.mkdir(parents=True, exist_ok=True)
    with input_csv.open("r", encoding="utf-8", newline="") as input_file, out.open(
        "w", encoding="utf-8", newline=""
    ) as output_file:
        reader = csv.DictReader(input_file)
        fieldnames = [
            *(reader.fieldnames or []),
            "route_type",
            "route_separator",
            "route_confidence",
            "origin_code",
            "origin_type",
            "origin_name",
            "origin_port",
            "origin_waterway",
            "origin_mile",
            "destination_code",
            "destination_type",
            "destination_name",
            "destination_port",
            "destination_waterway",
            "destination_mile",
            "route_notes",
        ]
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            raw_value = row.get(destination_column) or row.get("ticker_destination") or ""
            route = resolver.resolve_route(raw_value)
            origin = route.endpoints[0] if route.endpoints else None
            destination_endpoint = route.endpoints[1] if len(route.endpoints) > 1 else None
            row.update(
                {
                    "route_type": route.route_type,
                    "route_separator": route.separator or "",
                    "route_confidence": route.confidence,
                    "origin_code": origin.normalized if origin else "",
                    "origin_type": origin.endpoint_type if origin else "",
                    "origin_name": _endpoint_name(origin),
                    "origin_port": _endpoint_port(origin),
                    "origin_waterway": _endpoint_waterway(origin),
                    "origin_mile": _endpoint_mile(origin),
                    "destination_code": destination_endpoint.normalized if destination_endpoint else "",
                    "destination_type": destination_endpoint.endpoint_type if destination_endpoint else "",
                    "destination_name": _endpoint_name(destination_endpoint),
                    "destination_port": _endpoint_port(destination_endpoint),
                    "destination_waterway": _endpoint_waterway(destination_endpoint),
                    "destination_mile": _endpoint_mile(destination_endpoint),
                    "route_notes": route.notes or "",
                }
            )
            writer.writerow(row)
    console.print(f"Wrote {out}")


@app.command("download-guid-csv")
def download_guid_csv(
    out: Path = typer.Option(
        Path("data/sources/GUID-Sorted-By-Latitude-Longitude-Type-Name.csv"),
        help="Where to save the official NAVCEN GUID CSV.",
    ),
) -> None:
    """Download the official USCG NAVCEN U.S. GUID CSV."""

    path = download_navcen_guid_csv(out)
    console.print(f"Downloaded NAVCEN GUID CSV to {path}")


@app.command("import-guid-csv")
def import_guid_csv(
    csv_path: Path = typer.Argument(..., help="NAVCEN GUID CSV path."),
    db: Path = typer.Option(Path("data/inland_ports.db"), help="SQLite database path."),
) -> None:
    """Import USCG U.S. GUID locations into SQLite."""

    initialize_database(db)
    locations = load_guid_locations_from_csv(csv_path)
    count = upsert_guid_locations(db, locations)
    console.print(f"Imported {count} GUID locations into {db}.")


@app.command("resolve-route")
def resolve_route(
    destination: str = typer.Argument(..., help="Raw AIS route/destination text."),
    db: Path = typer.Option(Path("data/inland_ports.db"), help="SQLite database path."),
) -> None:
    """Resolve a route-style AIS field such as US^084Y>0WQB."""

    resolver = DestinationResolver(load_destinations(db), load_guid_locations(db))
    route = resolver.resolve_route(destination)
    _print_route(route)


@app.command("list-destinations")
def list_destinations(
    db: Path = typer.Option(Path("data/inland_ports.db"), help="SQLite database path."),
    waterway: str | None = typer.Option(None, help="Filter by waterway substring."),
) -> None:
    """Display destinations in a sortable-friendly table."""

    destinations = load_destinations(db)
    if waterway:
        waterway_upper = waterway.upper()
        destinations = [
            destination
            for destination in destinations
            if destination.waterway and waterway_upper in destination.waterway.upper()
        ]

    table = Table(title="Inland AIS Destinations")
    for column in ["LOCODE", "Name", "State", "Waterway", "River Mile", "Lat", "Lon", "Status"]:
        table.add_column(column)
    for destination in destinations:
        table.add_row(
            destination.locode or "",
            destination.canonical_name,
            destination.state or "",
            destination.waterway or "",
            "" if destination.river_mile is None else f"{destination.river_mile:.1f}",
            "" if destination.latitude is None else f"{destination.latitude:.5f}",
            "" if destination.longitude is None else f"{destination.longitude:.5f}",
            destination.status or "",
        )
    console.print(table)


def _print_match(match) -> None:
    table = Table(title="AIS Destination Match")
    table.add_column("Field")
    table.add_column("Value")
    destination = match.destination
    table.add_row("Raw", match.raw_destination)
    table.add_row("Normalized", match.normalized_destination)
    table.add_row("Matched", destination.canonical_name if destination else "")
    table.add_row("LOCODE", destination.locode if destination and destination.locode else "")
    table.add_row("State", destination.state if destination and destination.state else "")
    table.add_row("Waterway", destination.waterway if destination and destination.waterway else "")
    table.add_row("River Mile", str(destination.river_mile) if destination else "")
    table.add_row("Confidence", str(match.confidence))
    table.add_row("Method", match.match_method)
    table.add_row("Ambiguous", str(match.ambiguous))
    if match.notes:
        table.add_row("Notes", match.notes)
    console.print(table)

    if match.alternatives:
        alt_table = Table(title="Alternatives")
        alt_table.add_column("Name")
        alt_table.add_column("Score")
        alt_table.add_column("Waterway")
        for destination, score in match.alternatives:
            alt_table.add_row(destination.canonical_name, f"{score:.3f}", destination.waterway or "")
        console.print(alt_table)




def _print_route(route) -> None:
    table = Table(title="AIS Route Resolution")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Raw", route.raw_destination)
    table.add_row("Normalized", route.normalized_destination)
    table.add_row("Separator", route.separator or "")
    table.add_row("Route Type", route.route_type)
    table.add_row("Confidence", str(route.confidence))
    if route.notes:
        table.add_row("Notes", route.notes)
    console.print(table)

    endpoint_table = Table(title="Endpoints")
    for column in ["Raw", "Normalized", "Type", "Resolved Name", "Port", "Waterway", "Mile", "Lat", "Lon", "Confidence", "Notes"]:
        endpoint_table.add_column(column)

    for endpoint in route.endpoints:
        location = endpoint.guid_location
        destination = endpoint.destination
        endpoint_table.add_row(
            endpoint.raw,
            endpoint.normalized,
            endpoint.endpoint_type,
            location.official_name if location else (destination.canonical_name if destination else ""),
            location.port_name if location else "",
            location.waterway_name if location else (destination.waterway if destination else ""),
            _format_optional_float(location.mile if location else (destination.river_mile if destination else None)),
            _format_optional_float(location.latitude if location else (destination.latitude if destination else None)),
            _format_optional_float(location.longitude if location else (destination.longitude if destination else None)),
            str(endpoint.confidence),
            endpoint.notes or "",
        )
    console.print(endpoint_table)



def _endpoint_name(endpoint) -> str:
    if endpoint is None:
        return ""
    if endpoint.guid_location:
        return endpoint.guid_location.official_name
    if endpoint.destination:
        return endpoint.destination.canonical_name
    return ""


def _endpoint_port(endpoint) -> str:
    if endpoint is None or endpoint.guid_location is None:
        return ""
    return endpoint.guid_location.port_name or ""


def _endpoint_waterway(endpoint) -> str:
    if endpoint is None:
        return ""
    if endpoint.guid_location:
        return endpoint.guid_location.waterway_name or ""
    if endpoint.destination:
        return endpoint.destination.waterway or ""
    return ""


def _endpoint_mile(endpoint) -> str:
    if endpoint is None:
        return ""
    if endpoint.guid_location:
        return _format_optional_float(endpoint.guid_location.mile)
    if endpoint.destination:
        return _format_optional_float(endpoint.destination.river_mile)
    return ""


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.5f}"


def _optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
