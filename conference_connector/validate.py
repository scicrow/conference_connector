"""Sanity-check an adapter's output before trusting it.

Every real bug found building the ECCB 2026 adapter was silent -- the parser ran
without error and returned data, just less of it (or wrong parts of it) than it
should have. None would have surfaced from "does it run" alone. All four would have
been caught by the checks here:

  - board-ID regex dropped ~300 posters               -> low coverage vs. structural marker count
  - 3 talks per time slot, only 1 parsed               -> low coverage vs. structural marker count
  - organiser names shredded by a naive comma split    -> author/organiser name sanity outliers
  - 2 of 18 tutorials used different field markup      -> field-presence outliers within a kind

Run this against a small, cheap set of pages first (ideally fixtures, not live
fetches) while writing an adapter, and again against the full corpus before treating
its output as real. It does not replace reading a sample of the actual items --
it only tells you where to look.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from conference_connector.models import Item

# Mojibake signatures: byte sequences that only appear when UTF-8 text has been
# decoded as Latin-1/cp1252 somewhere in the pipeline. Any hit means a source page
# needs ftfy.fix_text() (or equivalent) applied before extraction, not after.
_MOJIBAKE_SIGNATURES = ["Ã¡", "Ã©", "Ã­", "Ã³", "Ã¼", "Ã¶", "Ã¤", "Â", "â€™", "â€œ", "â€"]

# A name field containing these is almost certainly a parsing artifact, not a real
# person/org name -- e.g. an unclosed parenthetical dragged in by a naive comma split.
_SUSPICIOUS_NAME_RE = re.compile(r"[(){}<>]|https?://|\d{4,}")

_FIELD_PRESENCE_LOW = 0.5   # below this: probably a real gap in the source, not a bug
_FIELD_PRESENCE_HIGH = 0.95  # above this: fine. Between the two: investigate.


def _mojibake_hits(text: str) -> list[str]:
    return [sig for sig in _MOJIBAKE_SIGNATURES if sig in text]


def validate(items: list[Item], expected_min_total: int | None = None) -> dict:
    issues: list[str] = []
    by_kind: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_kind[it.kind].append(it)

    # An adapter that returns nothing is the loudest possible failure, not a pass --
    # it's the default state of a half-written parser, and every other check below is
    # vacuously satisfied by an empty list. Report it and stop.
    if not items:
        issues.append(
            "Adapter returned 0 items. Nothing below could run. Check that fetch_all() "
            "is reaching the right URL, that the response is what you expect (look at "
            "the cached file under data/raw/), and that your entry-splitting pattern "
            "still matches the live markup."
        )
        return {"total": 0, "kinds": {}, "issues": issues}

    if expected_min_total is not None and len(items) < expected_min_total:
        issues.append(
            f"Only {len(items)} items total, expected at least {expected_min_total}. "
            "Check for a filter/regex that's silently dropping records."
        )

    # Duplicate item_ids -- two different items colliding on the same ID means one is
    # overwriting the other wherever items get keyed by item_id (e.g. the person pivot).
    id_counts = Counter(it.item_id for it in items)
    dupes = [item_id for item_id, n in id_counts.items() if n > 1]
    if dupes:
        issues.append(f"{len(dupes)} duplicate item_id(s), e.g. {dupes[:5]}")

    kind_reports = {}
    for kind, kind_items in sorted(by_kind.items()):
        n = len(kind_items)
        has_title = sum(1 for it in kind_items if it.title.strip())
        has_abstract = sum(1 for it in kind_items if it.abstract.strip())
        has_authors = sum(1 for it in kind_items if it.authors)
        has_day = sum(1 for it in kind_items if it.day)

        field_rates = {
            "title": has_title / n,
            "abstract": has_abstract / n,
            "authors": has_authors / n,
            "day": has_day / n,
        }
        for field, rate in field_rates.items():
            if _FIELD_PRESENCE_LOW < rate < _FIELD_PRESENCE_HIGH:
                missing = [it.item_id for it in kind_items if not _has_field(it, field)]
                issues.append(
                    f"kind={kind}: {field} present in {rate:.0%} of items "
                    f"({len(missing)} missing, e.g. {missing[:3]}) -- outlier pattern, "
                    "check whether those items use different source markup."
                )

        # Mojibake scan.
        mojibake_items = []
        for it in kind_items:
            hits = _mojibake_hits(it.title) or _mojibake_hits(it.abstract)
            if hits:
                mojibake_items.append((it.item_id, hits[0]))
        if mojibake_items:
            issues.append(
                f"kind={kind}: {len(mojibake_items)} item(s) contain mojibake signatures "
                f"(e.g. {mojibake_items[0]}) -- run clean_text()/ftfy on this source."
            )

        # Suspicious names in authors/organisers/chairs -- likely a split bug.
        bad_names = []
        for it in kind_items:
            for name in [a.name for a in it.authors] + list(it.organisers) + list(it.chairs):
                if name and _SUSPICIOUS_NAME_RE.search(name):
                    bad_names.append((it.item_id, name))
        if bad_names:
            issues.append(
                f"kind={kind}: {len(bad_names)} suspicious name(s) containing parens/urls/"
                f"long digit runs, e.g. {bad_names[0]} -- likely a comma-split or similar bug."
            )

        kind_reports[kind] = {"n": n, "field_rates": {k: round(v, 3) for k, v in field_rates.items()}}

    return {"total": len(items), "kinds": kind_reports, "issues": issues}


def _has_field(item: Item, field: str) -> bool:
    if field == "title":
        return bool(item.title.strip())
    if field == "abstract":
        return bool(item.abstract.strip())
    if field == "authors":
        return bool(item.authors)
    if field == "day":
        return bool(item.day)
    return True


def format_report(report: dict) -> str:
    lines = [f"validate: {report['total']} items total"]
    for kind, k in sorted(report["kinds"].items()):
        rates = ", ".join(f"{f}={r:.0%}" for f, r in k["field_rates"].items())
        lines.append(f"  {kind:10s} n={k['n']:<5d} {rates}")
    lines.append("")
    if report["issues"]:
        lines.append(f"{len(report['issues'])} issue(s) found:")
        for issue in report["issues"]:
            lines.append(f"  - {issue}")
    else:
        lines.append("No issues found by the automated checks. Still read a sample by hand.")
    return "\n".join(lines)


def main(adapter_slug: str, refresh: bool = False) -> None:
    from conference_connector.ingest import build_items

    items = build_items(adapter_slug, refresh=refresh)
    report = validate(items)
    print(format_report(report))
