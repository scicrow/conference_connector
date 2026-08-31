"""Keyword prefilter -- narrow a large item pool to a set worth a close read.

conference_connector deliberately does not call an LLM API to score every item. For a
conference-sized corpus (hundreds to low thousands of items), that's either expensive
or, if you're relying on a chat subscription instead of API credits, impossible to
automate at all -- the model has to actually read the text, which means a human (or an
LLM-in-the-loop session) doing the reading.

So this stage does the cheap, mechanical part: a broad, recall-oriented lexical filter
that narrows the pool enough for a person to read it in one sitting, without silently
dropping good candidates to vocabulary mismatch. It deliberately over-generates on
synonyms -- false positives here cost nothing (they just score low in the close read);
false negatives are unrecoverable, since nobody reads what this stage throws away.

Item kinds that are individually scarce and high-value (see `always_include_kinds` in
config.yaml's `prefilter` section) skip the filter entirely and go straight to the
candidate set. This matters: a global top-N cut across a mixed pool of many small items
and few large ones can crowd the scarce, valuable kind out almost entirely even though
each individual item in it is worth reading -- confirm your own always-include list
against a raw kind breakdown before trusting the defaults.

The output (candidates_for_review.md) is for a human or an LLM-in-the-loop session to
read directly and hand-write item_scores.json from -- see
conference_connector/skills/conference-scout/references/close-reading.md.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from conference_connector import config
from conference_connector.ingest import load_items
from conference_connector.models import Item
from conference_connector.paths import interim_dir

CANDIDATES_JSONL = "candidates.jsonl"
CANDIDATES_MD = "candidates_for_review.md"

DEFAULT_ALWAYS_INCLUDE_KINDS = {"tutorial", "workshop", "keynote"}
DEFAULT_TOP_N = 150


def _thread_keywords(profile: dict) -> dict[str, list[str]]:
    return {t["id"]: [k.lower() for k in t.get("keywords", [])] for t in profile["threads"]}


def _thread_weights(profile: dict) -> dict[str, float]:
    return {t["id"]: t["weight"] for t in profile["threads"]}


def lexical_score(item: Item, keywords: dict[str, list[str]], weights: dict[str, float]) -> tuple[float, dict[str, int]]:
    text = f"{item.title}\n{item.abstract}".lower()
    hits: dict[str, int] = {}
    total = 0.0
    for thread_id, kws in keywords.items():
        count = sum(len(re.findall(re.escape(kw), text)) for kw in kws if kw)
        if count:
            hits[thread_id] = count
            total += count * weights.get(thread_id, 1.0)
    return total, hits


def prefilter(items: list[Item], profile: dict | None = None) -> list[dict]:
    profile = profile or config.load()
    keywords = _thread_keywords(profile)
    weights = _thread_weights(profile)
    pf_config = profile.get("prefilter", {})
    always_include_kinds = set(pf_config.get("always_include_kinds", DEFAULT_ALWAYS_INCLUDE_KINDS))
    top_n = pf_config.get("top_n_scored", DEFAULT_TOP_N)

    always = [it for it in items if it.kind in always_include_kinds]
    scored_pool = [it for it in items if it.kind not in always_include_kinds]

    scored = []
    for it in scored_pool:
        score, hits = lexical_score(it, keywords, weights)
        if score > 0:
            scored.append((score, hits, it))
    scored.sort(key=lambda t: -t[0])
    top = scored[:top_n]

    candidates = []
    for it in always:
        candidates.append({"item": it, "lexical_score": None, "lexical_hits": {}})
    for score, hits, it in top:
        candidates.append({"item": it, "lexical_score": round(score, 2), "lexical_hits": hits})
    return candidates


def write_candidates(candidates: list[dict]) -> None:
    interim_dir().mkdir(parents=True, exist_ok=True)

    jsonl_path = interim_dir() / CANDIDATES_JSONL
    with jsonl_path.open("w", encoding="utf-8") as f:
        for c in candidates:
            row = c["item"].model_dump()
            row["lexical_score"] = c["lexical_score"]
            row["lexical_hits"] = c["lexical_hits"]
            f.write(json.dumps(row) + "\n")

    md_path = interim_dir() / CANDIDATES_MD
    lines = [f"# Candidates for close reading ({len(candidates)} items)\n"]
    for c in candidates:
        it: Item = c["item"]
        lines.append(f"## [{it.item_id}] {it.title}")
        meta = [f"kind={it.kind}", f"track={it.track}"]
        if it.board_id:
            meta.append(f"board={it.board_id}")
        if it.day:
            meta.append(f"day={it.day} {it.start or ''}-{it.end or ''}")
        if it.room:
            meta.append(f"room={it.room}")
        if c["lexical_score"] is not None:
            meta.append(f"lexical_score={c['lexical_score']} hits={c['lexical_hits']}")
        lines.append("`" + " | ".join(meta) + "`\n")
        if it.organisers:
            lines.append(f"**Organisers:** {', '.join(it.organisers)}\n")
        if it.chairs:
            lines.append(f"**Chairs:** {', '.join(it.chairs)}\n")
        if it.authors:
            author_strs = []
            for a in it.authors:
                tag = []
                if a.is_presenter:
                    tag.append("presenter")
                if a.is_last:
                    tag.append("last")
                tagstr = f" [{','.join(tag)}]" if tag else ""
                author_strs.append(f"{a.name}{tagstr} ({a.affiliation_norm or a.country})")
            lines.append(f"**Authors:** {'; '.join(author_strs)}\n")
        lines.append(f"{it.abstract}\n")
        lines.append("---\n")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(candidates)} candidates to {jsonl_path} and {md_path}")


def main() -> None:
    from conference_connector.ingest import items_path
    from conference_connector.preconditions import require_config, require_file

    require_config("threads")
    require_file(items_path(), "conference_connector ingest <adapter>", "the ingested item list")

    items = load_items()
    candidates = prefilter(items)
    write_candidates(candidates)

    kinds = Counter(c["item"].kind for c in candidates)
    print("Candidate kinds:", dict(kinds))
