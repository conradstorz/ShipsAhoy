"""Resolve AIS destination text to inland-waterway destination records."""

from __future__ import annotations

import math

from rapidfuzz import fuzz, process

from .models import Destination, GuidLocation, MatchResult, RouteEndpoint, RouteResolution
from .normalizer import alias_variants, normalize_destination
from .uscg_route import parse_ais_route


def haversine_miles(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return approximate great-circle distance in statute miles."""

    radius_miles = 3958.7613
    phi_a = math.radians(latitude_a)
    phi_b = math.radians(latitude_b)
    delta_phi = math.radians(latitude_b - latitude_a)
    delta_lambda = math.radians(longitude_b - longitude_a)
    component = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_miles * math.asin(math.sqrt(component))


class DestinationResolver:
    """Resolve noisy AIS destination strings against a destination dictionary."""

    def __init__(
        self,
        destinations: list[Destination],
        guid_locations: list[GuidLocation] | None = None,
    ) -> None:
        """Build lookup indexes for destination and US/GUID resolution."""

        self.destinations = destinations
        self.guid_locations = guid_locations or []
        self.guid_to_location = {location.full_code: location for location in self.guid_locations}
        self.guid_to_location.update({location.guid: location for location in self.guid_locations})
        self.alias_to_destination: dict[str, Destination] = {}
        self.search_choices: dict[str, Destination] = {}

        for destination in destinations:
            values = [destination.canonical_name, *(destination.aliases or [])]
            if destination.locode:
                values.append(destination.locode)
            for value in values:
                for variant in alias_variants(value):
                    self.alias_to_destination.setdefault(variant, destination)
                    self.search_choices.setdefault(variant, destination)

    def resolve(
        self,
        raw_destination: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        limit: int = 5,
    ) -> MatchResult:
        """Resolve one raw AIS destination string.

        :param raw_destination: Raw destination field from AIS.
        :param latitude: Optional vessel latitude for proximity scoring.
        :param longitude: Optional vessel longitude for proximity scoring.
        :param limit: Number of alternatives to keep.
        :return: Best match result with alternatives.
        """

        normalized = normalize_destination(raw_destination)
        if not normalized:
            return MatchResult(
                raw_destination=raw_destination,
                normalized_destination=normalized,
                destination=None,
                confidence=0.0,
                match_method="empty",
                ambiguous=False,
                alternatives=[],
                notes="No destination text was provided.",
            )

        exact_destination = self.alias_to_destination.get(normalized)
        if exact_destination is not None:
            confidence = self._position_adjusted_score(100.0, exact_destination, latitude, longitude)
            return MatchResult(
                raw_destination=raw_destination,
                normalized_destination=normalized,
                destination=exact_destination,
                confidence=round(confidence / 100, 3),
                match_method="exact_alias",
                ambiguous=False,
                alternatives=[],
            )

        matches = process.extract(
            normalized,
            self.search_choices.keys(),
            scorer=fuzz.WRatio,
            limit=max(limit * 3, 10),
        )

        scored: list[tuple[Destination, float]] = []
        seen_ids: set[int | str] = set()
        for _choice, score, index in matches:
            # RapidFuzz can return either key by value or positional index depending on version.
            choice = list(self.search_choices.keys())[index] if isinstance(index, int) else _choice
            destination = self.search_choices[choice]
            destination_key = destination.id or destination.locode or destination.canonical_name
            if destination_key in seen_ids:
                continue
            seen_ids.add(destination_key)
            adjusted = self._position_adjusted_score(float(score), destination, latitude, longitude)
            scored.append((destination, adjusted))

        scored.sort(key=lambda item: item[1], reverse=True)
        alternatives = scored[:limit]
        if not alternatives:
            return MatchResult(
                raw_destination=raw_destination,
                normalized_destination=normalized,
                destination=None,
                confidence=0.0,
                match_method="no_match",
                ambiguous=False,
                alternatives=[],
            )

        best_destination, best_score = alternatives[0]
        ambiguous = len(alternatives) > 1 and (best_score - alternatives[1][1]) < 5.0
        if best_score < 65.0:
            return MatchResult(
                raw_destination=raw_destination,
                normalized_destination=normalized,
                destination=None,
                confidence=round(best_score / 100, 3),
                match_method="low_confidence_fuzzy",
                ambiguous=ambiguous,
                alternatives=alternatives,
                notes="Best candidate was below the acceptance threshold.",
            )

        return MatchResult(
            raw_destination=raw_destination,
            normalized_destination=normalized,
            destination=best_destination,
            confidence=round(best_score / 100, 3),
            match_method="fuzzy_alias",
            ambiguous=ambiguous,
            alternatives=alternatives[1:],
        )

    def _position_adjusted_score(
        self,
        base_score: float,
        destination: Destination,
        latitude: float | None,
        longitude: float | None,
    ) -> float:
        """Apply a small position-context adjustment to a text score."""

        if (
            latitude is None
            or longitude is None
            or destination.latitude is None
            or destination.longitude is None
        ):
            return base_score

        distance = haversine_miles(latitude, longitude, destination.latitude, destination.longitude)
        proximity_bonus = max(0.0, 8.0 - (distance / 25.0))
        adjusted = min(100.0, base_score + proximity_bonus)
        return adjusted


    def resolve_route(
        self,
        raw_destination: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> RouteResolution:
        """Resolve a route-style AIS destination/origination string.

        This handles examples such as ``US^084Y>0WQB`` and ``USCIR<>USCIR``.
        U.S. GUID endpoints are looked up in ``us_guid_locations``. UN/LOCODE
        and plain-text endpoints fall back to the existing destination resolver.
        """

        parsed = parse_ais_route(raw_destination)
        endpoints: list[RouteEndpoint] = []
        endpoint_scores: list[float] = []
        notes: list[str] = []

        for token in parsed.tokens:
            if token.token_type == "us_guid":
                location = self.guid_to_location.get(token.normalized) or self.guid_to_location.get(
                    token.normalized.removeprefix("US^")
                )
                confidence = 1.0 if location else 0.0
                endpoint_scores.append(confidence)
                if location is None:
                    notes.append(f"No GUID lookup row for {token.normalized}.")
                endpoints.append(
                    RouteEndpoint(
                        raw=token.raw,
                        normalized=token.normalized,
                        endpoint_type="us_guid",
                        guid_location=location,
                        destination=None,
                        confidence=confidence,
                        notes=None if location else "GUID parsed but not found in lookup table.",
                    )
                )
                continue

            if token.token_type in {"unlocode", "text"}:
                match = self.resolve(token.normalized, latitude=latitude, longitude=longitude)
                endpoint_scores.append(match.confidence)
                endpoints.append(
                    RouteEndpoint(
                        raw=token.raw,
                        normalized=token.normalized,
                        endpoint_type=token.token_type,
                        guid_location=None,
                        destination=match.destination,
                        confidence=match.confidence,
                        notes=match.notes,
                    )
                )
                continue

            endpoints.append(
                RouteEndpoint(
                    raw=token.raw,
                    normalized=token.normalized,
                    endpoint_type=token.token_type,
                    guid_location=None,
                    destination=None,
                    confidence=0.0,
                    notes="Empty or unhandled endpoint token.",
                )
            )
            endpoint_scores.append(0.0)

        confidence = round(sum(endpoint_scores) / len(endpoint_scores), 3) if endpoint_scores else 0.0
        if parsed.notes:
            notes.append(parsed.notes)

        return RouteResolution(
            raw_destination=raw_destination,
            normalized_destination=parsed.normalized_destination,
            separator=parsed.separator,
            route_type=parsed.route_type,
            endpoints=endpoints,
            confidence=confidence,
            notes=" ".join(notes) if notes else None,
        )
