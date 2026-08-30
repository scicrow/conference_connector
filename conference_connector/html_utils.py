"""Shared text/HTML cleanup helpers used by every adapter.

The ISCB pages are old, hand-rolled HTML with mismatched tags in places, so we lean on
regex extraction rather than a strict DOM parser, then use selectolax just to strip any
residual tags from an already-located fragment.

Note: parse_author_string assumes one common convention ("Name, Aff1, Aff2, Country") --
seen on ISCB-family sites and several others. It will not fit every conference; adapters
for differently-formatted author strings should write their own parser and skip this one.
"""
from __future__ import annotations

import re

import ftfy
from selectolax.parser import HTMLParser

_WS_RE = re.compile(r"\s+")


def strip_tags(fragment: str) -> str:
    """Remove HTML tags from a fragment, returning clean whitespace-collapsed text."""
    if not fragment:
        return ""
    text = HTMLParser(fragment).text(separator=" ")
    return clean_text(text)


def clean_text(text: str) -> str:
    """Fix mojibake (double-encoded UTF-8) and collapse whitespace.

    ftfy.fix_text is run unconditionally: ~75% of the ISCB pages contain mojibake
    (e.g. "ZoltÃ¡n" -> "Zoltán", "Î²-lactamase" -> "β-lactamase") and this corrupts
    author names, which are later used as join keys. Never skip this step.
    """
    if not text:
        return ""
    text = ftfy.fix_text(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def parse_author_string(raw: str) -> dict:
    """Parse a raw ISCB author string of the form:

        "Name, Affiliation part 1, Affiliation part 2, ..., Country[, Country]"

    into {"name", "affiliation_raw", "affiliation_norm", "country"}.

    The country is frequently duplicated at the end of the string (a rendering quirk
    of the source site), so we drop an exact trailing duplicate.
    """
    raw = clean_text(raw)
    if not raw:
        return {"name": "", "affiliation_raw": "", "affiliation_norm": "", "country": ""}

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return {"name": "", "affiliation_raw": "", "affiliation_norm": "", "country": ""}

    name = parts[0]
    rest = parts[1:]

    # Drop an exact trailing duplicate (e.g. "...Germany, Germany").
    if len(rest) >= 2 and rest[-1] == rest[-2]:
        rest = rest[:-1]

    country = rest[-1] if rest else ""
    affiliation_parts = rest[:-1] if len(rest) > 1 else rest if not country else []
    # If there was only one segment after the name, it doubles as country AND
    # affiliation is unknown (common for short "Name, Country" entries).
    if len(rest) == 1:
        affiliation_parts = []

    affiliation_raw = ", ".join(rest)
    affiliation_norm = ", ".join(affiliation_parts)

    return {
        "name": name,
        "affiliation_raw": affiliation_raw,
        "affiliation_norm": affiliation_norm,
        "country": country,
    }
