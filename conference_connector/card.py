"""Reference card: a phone/print-friendly HTML+PDF summary of who to see at the
conference, built from the ranked shortlist.

This is the last stage of the pipeline, downstream of `rank`. It doesn't do anything
that requires reading text or judgement -- the judgement already happened during the
close-read (item_scores.json's `why`) and, optionally, during outreach-writing
(outputs/dossiers/*.md, if the skill wrote them per
conference_connector/skills/conference-scout/references/outreach-writing.md). This module just assembles
what already exists into something browsable on a phone at the actual event: a
day-by-day schedule plus one card per person with their sessions' day/time/room/board.

Dossier enrichment is opportunistic, not required: if `outputs/dossiers/<slug>.md`
exists for a person (slug = their name, lowercased, non-alphanumerics collapsed to
hyphens), its "hook"/"opening line"/"ask" sections (matched by loose keyword, not an
exact header) are pulled in verbatim. Anyone without a dossier still gets a card, just
with the item_scores.json `why` for their single highest-scoring item as the one-line
summary instead of a hand-written hook.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from conference_connector import config
from conference_connector.ingest import load_items
from conference_connector.pivot import item_scores_path, people_path
from conference_connector.paths import outputs_dir
from conference_connector.render import ROLE_LABEL, TIER_LABEL

TIER_COLORS = {
    "A": ("#b8860b", "#fffdf7"),
    "B": ("#4a6fa5", "#f7fafd"),
    "C": ("#5a8f5a", "#f5faf5"),
}
_DEFAULT_TIER_COLOR = ("#777777", "#f7f7f7")

KIND_COLORS = {
    "poster": ("#dcebe0", "#1e5631"),
    "talk": ("#dde6f5", "#1d3f7a"),
    "tutorial": ("#f5e6dd", "#7a3f1d"),
    "workshop": ("#f0e0f0", "#6a1d7a"),
    "keynote": ("#f5dde0", "#7a1d3f"),
}

_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
]
_MONTHS = {m: i + 1 for i, m in enumerate(_MONTH_NAMES)}
# Three-letter abbreviations too ("Mar 3", "3 Sep"), which are at least as common on
# conference programmes as the full month name.
_MONTHS.update({m[:3]: i + 1 for i, m in enumerate(_MONTH_NAMES)})

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
# Day-month ("31 August", "3 Sep") and month-day ("August 31", "Mar 3") are both in
# wide use and neither is safe to assume -- ECCB writes the first, most US
# conferences write the second. ISO dates appear in machine-generated programmes.
_DATE_DM_RE = re.compile(r"\b(\d{1,2})\s+(" + _MONTH_ALT + r")\b", re.I)
_DATE_MD_RE = re.compile(r"\b(" + _MONTH_ALT + r")\s+(\d{1,2})\b", re.I)
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_UNSCHEDULED = (99, 99)


def _date_key(day: str | None) -> tuple[int, int]:
    """Parse a human day string into a (month, day) sort key, independent of weekday
    naming, month-name abbreviation, field order, or which conference/year this is.

    Unparseable or missing days sort last rather than raising -- a conference that
    labels days "Day 1"/"Day 2" or omits them entirely is a real case, and the card
    still has to render something sensible.
    """
    if not day:
        return _UNSCHEDULED
    s = day.lower()

    iso = _DATE_ISO_RE.search(s)
    if iso:
        return (int(iso.group(2)), int(iso.group(3)))

    dm = _DATE_DM_RE.search(s)
    if dm:
        return (_MONTHS[dm.group(2)], int(dm.group(1)))

    md = _DATE_MD_RE.search(s)
    if md:
        return (_MONTHS[md.group(1)], int(md.group(2)))

    return _UNSCHEDULED


def _time_key(start: str | None) -> int:
    if not start:
        return -1
    try:
        h, m = start.split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return 9999


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower())
    return s.strip("-")


def _when_where(it: dict) -> tuple[str, str, str]:
    kind = it["kind"]
    day = it.get("day") or ""
    start = it.get("start")
    end = it.get("end")
    room = it.get("room") or ""
    board = it.get("board_id")

    if kind == "poster":
        loc = f"Board {board}" if board else "poster board"
        time = f"{start}\u2013{end or ''}" if start else ""
        return day, time, loc
    if kind == "talk":
        time = f"{start}\u2013{end or ''}" if start else ""
        return day, time, room
    if kind in ("tutorial", "workshop"):
        time = f"{start}\u2013{end or ''}" if start else "full day"
        return day, time, room
    return day, "", room  # keynote or anything else


def _merge_identical_slots(rows: list[dict]) -> list[dict]:
    """Some sources only timestamp a whole session slot, not each item within it
    (e.g. three talks sharing one chaired hour) -- merge consecutive rows that land
    on the exact same day/time/room/board so the card doesn't show what looks like a
    duplicated line."""
    merged: list[dict] = []
    for r in rows:
        if (merged and merged[-1]["kind"] == r["kind"] and merged[-1]["day"] == r["day"]
                and merged[-1]["time"] == r["time"] and merged[-1]["loc"] == r["loc"]):
            merged[-1]["titles"].append(r["title"])
        else:
            merged.append({**r, "titles": [r["title"]]})
    return merged


_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


def _load_dossier_sections(dossiers_dir: Path, slug: str) -> dict[str, str]:
    path = dossiers_dir / f"{slug}.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    headers = list(_SECTION_RE.finditer(text))
    sections = {}
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        sections[m.group(1).strip().lower()] = text[start:end].strip()
    return sections


def _clean_markdown(body: str, max_len: int) -> str:
    body = re.sub(r"^[>\-\*]\s*", "", body, flags=re.M)
    body = re.sub(r"[*_]{1,2}", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > max_len:
        body = body[:max_len].rsplit(" ", 1)[0] + "..."
    return body


def _pick(sections: dict[str, str], keyword_groups: list[list[str]], max_len: int) -> str | None:
    for keywords in keyword_groups:
        for header, body in sections.items():
            if any(kw in header for kw in keywords):
                return _clean_markdown(body, max_len)
    return None


def _fallback_why(person: dict, item_scores: dict) -> str:
    best, best_score = None, -1.0
    for iid in person["item_ids"]:
        sc = item_scores.get(iid)
        if not sc:
            continue
        avg = (sc["topic_fit"] + sc["method_overlap"] + sc["collab_potential"]) / 3.0
        if avg > best_score:
            best_score, best = avg, sc
    return best["why"] if best else ""


def build_card_data(
    tiers: tuple[str, ...] = ("A", "B"),
    exclude: set[str] | None = None,
    dossiers_dir: Path | None = None,
) -> list[dict]:
    exclude = exclude or set()
    people = json.loads(people_path().read_text())
    items = {it.item_id: it for it in load_items()}
    item_scores = {row["item_id"]: row for row in json.loads(item_scores_path().read_text())}
    dossiers_dir = dossiers_dir or (outputs_dir() / "dossiers")
    geo_labels = config.geo_labels()

    out = []
    for p in people:
        if p["tier"] not in tiers or p["name"] in exclude:
            continue

        rows = []
        for iid in p["item_ids"]:
            it = items.get(iid)
            if it is None:
                continue
            day, time, loc = _when_where(it.model_dump())
            rows.append({
                "kind": it.kind, "title": it.title, "day": day, "time": time, "loc": loc,
                "_sort": (_date_key(day), _time_key(it.start)),
            })
        # Sort by slot *and* location so rows sharing a slot are adjacent --
        # _merge_identical_slots only merges neighbours, so two items in the same
        # room separated by one in a different room would otherwise not merge.
        rows.sort(key=lambda r: (r["_sort"], r["kind"], r["loc"]))
        rows = _merge_identical_slots(rows)

        slug = _slugify(p["name"])
        sections = _load_dossier_sections(dossiers_dir, slug) if dossiers_dir.exists() else {}
        why = _pick(sections, [["hook"], ["why"], ["who "]], 400) or _fallback_why(p, item_scores)
        opener = _pick(sections, [["opening line"], ["opener"]], 350)
        ask = None
        for header, body in sections.items():
            if header.strip() == "the ask" or header.strip().endswith(" ask"):
                ask = _clean_markdown(body, 350)
                break

        out.append({
            "name": p["name"],
            "tier": p["tier"],
            # Kept so the day-by-day schedule can be rebuilt per *item* rather than
            # per person -- `items` below is already merged by slot and no longer
            # carries item identity, so it can't be de-duplicated across people.
            "item_ids": list(p["item_ids"]),
            "affiliation": p["affiliation"] or "affiliation not listed",
            "geo": geo_labels.get(p["geography_tier"], ""),
            "roles": [ROLE_LABEL.get(r, r) for r in p["roles"]],
            "why": why,
            "opener": opener,
            "ask": ask,
            "items": rows,
        })

    tier_order = {t: i for i, t in enumerate(tiers)}
    out.sort(key=lambda p: (tier_order.get(p["tier"], 99), p["name"]))
    return out


def _e(s: str) -> str:
    return _html.escape(s or "")


def _schedule_rows_html(items: list[dict]) -> str:
    rows = []
    for it in items:
        kind_tag = it["kind"].capitalize()
        loc = f"{it['day']}, {it['time']} \u00b7 {it['loc']}" if it["time"] else f"{it['day']} \u00b7 {it['loc']}"
        if len(it["titles"]) > 1:
            loc += f" ({len(it['titles'])} {it['kind']}s, same slot)"
        title_text = "; ".join(it["titles"])
        rows.append(
            f"<div class='item-row'><span class='kind-tag kind-{it['kind']}'>{_e(kind_tag)}</span>"
            f"<span class='item-title'>{_e(title_text)}</span>"
            f"<span class='item-loc'>{_e(loc)}</span></div>"
        )
    return "\n".join(rows)


def _person_card_html(p: dict) -> str:
    geo_badge = f"<span class='geo-badge'>{_e(p['geo'])}</span>" if p["geo"] else ""
    roles = ", ".join(p["roles"])
    opener = f"<div class='opener'>{_e(p['opener'])}</div>" if p["opener"] else ""
    ask = f"<div class='ask'><strong>Ask:</strong> {_e(p['ask'])}</div>" if p["ask"] else ""
    tier = p["tier"]
    return f"""
    <section class="card" style="border-left-color:{TIER_COLORS.get(tier, _DEFAULT_TIER_COLOR)[0]};
                                  background:{TIER_COLORS.get(tier, _DEFAULT_TIER_COLOR)[1]}">
      <div class="card-head">
        <h3>{_e(p['name'])}</h3>
        <span class="tier-badge" style="background:{TIER_COLORS.get(tier, _DEFAULT_TIER_COLOR)[0]}">Tier {_e(tier)}</span>
      </div>
      <div class="meta">{_e(p['affiliation'])} {geo_badge}</div>
      <div class="roles">{_e(roles)}</div>
      <div class="why">{_e(p['why'])}</div>
      {opener}
      {ask}
      <div class="schedule">{_schedule_rows_html(p['items'])}</div>
    </section>
    """


UNSCHEDULED_HEADING = "Day/time not listed in the programme"

# Order the kind sections within a day. Fixed rather than data-driven so the card
# reads the same every day of the conference: the things with a hard start time
# first, then the poster sessions you graze, then the all-day teaching formats.
KIND_ORDER = ["keynote", "talk", "poster", "tutorial", "workshop"]
KIND_HEADINGS = {
    "keynote": "Keynotes",
    "talk": "Talks",
    "poster": "Posters",
    "tutorial": "Tutorials",
    "workshop": "Workshops",
}

# A poster hall is walkable at roughly this many boards per session before it stops
# being a conversation and starts being a corridor. Posters beyond the cut are still
# on the person cards below; only this at-a-glance view is capped.
DEFAULT_MAX_POSTERS_PER_DAY = 10

_TIER_RANK = {"A": 0, "B": 1, "C": 2}


def _name_tokens(name: str) -> tuple[str, ...]:
    """Accent-stripped, initial-free name tokens, for spotting the same person spelled
    two ways in one author list."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return tuple(t for t in re.split(r"[^a-z0-9]+", folded.lower()) if len(t) > 1)


def _same_person(a: str, b: str) -> bool:
    """True when two author strings are near-certainly one person.

    Source author lists are not normalised: the same person turns up as both
    "Anais Mottaz" and "Anaïs Mottaz", or as "Ian Simpson" and "T. Ian Simpson",
    and `rank` treats those as two people. That is tolerable in a ranked list but
    not on a schedule row, where the point is to name everyone worth catching at one
    board -- listing the same person twice there is simply wrong.

    The test is deliberately narrow: identical token sets, or one a subset of the
    other with the first and last tokens matching (a dropped middle name). Anything
    looser starts merging distinct people who share a surname.
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    short, long_ = (ta, tb) if len(ta) < len(tb) else (tb, ta)
    return set(short) < set(long_) and short[0] == long_[0] and short[-1] == long_[-1]


def _dedupe_people(people: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Collapse spelling variants in one row's author list, keeping the fullest
    spelling and the strongest tier seen for that person."""
    out: list[tuple[str, str]] = []
    for name, tier in people:
        for i, (kept_name, kept_tier) in enumerate(out):
            if _same_person(name, kept_name):
                best_tier = min(kept_tier, tier, key=lambda t: _TIER_RANK.get(t, 99))
                out[i] = (max(kept_name, name, key=len), best_tier)
                break
        else:
            out.append((name, tier))
    return out


def _item_relevance(score: dict | None) -> float:
    """Mean of the three close-read axes -- the same aggregate `pivot` uses to turn
    item scores into a person's relevance, reused here to rank posters within a day."""
    if not score:
        return 0.0
    return (score["topic_fit"] + score["method_overlap"] + score["collab_potential"]) / 3.0


def build_schedule_data(
    people: list[dict], max_posters_per_day: int = DEFAULT_MAX_POSTERS_PER_DAY
) -> list[dict]:
    """Day-by-day schedule keyed on *items*, not people.

    One row per poster/talk/session, with every shortlisted person attached to it --
    the same poster routinely has two or three relevant authors, and listing it once
    per author turns a day into a list of near-duplicates. Rows are grouped by kind
    within each day, and posters are capped per day (highest close-read relevance
    first) because there is a hard limit on how many boards anyone visits in one
    session. Capped-out posters are counted, not silently dropped: they remain in
    full on the person cards.
    """
    items = {it.item_id: it for it in load_items()}
    item_scores = {row["item_id"]: row for row in json.loads(item_scores_path().read_text())}

    # item_id -> row, accumulating the people attached to it.
    rows: dict[str, dict] = {}
    for p in people:
        for iid in p["item_ids"]:
            it = items.get(iid)
            if it is None:
                continue
            row = rows.get(iid)
            if row is None:
                d = it.model_dump()
                day, time, loc = _when_where(d)
                row = rows[iid] = {
                    "item_id": iid,
                    "kind": it.kind,
                    "title": it.title,
                    "day": day or UNSCHEDULED_HEADING,
                    "time": time,
                    "loc": loc,
                    "relevance": _item_relevance(item_scores.get(iid)),
                    "_time": _time_key(it.start),
                    "people": [],
                }
            row["people"].append((p["name"], p["tier"]))

    by_day: dict[str, list[dict]] = {}
    for row in rows.values():
        # Best tier present drives the row's badge and its tie-breaks: a poster with
        # one Tier A author is a Tier A stop even if its other authors rank lower.
        row["people"] = _dedupe_people(row["people"])
        row["people"].sort(key=lambda np: (_TIER_RANK.get(np[1], 99), np[0]))
        row["tier"] = row["people"][0][1]
        by_day.setdefault(row["day"], []).append(row)

    days_sorted = sorted(by_day, key=lambda d: (d == UNSCHEDULED_HEADING, _date_key(d)))

    out = []
    for day in days_sorted:
        groups = []
        for kind in KIND_ORDER:
            kind_rows = [r for r in by_day[day] if r["kind"] == kind]
            if not kind_rows:
                continue
            dropped = 0
            if kind == "poster" and max_posters_per_day and len(kind_rows) > max_posters_per_day:
                kind_rows.sort(
                    key=lambda r: (-r["relevance"], _TIER_RANK.get(r["tier"], 99), r["loc"])
                )
                dropped = len(kind_rows) - max_posters_per_day
                kind_rows = kind_rows[:max_posters_per_day]
                # Once cut to the shortlist, order by board so the day is walkable.
                kind_rows.sort(key=lambda r: (r["loc"], -r["relevance"]))
            elif kind == "poster":
                kind_rows.sort(key=lambda r: (r["loc"], -r["relevance"]))
            else:
                kind_rows.sort(key=lambda r: (r["_time"], r["loc"], r["title"]))
            groups.append({"kind": kind, "rows": kind_rows, "dropped": dropped})
        # Any kind not in KIND_ORDER (a format this conference has and we don't know
        # about) still has to appear rather than vanishing from the schedule.
        for kind in sorted({r["kind"] for r in by_day[day]} - set(KIND_ORDER)):
            kind_rows = [r for r in by_day[day] if r["kind"] == kind]
            kind_rows.sort(key=lambda r: (r["_time"], r["loc"], r["title"]))
            groups.append({"kind": kind, "rows": kind_rows, "dropped": 0})
        out.append({"day": day, "groups": groups})
    return out


def _quick_index_html(schedule: list[dict]) -> str:
    out = []
    for day in schedule:
        out.append(f"<h3 class='day-head'>{_e(day['day'])}</h3>")
        for group in day["groups"]:
            kind = group["kind"]
            heading = KIND_HEADINGS.get(kind, kind.capitalize() + "s")
            count = f"{len(group['rows'])}"
            if group["dropped"]:
                count += f" of {len(group['rows']) + group['dropped']}, top-ranked"
            out.append(
                f"<div class='kind-head'><span class='kind-tag kind-{_e(kind)}'>{_e(heading)}</span>"
                f"<span class='kind-count'>{_e(count)}</span></div>"
            )
            for r in group["rows"]:
                names = ", ".join(name for name, _ in r["people"])
                color = TIER_COLORS.get(r["tier"], _DEFAULT_TIER_COLOR)[0]
                # The section heading already says these are posters, so the "Board"
                # prefix is redundant here and only pushes the ID onto a second line.
                loc = r["loc"][6:] if kind == "poster" and r["loc"].startswith("Board ") else r["loc"]
                when = f"{r['time']} \u00b7 {loc}" if r["time"] else loc
                out.append(
                    f"<div class='sched-row'><span class='sched-time'>{_e(when)}</span>"
                    f"<span class='sched-tierbadge' style='background:{color}'>{_e(r['tier'])}</span>"
                    f"<div class='sched-body'><span class='sched-title'>{_e(r['title'])}</span>"
                    f"<span class='sched-name'>{_e(names)}</span></div></div>"
                )
            if group["dropped"]:
                out.append(
                    f"<div class='sched-note'>+{group['dropped']} further {kind}s that day "
                    f"scored lower \u2014 see the person cards below.</div>"
                )
    return "\n".join(out)


def render_html(
    people: list[dict],
    conference_name: str,
    tiers: tuple[str, ...],
    schedule: list[dict] | None = None,
) -> str:
    if schedule is None:
        schedule = build_schedule_data(people)
    kind_css = "\n".join(
        f"  .kind-{k} {{ background: {bg}; color: {fg}; }}" for k, (bg, fg) in KIND_COLORS.items()
    )
    legend_lines = "; ".join(f"<strong>{TIER_LABEL.get(t, 'Tier ' + t)}</strong>" for t in tiers)
    sections_html = []
    for t in tiers:
        rows = [p for p in people if p["tier"] == t]
        if not rows:
            continue
        sections_html.append(f"<h2>{TIER_LABEL.get(t, 'Tier ' + t)} ({len(rows)} people)</h2>")
        sections_html.append("".join(_person_card_html(p) for p in rows))

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{_e(conference_name)} — Who to See</title>
<style>
  @page {{ size: A4; margin: 14mm 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 13px;
          line-height: 1.42; color: #1a1a1a; margin: 0; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 22px 0 8px; border-bottom: 2px solid #222; padding-bottom: 3px;
        page-break-after: avoid; }}
  h3 {{ font-size: 15px; margin: 0; }}
  .subtitle {{ color: #555; font-size: 12px; margin-bottom: 14px; }}
  .cover-note {{ background: #f2f2f2; border-radius: 6px; padding: 8px 10px; font-size: 11.5px;
                 color: #333; margin-bottom: 10px; }}
  .day-head {{ font-size: 14px; font-weight: 700; margin: 14px 0 2px; color: #222;
               border-bottom: 1px solid #ccc; padding-bottom: 2px; page-break-after: avoid; }}
  .kind-head {{ display: flex; align-items: baseline; gap: 6px; margin: 8px 0 2px;
                page-break-after: avoid; }}
  .kind-count {{ font-size: 10px; color: #777; }}
  .kind-head .kind-tag {{ font-size: 11px; padding: 2px 8px; letter-spacing: 0.04em; }}
  .sched-row {{ display: flex; gap: 8px; align-items: baseline; padding: 3px 0;
                border-bottom: 1px dotted #ddd; font-size: 11.5px; page-break-inside: avoid; }}
  .sched-time {{ width: 132px; flex-shrink: 0; color: #555; font-weight: 600;
                 font-variant-numeric: tabular-nums; }}
  .sched-tierbadge {{ width: 16px; flex-shrink: 0; text-align: center; border-radius: 3px;
                      font-size: 9px; font-weight: 700; padding: 1px 0; color: #fff; }}
  .sched-body {{ flex: 1 1 auto; min-width: 0; }}
  .sched-title {{ display: block; color: #1a1a1a; }}
  .sched-name {{ display: block; font-size: 10.5px; font-weight: 600; color: #666; }}
  .sched-note {{ font-size: 10.5px; color: #777; font-style: italic; padding: 3px 0 0 126px; }}
  .card {{ page-break-inside: avoid; border: 1px solid #ddd; border-left: 4px solid #999;
           border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }}
  .tier-badge {{ font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 10px;
                 white-space: nowrap; color: #fff; }}
  .meta {{ font-size: 11.5px; color: #555; margin-top: 1px; }}
  .geo-badge {{ display: inline-block; margin-left: 4px; font-size: 9.5px; background: #e6e6e6;
                border-radius: 8px; padding: 0px 6px; color: #333; }}
  .roles {{ font-size: 11px; color: #777; font-style: italic; margin: 2px 0 5px; }}
  .why {{ margin: 4px 0; }}
  .opener {{ margin: 5px 0; padding: 5px 7px; background: rgba(0,0,0,0.04); border-radius: 4px;
             font-style: italic; font-size: 12px; }}
  .ask {{ margin: 4px 0; font-size: 12px; }}
  .schedule {{ margin-top: 6px; border-top: 1px solid #e5e5e5; padding-top: 5px; }}
  .item-row {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; font-size: 11.5px;
               padding: 2px 0; }}
  .kind-tag {{ font-size: 9px; font-weight: 700; padding: 1px 5px; border-radius: 3px;
               text-transform: uppercase; flex-shrink: 0; }}
{kind_css}
  .item-title {{ flex: 1 1 auto; min-width: 140px; }}
  .item-loc {{ color: #555; font-weight: 600; white-space: nowrap; }}
  .section-break {{ page-break-before: always; }}

  @media (max-width: 480px) {{
    body {{ font-size: 15px; padding: 6px; }}
    .sched-row {{ flex-wrap: wrap; }}
    .sched-time {{ width: auto; }}
    .sched-body {{ flex-basis: 100%; padding-left: 24px; }}
    .sched-note {{ padding-left: 24px; }}
    .item-row {{ flex-direction: column; gap: 2px; }}
    .item-loc {{ font-weight: 700; }}
  }}
</style>
</head>
<body>

<h1>{_e(conference_name)} — Who to See</h1>
<div class="subtitle">Personal reference generated by conference_connector \u2014 not for distribution</div>
<div class="cover-note">
  {len(people)} people, ranked by fit to your research/outreach goals and how easy they are to
  actually approach. {legend_lines}.
  Posters show a board number and the session window it's staffed; talks and tutorials show an
  exact time and room where the source data provides one.
  The schedule below lists each session once, grouped by format, with everyone worth catching
  there named on the same line. Posters are capped at the {DEFAULT_MAX_POSTERS_PER_DAY}
  highest-scoring per day; the rest are on the person cards.
</div>

<h2>Day-by-day quick schedule</h2>
{_quick_index_html(schedule)}

{"".join(sections_html)}

</body>
</html>
"""


_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _find_chrome() -> str | None:
    for candidate in _CHROME_CANDIDATES:
        if os.path.isabs(candidate) or ":\\" in candidate:
            if Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def render_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Best-effort HTML->PDF via a locally installed Chrome/Chromium. Returns False
    (with guidance printed, not raised) rather than failing the whole card command --
    the HTML is already a complete, usable deliverable on its own."""
    chrome = _find_chrome()
    if not chrome:
        print(
            f"No Chrome/Chromium found for PDF export. HTML is ready at {html_path} -- "
            "open it in a browser and use Print > Save as PDF, or install Chrome and "
            "re-run with --pdf."
        )
        return False
    cmd = [
        chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}", f"file://{html_path.resolve()}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not pdf_path.exists():
        print("PDF export failed:", (result.stderr or "unknown error")[-500:])
        return False
    return True


def main(tiers: tuple[str, ...] = ("A", "B"), make_pdf: bool = False, exclude: set[str] | None = None) -> None:
    from conference_connector.ingest import items_path
    from conference_connector.preconditions import require_file

    require_file(items_path(), "conference_connector ingest <adapter>", "the ingested item list")
    require_file(item_scores_path(), "conference_connector prefilter", "your hand-written item scores")
    require_file(people_path(), "conference_connector rank", "the ranked people list")

    if exclude is None:
        exclude = set(config.load().get("card", {}).get("exclude_people", []))
    data = build_card_data(tiers=tiers, exclude=exclude)
    conference_name = config.conference_name()
    html_str = render_html(data, conference_name, tiers)

    out_dir = outputs_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "reference_card.html"
    html_path.write_text(html_str, encoding="utf-8")
    print(f"Wrote {len(data)} people to {html_path}")

    if make_pdf:
        pdf_path = out_dir / "reference_card.pdf"
        if render_pdf(html_path, pdf_path):
            print(f"Wrote {pdf_path}")
