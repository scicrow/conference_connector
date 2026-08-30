"""Pivot from scored items to ranked people.

Items are evidence; people are the deliverable. This module explodes each scored
item's authors/chairs/organisers into (person, item, role) edges, resolves them to
person records, and computes a composite score per weights.yaml:

    composite = (w_relevance*relevance + w_seniority*seniority + w_access*access)
                * geography_multiplier

This exists because ranking items directly surfaces the wrong people for most
outreach goals -- item-level rankings are dominated by whoever happens to be
presenting, which for a poster-heavy conference is mostly students, while the person
worth contacting is often a last author or session chair who never tops an
item-ranked list at all. Tune what "worth contacting" means via access_by_role and
seniority_by_role in weights.yaml -- the roles and their weights encode your outreach
goal, not a fact about the conference.
"""
from __future__ import annotations

import json
import math
from collections import Counter

import yaml

from conference_connector.geography import classify, multiplier
from conference_connector.ingest import load_items
from conference_connector.models import Item
from conference_connector.paths import config_dir, processed_dir

ITEM_SCORES_FILENAME = "item_scores.json"
PEOPLE_FILENAME = "people.json"

# Fallback for plain co-authors (not presenter, not last, not chair/organiser) --
# still worth knowing about, but neither senior nor easily approachable by default.
_DEFAULT_ACCESS = 1
_DEFAULT_SENIORITY = 2


def item_scores_path():
    return processed_dir() / ITEM_SCORES_FILENAME


def people_path():
    return processed_dir() / PEOPLE_FILENAME


def _load_weights() -> dict:
    return yaml.safe_load((config_dir() / "weights.yaml").read_text())


def _load_item_scores() -> dict[str, dict]:
    return {row["item_id"]: row for row in json.loads(item_scores_path().read_text())}


def _load_items_by_id() -> dict[str, Item]:
    return {item.item_id: item for item in load_items()}


def _item_topic_score(scored: dict) -> float:
    return (scored["topic_fit"] + scored["method_overlap"] + scored["collab_potential"]) / 3.0


def build_people() -> list[dict]:
    weights = _load_weights()
    access_by_role = weights["access_by_role"]
    seniority_by_role = weights["seniority_by_role"]
    composite_w = weights["composite"]
    tiers_cfg = weights["tiers"]

    item_scores = _load_item_scores()
    items_by_id = _load_items_by_id()

    people: dict[str, dict] = {}

    def get_person(name: str) -> dict:
        key = name.strip()
        if key not in people:
            people[key] = {
                "name": key,
                "affiliations": [],  # list of (affiliation_norm, country)
                "roles": [],         # list of (role, item_id, item_score)
                "items": [],         # list of item_id
            }
        return people[key]

    for item_id, scored in item_scores.items():
        item = items_by_id.get(item_id)
        if item is None:
            continue
        item_score = _item_topic_score(scored)
        # sorted(set(...)), not set(...): dict/set iteration order for strings is
        # hash-randomized per process in CPython, so an unsorted set here would make
        # the order people are first encountered -- and therefore tie-break order in
        # the final sort below -- nondeterministic across runs on identical input.
        chairs = sorted(set(item.chairs))
        organisers = sorted(set(item.organisers))

        for chair_name in chairs:
            p = get_person(chair_name)
            p["roles"].append(("session_chair", item_id, item_score))
            p["items"].append(item_id)

        for org_name in organisers:
            role = "tutorial_organiser" if item.kind == "tutorial" else "workshop_organiser"
            p = get_person(org_name)
            p["roles"].append((role, item_id, item_score))
            p["items"].append(item_id)
            p["affiliations"].append(("", ""))  # organiser strings carry no affiliation

        for author in item.authors:
            if not author.name:
                continue
            p = get_person(author.name)
            p["affiliations"].append((author.affiliation_norm, author.country))
            p["items"].append(item_id)

            if item.kind == "keynote":
                role = "keynote_speaker"
            elif item.kind == "poster":
                role = "poster_presenter" if author.is_presenter else (
                    "poster_last_author" if author.is_last else "co_author"
                )
            elif item.kind == "talk":
                if author.name in chairs:
                    role = "session_chair"
                elif author.is_presenter:
                    role = "talk_presenter"
                elif author.is_last:
                    role = "talk_last_author"
                else:
                    role = "co_author"
            else:  # tutorial/workshop authors (rare; organisers already handled above)
                role = "co_author"

            p["roles"].append((role, item_id, item_score))

    out = []
    for name, p in people.items():
        if not p["roles"]:
            continue
        item_ids = sorted(set(p["items"]))
        n_items = len(item_ids)

        item_scores_seen = sorted({s for (_, _, s) in p["roles"]}, reverse=True)
        top_score = item_scores_seen[0]
        relevance = top_score + min(1.5, 0.3 * (n_items - 1))

        access = max(access_by_role.get(role, _DEFAULT_ACCESS) for role, _, _ in p["roles"])
        seniority = max(seniority_by_role.get(role, _DEFAULT_SENIORITY) for role, _, _ in p["roles"])

        # Geography: best (lowest/most valuable) tier across any known affiliation.
        # A person can appear with more than one affiliation string across items
        # (dual appointment, stale/partial one on an older submission); take
        # whichever single affiliation classifies best, and keep that exact string
        # for display so the shown affiliation always matches the tier it earned.
        known_affs = [(aff, country) for aff, country in p["affiliations"] if aff or country]
        if known_affs:
            best_affiliation, best_country = min(known_affs, key=lambda ac: classify(ac[0], ac[1]))
            geo_tier = classify(best_affiliation, best_country)
        else:
            best_affiliation, best_country = "", ""
            geo_tier = 4
        geo_mult = multiplier(geo_tier)

        composite = (
            composite_w["w_relevance"] * relevance
            + composite_w["w_seniority"] * seniority
            + composite_w["w_access"] * access
        ) * geo_mult

        roles_summary = sorted({r for r, _, _ in p["roles"]})

        out.append(
            {
                "name": name,
                "affiliation": best_affiliation,
                "country": best_country,
                "geography_tier": geo_tier,
                "roles": roles_summary,
                "n_items": n_items,
                "item_ids": item_ids,
                "relevance": round(relevance, 2),
                "seniority": seniority,
                "access": access,
                "composite": round(composite, 3),
            }
        )

    # Tiebreak on name: composite scores frequently tie (small integer inputs, few
    # distinct multipliers), and tier assignment below is by position in this sorted
    # list -- an undefined tiebreak means two equally-scored people could land on
    # either side of a tier cutoff differently on different runs of the same data.
    out.sort(key=lambda r: (-r["composite"], r["name"]))

    n = len(out)
    a_cutoff = max(1, math.ceil(n * tiers_cfg["A_top_pct"]))
    b_cutoff = max(a_cutoff, math.ceil(n * tiers_cfg["B_top_pct"]))
    for i, row in enumerate(out):
        row["tier"] = "A" if i < a_cutoff else ("B" if i < b_cutoff else "C")

    return out


def main() -> None:
    people = build_people()
    processed_dir().mkdir(parents=True, exist_ok=True)
    people_path().write_text(json.dumps(people, indent=2), encoding="utf-8")

    tiers = Counter(p["tier"] for p in people)
    print(f"Resolved {len(people)} people -> {people_path()}")
    print(f"  tiers: {dict(tiers)}")
    print("\nTop 15 by composite:")
    for p in people[:15]:
        print(f"  [{p['tier']}] {p['composite']:6.2f}  {p['name']:28s} {p['affiliation'][:45]}")
