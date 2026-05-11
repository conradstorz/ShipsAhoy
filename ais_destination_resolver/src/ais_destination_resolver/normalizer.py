"""Normalize messy AIS destination text before matching."""

from __future__ import annotations

import re
import unicodedata

_DIRECTION_WORDS = {
    "TO",
    "FOR",
    "DEST",
    "DESTINATION",
    "BOUND",
    "BND",
    "VIA",
    "ETA",
    "TOW",
    "TOWING",
}

_STATE_SUFFIXES = {
    "AL",
    "AR",
    "IL",
    "IN",
    "IA",
    "KY",
    "LA",
    "MN",
    "MO",
    "MS",
    "OH",
    "OK",
    "PA",
    "TN",
    "WV",
    "NE",
    "OR",
    "ID",
}


def normalize_destination(value: str | None, *, keep_state: bool = True) -> str:
    """Return a normalized AIS destination string.

    :param value: Raw AIS destination text.
    :param keep_state: Whether two-letter state suffixes should be preserved.
    :return: Uppercase normalized destination text.
    """

    if not value:
        return ""

    text = unicodedata.normalize("NFKD", value)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper().strip()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    tokens = []
    for token in text.split():
        if token in _DIRECTION_WORDS:
            continue
        if not keep_state and token in _STATE_SUFFIXES:
            continue
        tokens.append(token)

    return " ".join(tokens)


def alias_variants(value: str) -> set[str]:
    """Return practical variants for a normalized alias.

    :param value: Canonical or alias text.
    :return: Set of searchable normalized variants.
    """

    normalized = normalize_destination(value)
    variants = {normalized}
    no_state = normalize_destination(value, keep_state=False)
    if no_state:
        variants.add(no_state)

    variants.add(normalized.replace("SAINT", "ST"))
    variants.add(normalized.replace("ST", "SAINT"))
    variants.add(normalized.replace("PORT OF ", ""))

    return {variant for variant in variants if variant}
