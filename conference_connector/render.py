"""Render outputs/shortlist.md, outputs/people.md, outputs/people.csv, outputs/items.csv
from the scored items and ranked people.
"""
from __future__ import annotations

import csv
import json

import yaml

from conference_connector.ingest import load_items
from conference_connector.models import Item
from conference_connector.paths import config_dir, outputs_dir, processed_dir

TIER_LABEL = {
    "A": "Tier A -- reach out before the conference",
    "B": "Tier B -- seek out on site",
    "C": "Tier C -- worth a look if time allows",
}

ROLE_LABEL = {
    "tutorial_organiser": "Tutorial organiser",
    "workshop_organiser": "Workshop organiser",
    "session_chair": "Session chair",
    "keynote_speaker": "Keynote speaker",
    "talk_last_author": "Talk (last author)",
    "talk_presenter": "Talk presenter",
    "poster_last_author": "Poster (last author)",
    "poster_presenter": "Poster presenter",
    "co_author": "Co-author",
}

DEFAULT_GEO_LABELS = {1: "tier 1", 2: "tier 2", 3: "tier 3", 4: ""}


def _conference_name() -> str:
    profile_path = config_dir() / "profile.yaml"
    if profile_path.exists():
        profile = yaml.safe_load(profile_path.read_text())
        if profile.get("conference"):
            return profile["conference"]
    return "the conference"


def _geo_labels() -> dict[int, str]:
    weights_path = config_dir() / "weights.yaml"
    if weights_path.exists():
        weights = yaml.safe_load(weights_path.read_text())
        labels = weights.get("geography", {}).get("tier_labels")
        if labels:
            return {int(k): v for k, v in labels.items()}
    return DEFAULT_GEO_LABELS


def _load_items_by_id() -> dict[str, Item]:
    return {item.item_id: item for item in load_items()}


def render_shortlist(item_scores: list[dict], items_by_id: dict[str, Item]) -> None:
    rows = []
    for s in item_scores:
        item = items_by_id.get(s["item_id"])
        if item is None:
            continue
        composite = (s["topic_fit"] + s["method_overlap"] + s["collab_potential"]) / 3.0
        rows.append((composite, s, item))
    rows.sort(key=lambda r: -r[0])

    conference = _conference_name()
    lines = [
        f"# {conference} -- Shortlist ({len(rows)} items)",
        "",
        "Scored by relevance to config/profile.yaml. Generated from a keyword-prefiltered "
        "candidate pool, close-read and scored manually -- see "
        "skills/conference-scout/references/close-reading.md for the method.",
        "",
    ]

    for composite, s, item in rows:
        kind_label = item.kind.capitalize()
        loc_bits = []
        if item.board_id:
            loc_bits.append(f"board {item.board_id}")
        if item.day:
            loc_bits.append(item.day)
        if item.start:
            loc_bits.append(f"{item.start}-{item.end or ''}")
        if item.room:
            loc_bits.append(item.room)
        loc = " | ".join(loc_bits)

        lines.append(f"## {item.title}")
        lines.append(f"`{kind_label} | score {composite:.2f}/5 | {loc}`")
        lines.append("")

        people_bits = []
        if item.organisers:
            people_bits.append(f"**Organisers:** {', '.join(item.organisers)}")
        if item.chairs:
            people_bits.append(f"**Chairs:** {', '.join(item.chairs)}")
        if item.authors:
            presenter = next((a.name for a in item.authors if a.is_presenter), None)
            last = next((a.name for a in item.authors if a.is_last), None)
            bits = []
            if presenter:
                bits.append(f"presenter {presenter}")
            if last and last != presenter:
                bits.append(f"last author {last}")
            if bits:
                people_bits.append(f"**Key people:** {'; '.join(bits)}")
        for pb in people_bits:
            lines.append(pb)
        if people_bits:
            lines.append("")

        lines.append(f"**Why it matters:** {s['why']}")
        lines.append("")
        lines.append(f"> {s['evidence']}")
        lines.append("")
        abstract = item.abstract.strip()
        if len(abstract) > 500:
            abstract = abstract[:500].rsplit(" ", 1)[0] + "..."
        if abstract:
            lines.append(abstract)
            lines.append("")
        if item.url:
            lines.append(f"[Source]({item.url})")
            lines.append("")
        lines.append("---")
        lines.append("")

    (outputs_dir() / "shortlist.md").write_text("\n".join(lines), encoding="utf-8")


def render_items_csv(item_scores: list[dict], items_by_id: dict[str, Item]) -> None:
    path = outputs_dir() / "items.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "item_id", "kind", "title", "track", "board_id", "day", "start", "end",
            "room", "topic_fit", "method_overlap", "collab_potential", "composite",
            "presenter", "last_author", "organisers", "chairs", "url",
        ])
        for s in item_scores:
            item = items_by_id.get(s["item_id"])
            if item is None:
                continue
            composite = (s["topic_fit"] + s["method_overlap"] + s["collab_potential"]) / 3.0
            presenter = next((a.name for a in item.authors if a.is_presenter), "")
            last = next((a.name for a in item.authors if a.is_last), "")
            w.writerow([
                item.item_id, item.kind, item.title, item.track, item.board_id or "",
                item.day or "", item.start or "", item.end or "", item.room or "",
                s["topic_fit"], s["method_overlap"], s["collab_potential"], f"{composite:.2f}",
                presenter, last, "; ".join(item.organisers), "; ".join(item.chairs), item.url,
            ])


def render_people(people: list[dict], items_by_id: dict[str, Item]) -> None:
    conference = _conference_name()
    geo_labels = _geo_labels()
    lines = [
        f"# {conference} -- Ranked people to reach out to",
        "",
        "Derived from the shortlisted items (see shortlist.md), pivoted from items to the "
        "people behind them. Ranking = relevance x seniority x access-quality x geography "
        "-- see config/weights.yaml for what each of those means for this profile.",
        "",
        "**Note on email addresses:** deliberately excluded from this list and every "
        "other output. Find contact details yourself when you decide to write.",
        "",
    ]

    by_tier: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    for p in people:
        by_tier[p["tier"]].append(p)

    for tier in ("A", "B", "C"):
        rows = by_tier[tier]
        if not rows:
            continue
        lines.append(f"## {TIER_LABEL[tier]} ({len(rows)} people)")
        lines.append("")
        for p in rows:
            role_str = ", ".join(ROLE_LABEL.get(r, r) for r in p["roles"])
            geo_tag = geo_labels.get(p["geography_tier"], "")
            header = f"### {p['name']}"
            if geo_tag:
                header += f"  ({geo_tag})"
            lines.append(header)
            lines.append(f"*{p['affiliation'] or 'affiliation unknown'}* -- {p['country'] or 'country unknown'}")
            lines.append(f"Roles: {role_str}. Composite score: {p['composite']:.2f}.")
            lines.append("")
            lines.append("Items:")
            for item_id in p["item_ids"]:
                item = items_by_id.get(item_id)
                if item is None:
                    continue
                loc = item.board_id or f"{item.day or ''} {item.room or ''}".strip()
                lines.append(f"- [{item.kind}] {item.title} ({loc})")
            lines.append("")
    (outputs_dir() / "people.md").write_text("\n".join(lines), encoding="utf-8")


def render_people_csv(people: list[dict]) -> None:
    path = outputs_dir() / "people.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "tier", "name", "affiliation", "country", "geography_tier", "roles",
            "n_items", "relevance", "seniority", "access", "composite", "item_ids",
        ])
        for p in people:
            w.writerow([
                p["tier"], p["name"], p["affiliation"], p["country"], p["geography_tier"],
                "; ".join(p["roles"]), p["n_items"], p["relevance"], p["seniority"],
                p["access"], p["composite"], "; ".join(p["item_ids"]),
            ])


def main() -> None:
    outputs_dir().mkdir(parents=True, exist_ok=True)
    item_scores = json.loads((processed_dir() / "item_scores.json").read_text())
    people = json.loads((processed_dir() / "people.json").read_text())
    items_by_id = _load_items_by_id()

    render_shortlist(item_scores, items_by_id)
    render_items_csv(item_scores, items_by_id)
    render_people(people, items_by_id)
    render_people_csv(people)

    print(f"Wrote shortlist.md, items.csv, people.md, people.csv to {outputs_dir()}")
