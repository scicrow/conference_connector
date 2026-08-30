"""Location-tier classification.

Many use cases for this tool have a geographic angle -- targeting a specific host
institution or region for a placement, a visa-friendly country, home turf for a
funding scheme. weights.yaml defines up to 4 tiers of institutions/countries and a
score multiplier for each; tier 4 (the default) is "everyone else" and always has
multiplier 1.0. A profile with no geographic angle at all should just leave every
tier list empty -- everything then falls into tier 4 and geography stops affecting
the ranking.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from conference_connector.paths import config_dir

_weights_cache: dict | None = None


def _weights() -> dict:
    global _weights_cache
    if _weights_cache is None:
        _weights_cache = yaml.safe_load((config_dir() / "weights.yaml").read_text())
    return _weights_cache


def _lower_list(key: str) -> list[str]:
    return [s.lower() for s in _weights().get(key, []) or []]


def _lower_set(key: str) -> set[str]:
    return {s.lower() for s in _weights().get(key, []) or []}


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
    geo = _weights()["geography"]
    return {
        1: geo.get("tier1_multiplier", 1.0),
        2: geo.get("tier2_multiplier", 1.0),
        3: geo.get("tier3_multiplier", 1.0),
        4: geo.get("tier4_multiplier", 1.0),
    }[tier]
