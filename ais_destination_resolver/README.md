# AIS Destination Resolver

This project resolves messy AIS destination text such as `NOLA`, `ST LOUIS`, `PADUCAH KY`, or `LOUISVILLE` into structured U.S. inland-waterway destinations.

It is intentionally separate from MMSI vessel identity lookup. The first job is to determine likely departure and destination points from AIS broadcast text and position context. A later tool can enrich MMSI values with vessel owner/name/type data.

## Data Sources

Authoritative upstream sources to integrate:

- UNECE UN/LOCODE, latest official publication: 2025-1.
- USACE Navigation Infrastructure / Navigation Facilities for docks, fleeting areas, river-mile markers, port polygons, waterway links, and inland navigation points.
- NOAA ENC and Inland ENC data for navigational geography.

This starter version includes a hand-curated seed file focused on common inland river destinations. The importer structure is designed so official UNECE/USACE/NOAA files can be added without changing the resolver API.

## Install

```bash
uv sync --extra dev
```

## Build the SQLite database

```bash
uv run ais-dest init-db --db data/inland_ports.db
```

## Resolve one destination

```bash
uv run ais-dest resolve "NOLA" --db data/inland_ports.db
uv run ais-dest resolve "ST LOUIS" --mmsi 367123456 --lat 38.62 --lon -90.18 --db data/inland_ports.db
```

## Batch resolve a CSV

Input CSV columns may include:

- `mmsi`
- `destination`
- `lat`
- `lon`
- `timestamp`

```bash
uv run ais-dest resolve-csv examples/ais_messages.csv --db data/inland_ports.db --out matches.csv
```

## List destinations

```bash
uv run ais-dest list-destinations --db data/inland_ports.db
uv run ais-dest list-destinations --db data/inland_ports.db --waterway "Ohio River"
```

## Project Layout

```text
src/ais_destination_resolver/
    cli.py              Typer CLI
    db.py               SQLite schema and persistence
    models.py           Dataclasses for destinations and matches
    normalizer.py       AIS text cleanup and alias normalization
    resolver.py         Matching logic and confidence scoring
    seeds.py            Seed-data loader
    sources.py          Stubs for UNECE/USACE/NOAA importers

data/seeds/inland_destinations.csv
    Starter inland destination dictionary
```

## Matching Strategy

The resolver uses:

1. Exact normalized alias match
2. Fuzzy alias/canonical-name match
3. Optional position proximity boost
4. Ambiguity reporting when multiple candidates are close

AIS destination text is often abbreviated, misspelled, stale, or operator-specific. For that reason, every result includes confidence and match method.

## Next Iteration: MMSI Lookup

A later tool can add a `vessels` table:

```sql
CREATE TABLE vessels (
    mmsi TEXT PRIMARY KEY,
    vessel_name TEXT,
    imo TEXT,
    call_sign TEXT,
    vessel_type TEXT,
    dimensions TEXT,
    source TEXT,
    last_seen_at TEXT
);
```

That tool should enrich MMSI identity, while this project remains responsible for resolving broadcast destination intent.
