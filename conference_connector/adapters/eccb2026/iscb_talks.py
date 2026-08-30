"""S3 — parallel-session talk ingest from the ISCB transition-page endpoint.

https://transition.iscb.org/cms_addon/conferences/eccb2026/schedule/{Area}

6 requests return the full parallel-session programme (~81 talks + 9 Elixir talks)
with day, time, room, session chairs/moderators, confirmed presenter, full author
list with affiliations, and abstract.
"""
from __future__ import annotations

import re

import ftfy

from conference_connector.html_utils import clean_text, parse_author_string, strip_tags
from conference_connector.http_client import cached_get
from conference_connector.models import Author, Item

BASE_URL = "https://transition.iscb.org/cms_addon/conferences/eccb2026/schedule"

AREAS = ["Genomics", "Transcriptomics", "Proteins", "SysBio", "Biodiversity", "Elixir"]

_DAY_RE = re.compile(r"bigSessionDate'>\s*([^<]+?)\s*</div")
_ROW_START = "<div class='row schedulerow'>"
_TIME_RE = re.compile(
    r"timeSpans'>\s*([\d:]+-[\d:]+)\s*<br\s*/?>\s*(?:Session:\s*)?([^<]*)</div", re.S
)
# Anchors one talk block. Each schedulerow is a one-hour slot containing THREE such
# blocks back to back (site copy: "Each one-hour parallel session comprises three
# talks") -- splitting only at the row level and taking the first title per row
# silently drops 2 of every 3 talks.
_TALK_BLOCK_START_RE = re.compile(r"<div class='well well-smb \w+'>")
_TALK_TITLE_RE = re.compile(r"well-smb (\w+)'>\s*<strong>([^<]+)</strong>", re.S)
_PRESENTER_RE = re.compile(
    r"<div class='room'>\s*<strong>Confirmed Presenter:</strong>\s*(.*?)</div>", re.S
)
_ROOM_RE = re.compile(r"pull-right'>\s*<strong>Room:</strong>\s*(.*?)</div>", re.S)
_MODERATOR_RE = re.compile(r"pull-left'>\s*<strong>Moderator\(s\):</strong>\s*(.*?)</div>", re.S)
_AUTHORS_UL_RE = re.compile(r"<ul class='authorsList'>(.*?)</ul>", re.S)
_AUTHOR_LI_RE = re.compile(r"<li>(.*?)</li>", re.S)
_ABSTRACT_RE = re.compile(
    r"Presentation Overview:.*?<div style='display:none;'\s*>\s*<p>(.*?)</p>", re.S
)

_PRESENTATION_LABELS = {
    "proceedings": "Proceedings Presentation",
    "abstract": "Highlight Talk",
    "invited": "Invited",
    "remarks": "Remarks",
    "panel": "Panel",
}


def fetch_all(refresh: bool = False) -> list[Item]:
    items: dict[str, Item] = {}
    for area in AREAS:
        html = cached_get(
            f"{BASE_URL}/{area}",
            source="iscb_talks",
            key=area,
            ext="html",
            refresh=refresh,
        )
        html = ftfy.fix_text(html)
        for item in _parse_page(html, area_hint=area):
            items[item.item_id] = item
    return list(items.values())


def _parse_page(html: str, area_hint: str) -> list[Item]:
    day_matches = [(m.start(), clean_text(m.group(1))) for m in _DAY_RE.finditer(html)]
    row_starts = [m.start() for m in re.finditer(re.escape(_ROW_START), html)]

    out: list[Item] = []
    seq = 0
    for i, start in enumerate(row_starts):
        row_end = row_starts[i + 1] if i + 1 < len(row_starts) else len(html)
        row_chunk = html[start:row_end]
        day = None
        for pos, d in day_matches:
            if pos <= start:
                day = d
            else:
                break

        time_m = _TIME_RE.search(row_chunk)
        start_end, session_name = ("", "")
        if time_m:
            start_end, session_name = time_m.group(1), clean_text(time_m.group(2))
        slot_start, _, slot_end = start_end.partition("-")

        # Split the one-hour slot into its individual talk blocks.
        block_starts = [m.start() for m in _TALK_BLOCK_START_RE.finditer(row_chunk)]
        for j, bstart in enumerate(block_starts):
            bend = block_starts[j + 1] if j + 1 < len(block_starts) else len(row_chunk)
            talk_chunk = row_chunk[bstart:bend]
            item = _parse_talk_block(
                talk_chunk,
                day=day,
                area_hint=area_hint,
                seq=seq,
                slot_start=slot_start,
                slot_end=slot_end,
                session_name=session_name or None,
            )
            if item is not None:
                out.append(item)
                seq += 1
    return out


def _parse_talk_block(
    chunk: str,
    day: str | None,
    area_hint: str,
    seq: int,
    slot_start: str | None = None,
    slot_end: str | None = None,
    session_name: str | None = None,
) -> Item | None:
    title_m = _TALK_TITLE_RE.search(chunk)
    if not title_m:
        return None
    kind_class, raw_title = title_m.groups()
    raw_title = clean_text(raw_title)

    presentation_type = _PRESENTATION_LABELS.get(kind_class, kind_class)
    prefix = f"{presentation_type}:"
    title = raw_title[len(prefix):].strip() if raw_title.startswith(prefix) else raw_title

    room_m = _ROOM_RE.search(chunk)
    room = strip_tags(room_m.group(1)) if room_m else None

    mod_m = _MODERATOR_RE.search(chunk)
    chairs = [clean_text(c) for c in strip_tags(mod_m.group(1)).split(";") if c.strip()] if mod_m else []

    presenter_m = _PRESENTER_RE.search(chunk)
    presenter_raw = strip_tags(presenter_m.group(1)) if presenter_m else ""
    presenter_name = parse_author_string(presenter_raw)["name"] if presenter_raw else ""

    authors: list[Author] = []
    ul_m = _AUTHORS_UL_RE.search(chunk)
    author_lis = _AUTHOR_LI_RE.findall(ul_m.group(1)) if ul_m else []
    for i, li_html in enumerate(author_lis, start=1):
        is_presenter = "class='speaker'" in li_html
        raw_author = strip_tags(li_html)
        parsed = parse_author_string(raw_author)
        if not parsed["name"]:
            continue
        authors.append(Author(**parsed, position=i, is_presenter=is_presenter, is_last=False))
    if authors:
        authors[-1].is_last = True
        if not any(a.is_presenter for a in authors) and presenter_name:
            for a in authors:
                if a.name == presenter_name:
                    a.is_presenter = True
                    break

    abstract_m = _ABSTRACT_RE.search(chunk)
    abstract = strip_tags(abstract_m.group(1)) if abstract_m else ""

    slug = re.sub(r"\W+", "-", title.lower()).strip("-")[:80]
    item_key = f"{area_hint}-{seq:03d}-{slug}"

    return Item(
        item_id=f"talk:{item_key}",
        kind="talk",
        title=title,
        abstract=abstract,
        track=area_hint,
        session_name=session_name or None,
        presentation_type=presentation_type,
        day=day,
        start=slot_start or None,
        end=slot_end or None,
        room=room,
        authors=authors,
        chairs=chairs,
        source="S3",
        url=f"{BASE_URL}/{area_hint}",
    )


if __name__ == "__main__":
    result = fetch_all()
    print(f"Fetched {len(result)} talks")
    for it in result[:3]:
        print(f"  {it.item_id} | {it.day} {it.start}-{it.end} | {it.room} | chairs={it.chairs}")
        print(f"    authors={len(it.authors)}  presenter={[a.name for a in it.authors if a.is_presenter]}")
