# AIS Destination Resolver

A local Python/SQLite tool for resolving noisy AIS destination/origination text into U.S. inland waterway destinations.

The project supports two related problems:

1. Plain-text destination matching, such as `MEMPHIS`, `NOLA`, `CAIRO IL`, or `PADUCAH`.
2. USCG AIS route-code parsing, such as `US^084Y>0WQB` or `USCIR<>USCIR`.

The second case is important for inland towboats and pushboats. Those strings are commonly U.S. Geographic Unique ID codes, also called **US/GUIDs**, published by USCG NAVCEN.

## What the USCG route strings mean

Examples:

```text
US^084Y>0WQB
USCIR<>USCIR
USL7A>USCIR
```

The parser treats these as route-style AIS destination fields:

| Pattern | Meaning |
|---|---|
| `US^084Y` | One U.S. GUID endpoint |
| `US^084Y>0WQB` | Origin GUID `US^084Y` to destination GUID `US^0WQB` |
| `USCIR<>USCIR` | Operating within/around one UN/LOCODE area |
| `USL7A>USCIR` | UN/LOCODE origin to UN/LOCODE destination |

The second GUID in a route may omit the `US^` prefix. The resolver restores it automatically.

## Official source for GUID decoding

Use the official USCG NAVCEN AIS Encoding Guide and U.S. Destination Codes page:

```text
https://www.navcen.uscg.gov/contact/ais_encoding_guide
```

The CSV this project expects is the NAVCEN U.S. GUID listing, currently named similar to:

```text
GUID-Sorted-By-Latitude-Longitude-Type-Name.csv
```

## Install

This project uses `uv`.

```bash
uv sync
```

## Initialize the database

```bash
uv run ais-dest init-db
```

This loads the starter inland destination dictionary.

## Download and import the official USCG GUID CSV

```bash
uv run ais-dest download-guid-csv
uv run ais-dest import-guid-csv data/sources/GUID-Sorted-By-Latitude-Longitude-Type-Name.csv
```

If the download command fails because the machine has no internet access, manually download the CSV from NAVCEN and run only the import command.

## Resolve a plain destination

```bash
uv run ais-dest resolve "NOLA"
uv run ais-dest resolve "CAIRO IL"
```

## Resolve a USCG route-style AIS field

```bash
uv run ais-dest resolve-route "US^084Y>0WQB"
uv run ais-dest resolve-route "USCIR<>USCIR"
```

Without the NAVCEN GUID CSV imported, the tool can still parse GUID strings but cannot decode the GUIDs to facility names.

## Resolve your undecoded sample CSV

The project includes a small example file:

```bash
uv run ais-dest resolve-route-csv examples/undecoded_strings.csv --out route_matches.csv
```

For your real file, make sure it has either a `raw_ais_destination` column or pass the column name explicitly:

```bash
uv run ais-dest resolve-route-csv my_ais.csv --destination-column raw_ais_destination --out route_matches.csv
```

The output adds fields such as:

```text
route_type
route_separator
origin_code
origin_name
origin_port
origin_waterway
origin_mile
destination_code
destination_name
destination_port
destination_waterway
destination_mile
route_notes
```

## Database tables

### `inland_destinations`

Starter dictionary for known inland waterway cities, ports, and route aliases.

### `us_guid_locations`

Official USCG GUID lookup table after importing the NAVCEN CSV.

Important columns:

```text
guid
full_code
unlocode
official_name
port_name
waterway_name
facility_type
latitude
longitude
mile
```

### `ais_destination_matches`

Historical log table for observed plain-text destination matches.

## Tests

```bash
uv run pytest
```

## Notes

The included `data/seeds/sample_guid_locations.csv` is only a schema/example file for development. It is not an authoritative decoder. Use the official NAVCEN CSV for real AIS decoding.
