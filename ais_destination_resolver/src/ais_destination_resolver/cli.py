"""Command-line interface for the AIS destination resolver."""

from __future__ import annotations

import csv
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .db import initialize_database, load_destinations, record_match, upsert_destinations
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

    resolver = DestinationResolver(load_destinations(db))
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

    resolver = DestinationResolver(load_destinations(db))
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


def _optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
