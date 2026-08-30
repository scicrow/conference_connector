"""S4 — tutorials & workshops ingest from the (server-rendered) eccb2026.org page.

https://eccb2026.org/tutorials-workshops

Unlike the parallel-sessions schedule, this page's content is NOT behind an iframe --
it's a plain accordion (Alpine.js x-show) where all content is present statically in
the HTML and merely hidden by CSS/JS until clicked. One request gets everything:
Tutorials (T1-T14), Workshops (W1-W3), and ELIXIR workshops.
"""
from __future__ import annotations

import re

import ftfy

from conference_connector.html_utils import clean_text, strip_tags
from conference_connector.http_client import cached_get
from conference_connector.models import Item

URL = "https://eccb2026.org/tutorials-workshops"

_ROW_RE = re.compile(r'<tr\s+id="([\w-]+)"[^>]*class="scroll-mt-16[^"]*cursor-pointer"')
_TIME_ROOM_RE = re.compile(
    r'<td class="align-top font-medium[^"]*">([^<]+)</td>', re.S
)
_TITLE_RE = re.compile(r"<span>([^<]{5,250})</span>")

# Most entries have "Organized by:</strong> Name1, Name2</p>" immediately after the
# closing tag. A minority are pasted from Word/Office (data-ccp-* spans wrap every
# few words) so the plain-text-then-</p> assumption fails. Some entries also insert
# an extra "Topic:" field between organisers and the scientific area/overview.
# Rather than assume a fixed field order, find every labelled-field marker, sort by
# position, and take each field's text as "up to the next marker" -- robust to any
# subset/order of {Organized by, Topic, Scientific area, Overview, Abstract}.
_FIELD_MARKER_RE = re.compile(
    r"(Organized by|Topic|Scientific area|Overview|Abstract):\s*</strong>", re.I
)


def _split_top_level(raw: str) -> list[str]:
    """Split a comma-separated name list, but never inside parentheses.

    Needed for entries like "Cristian Iperi (USZ Universitätsspital Zürich,
    Switzerland), Jessica Gliozzo (..., Milan, Italy)" where a naive comma-split
    would shred each parenthetical affiliation into its own bogus "name".
    """
    raw = raw.replace(" and ", ", ")
    parts: list[str] = []
    depth = 0
    current = []
    for ch in raw:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p]


def fetch_all(refresh: bool = False) -> list[Item]:
    html = cached_get(URL, source="eccb_workshops", key="tutorials-workshops", ext="html", refresh=refresh)
    html = ftfy.fix_text(html)
    return _parse(html)


def _parse(html: str) -> list[Item]:
    row_matches = list(_ROW_RE.finditer(html))
    out: list[Item] = []
    for i, m in enumerate(row_matches):
        slug = m.group(1)
        start = m.start()
        end = row_matches[i + 1].start() if i + 1 < len(row_matches) else len(html)
        block = html[start:end]

        time_room_m = _TIME_ROOM_RE.search(block)
        time_room = clean_text(time_room_m.group(1)) if time_room_m else ""
        room = None
        if " - " in time_room:
            room = time_room.rsplit(" - ", 1)[1].strip()

        title_m = _TITLE_RE.search(block)
        raw_title = clean_text(title_m.group(1)) if title_m else slug
        code, _, rest = raw_title.partition(":")
        if re.match(r"^[TWE]\d+$", code.strip()):
            title = rest.strip()
        else:
            title = raw_title

        markers = list(_FIELD_MARKER_RE.finditer(block))
        fields: dict[str, str] = {}
        for idx, mk in enumerate(markers):
            label = mk.group(1).strip().lower()
            seg_start = mk.end()
            seg_end = markers[idx + 1].start() if idx + 1 < len(markers) else None
            if seg_end is None:
                rest_block = block[seg_start:]
                close_m = re.search(r"</div>\s*</div>\s*</td>\s*</tr>", rest_block)
                seg_html = rest_block[: close_m.start()] if close_m else rest_block
            else:
                seg_html = block[seg_start:seg_end]
            fields.setdefault(label, strip_tags(seg_html))

        organisers = _split_top_level(fields.get("organized by", ""))
        area = fields.get("scientific area", "")
        topic = fields.get("topic", "")
        if area and topic:
            area = f"{area} — {topic}"
        elif topic:
            area = topic
        overview = fields.get("overview") or fields.get("abstract") or ""

        kind = "tutorial" if slug.startswith("t") and not slug.startswith("elixir") else (
            "workshop" if slug.startswith("w") else "workshop"
        )
        if slug.startswith("elixir"):
            kind = "workshop"

        out.append(
            Item(
                item_id=f"{kind}:{slug}",
                kind=kind,
                title=title,
                abstract=overview,
                track=area,
                room=room,
                day="Thursday 3 September" if not slug.startswith("elixir") else "Thursday 3 September",
                organisers=organisers,
                source="S4",
                url=f"{URL}#{slug}",
            )
        )
    return out


if __name__ == "__main__":
    result = fetch_all()
    print(f"Fetched {len(result)} tutorials/workshops")
    for it in result:
        print(f"  {it.item_id:60s} organisers={it.organisers}")
        print(f"      room={it.room!r} abstract_len={len(it.abstract)}")
