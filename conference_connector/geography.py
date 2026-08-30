"""Location-tier classification.

Many use cases for this tool have a geographic angle -- targeting a specific host
institution or region for a placement, a visa-friendly country, home turf for a
funding scheme. config.yaml's `ranking` section defines up to 4 tiers of
institutions/countries and a score multiplier for each; tier 4 (the default) is
"everyone else" and always has multiplier 1.0. A profile with no geographic angle at
all should just leave every tier list empty -- everything then falls into tier 4 and
geography stops affecting the ranking.
"""
from __future__ import annotations

from conference_connector import config


def _ranking() -> dict:
    return config.load().get("ranking", {})


def _lower_list(key: str) -> list[str]:
    return [s.lower() for s in _ranking().get(key, []) or []]


def _lower_set(key: str) -> set[str]:
    return {s.lower() for s in _ranking().get(key, []) or []}


def classify(affiliation_norm: str, country: str) -> int:
    """Return a geography tier (1-4) for a given affiliation/country pair."""
    aff = (affiliation_norm or "").lower()
    ctry = (country or "").lower()

    if any(inst in aff for inst in _lower_list("tier1_institutions")):
        return 1
    if ctry in _lower_set("tier2_countries"):
        return 2
    if any(inst in aff for inst in _lower_list("tier2_institutions")):
        return 2
    if ctry in _lower_set("tier3_countries"):
        return 3
    return 4


def multiplier(tier: int) -> float:
    geo = _ranking().get("geography", {})
    return {
        1: geo.get("tier1_multiplier", 1.0),
        2: geo.get("tier2_multiplier", 1.0),
        3: geo.get("tier3_multiplier", 1.0),
        4: geo.get("tier4_multiplier", 1.0),
    }[tier]
