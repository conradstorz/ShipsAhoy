"""USCG/NAIS inland waterway code lookup.

Translates 4-character USCG location codes (e.g. "0TNR") to plain-text
waterway/place names before fuzzy matching.  The mapping is loaded once from
the bundled CSV at import time.
"""

from __future__ import annotations

import csv
from importlib import resources
from pathlib import Path

# ---------------------------------------------------------------------------
# Default data file – bundled alongside the package data directory.
# ---------------------------------------------------------------------------
_DEFAULT_CSV = Path(__file__).parent.parent.parent / "data" / "uscg_waterway_codes.csv"

# Module-level cache: upper-cased code → plain text name
_CODE_MAP: dict[str, str] = {}
_loaded = False


def _load(path: Path | str | None = None) -> None:
    global _loaded
    csv_path = Path(path) if path else _DEFAULT_CSV
    if not csv_path.exists():
        _loaded = True
        return
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            code = row.get("code", "").strip().upper()
            name = row.get("name", "").strip()
            if code and name:
                _CODE_MAP[code] = name
    _loaded = True


def translate_uscg_code(code: str) -> str | None:
    """Return the plain-text name for a USCG waterway code, or *None*.

    :param code: Raw code string, e.g. ``"0TNR"`` or ``"US0TNR"``.
    :return: Human-readable name, e.g. ``"Tennessee River"``, or ``None`` if
        the code is not in the lookup table.
    """
    if not _loaded:
        _load()

    upper = code.strip().upper()

    # Accept both bare code ("0TNR") and prefixed form ("US0TNR").
    if upper in _CODE_MAP:
        return _CODE_MAP[upper]
    # Strip a leading 2-character country prefix and retry.
    if len(upper) > 2:
        bare = upper[2:]
        if bare in _CODE_MAP:
            return _CODE_MAP[bare]
    return None


def reload(path: Path | str | None = None) -> None:
    """Reload the USCG code map from *path* (or the default CSV).

    Useful for testing and for adding codes at runtime.
    """
    global _loaded
    _CODE_MAP.clear()
    _loaded = False
    _load(path)
