"""Reference card: a phone/print-friendly HTML+PDF summary of who to see at the
conference, built from the ranked shortlist.

This is the last stage of the pipeline, downstream of `rank`. It doesn't do anything
that requires reading text or judgement -- the judgement already happened during the
close-read (item_scores.json's `why`) and, optionally, during outreach-writing
(outputs/dossiers/*.md, if the skill wrote them per
skills/conference-scout/references/outreach-writing.md). This module just assembles
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
from pathlib import Path

from conference_connector import config
from conference_connector.ingest import load_items
from conference_connector.pivot import item_scores_path, people_path
from conference_connector.paths import outputs_dir
from conference_connector.render import ROLE_LABEL, TIER_LABEL, _conference_name, _geo_labels

TIER_COLORS = {
    "A": ("#b8860b", "#fffdf7"),
    "B": ("#4a6fa5", "#f7fafd"),
    "C": ("#5a8f5a", "#f5faf5"),
    "D": ("#8a4a9a", "#faf5fb"),
}
_DEFAULT_TIER_COLOR = ("#777777", "#f7f7f7")

KIND_COLORS = {
    "poster": ("#dcebe0", "#1e5631"),
    "talk": ("#dde6f5", "#1d3f7a"),
    "tutorial": ("#f5e6dd", "#7a3f1d"),
    "workshop": ("#f0e0f0", "#6a1d7a"),
    "keynote": ("#f5dde0", "#7a1d3f"),
}

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"]
    )
}
_DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(_MONTHS) + r")", re.I)


def _date_key(day: str | None) -> tuple[int, int]:
    """Parse a human day string ("Monday 31 August") into a (month, day) sort key,
    independent of weekday naming or which conference/year this is."""
    if not day:
        return (99, 99)
    m = _DATE_RE.search(day.lower())
    if not m:
        return (99, 99)
    return (_MONTHS[m.group(2).lower()], int(m.group(1)))


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
    geo_labels = _geo_labels()

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
        rows.sort(key=lambda r: r["_sort"])
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


def _quick_index_html(people: list[dict]) -> str:
    by_day: dict[str, list[tuple]] = {}
    for p in people:
        for it in p["items"]:
            by_day.setdefault(it["day"], []).append((it["_sort"][1] if "_sort" in it else 0, p["name"], it))
    days_sorted = sorted(by_day.keys(), key=_date_key)

    out = []
    for day in days_sorted:
        if not day:
            continue
        entries = by_day[day]
        entries.sort(key=lambda e: e[0])
        out.append(f"<h3 class='day-head'>{_e(day)}</h3>")
        for _, name, it in entries:
            tier = next((p["tier"] for p in people if p["name"] == name), "?")
            color = TIER_COLORS.get(tier, _DEFAULT_TIER_COLOR)[0]
            title_text = "; ".join(it["titles"])
            out.append(
                f"<div class='sched-row'><span class='sched-time'>{_e(it['time'])}</span>"
                f"<span class='sched-tierbadge' style='background:{color}'>{_e(tier)}</span>"
                f"<span class='sched-name'>{_e(name)}</span>"
                f"<span class='sched-what'>{_e(it['kind'].capitalize())} \u00b7 {_e(it['loc'])} \u2014 {_e(title_text)}</span></div>"
            )
    return "\n".join(out)


def render_html(people: list[dict], conference_name: str, tiers: tuple[str, ...]) -> str:
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
  .day-head {{ font-size: 13px; margin: 10px 0 4px; color: #444; }}
  .sched-row {{ display: flex; gap: 8px; align-items: baseline; padding: 3px 0;
                border-bottom: 1px dotted #ddd; font-size: 11.5px; }}
  .sched-time {{ width: 70px; flex-shrink: 0; color: #555; font-variant-numeric: tabular-nums; }}
  .sched-tierbadge {{ width: 16px; flex-shrink: 0; text-align: center; border-radius: 3px;
                      font-size: 9px; font-weight: 700; padding: 1px 0; color: #fff; }}
  .sched-name {{ width: 150px; flex-shrink: 0; font-weight: 600; }}
  .sched-what {{ color: #333; }}
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
    .sched-name {{ width: auto; }}
    .sched-what {{ flex-basis: 100%; padding-left: 24px; color: #555; }}
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
</div>

<h2>Day-by-day quick schedule</h2>
{_quick_index_html(people)}

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
    if exclude is None:
        exclude = set(config.load().get("card", {}).get("exclude_people", []))
    data = build_card_data(tiers=tiers, exclude=exclude)
    conference_name = _conference_name()
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
