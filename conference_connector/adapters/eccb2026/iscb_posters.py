"""S1 — poster ingest from the ISCB transition-page endpoint.

https://transition.iscb.org/cms_addon/conferences/eccb2026/posters.php?track={T}&session={S}

21 requests (7 tracks x 3 sessions) return ~840 posters total with board ID, track,
full author list (with affiliation + country), presenting author, and abstract.

Board ID grammar: "{Session}-{TrackCode}.{NN}", e.g. "A-G.01", "C-S.B.12", "B-ELIXIR.03".
TrackCode is NOT always a single letter (SysBio -> "S.B", GenCompBio -> "G.C",
Elixir -> "ELIXIR") -- a naive single-letter regex silently drops ~300 posters.
"""
from __future__ import annotations

import re

from conference_connector.html_utils import clean_text, parse_author_string, strip_tags
from conference_connector.http_client import cached_get
from conference_connector.models import Author, Item

BASE_URL = "https://transition.iscb.org/cms_addon/conferences/eccb2026/posters.php"

TRACKS = ["Biodiversity", "Elixir", "GenCompBio", "Genomics", "Proteins", "SysBio", "Transcriptomics"]
SESSIONS = ["A", "B", "C"]

# Board id: session letter, dash, track code (may itself contain dots/letters), dot, number.
BOARD_RE = re.compile(r"^([A-C])-(.+)\.(\d{2,3})$")

# Each poster session (the board-id's leading letter) is staffed at one fixed
# conference-wide window -- confirmed against the ECCB 2026 programme. Decoding this
# gives every poster a day/time for free, with no extra request: without it, posters
# have no schedule info at all and can't appear in any chronological view.
_SESSION_WINDOWS = {
    "A": ("Monday 31 August", "12:00", "13:30"),
    "B": ("Tuesday 1 September", "16:15", "17:45"),
    "C": ("Wednesday 2 September", "11:30", "13:00"),
}

_ENTRY_SPLIT_RE = re.compile(r"<div class='well well-sm'>")
_TITLE_RE = re.compile(r"<strong>([^<]+)</strong>")
_TRACK_RE = re.compile(r"<strong>Track:</strong>\s*([^<]+)")
_AUTHOR_LIST_RE = re.compile(r"<ul[^>]*>(.*?)</ul>\s*<!-- END AUTHORS-->", re.S)
_AUTHOR_LI_RE = re.compile(r"<li class='author'>(.*?)</li>", re.S)
_ABSTRACT_RE = re.compile(
    r"Presentation Overview:.*?<div style='display:none;'\s*>\s*<p>(.*?)</p>\s*</div>", re.S
)


def fetch_all(refresh: bool = False) -> list[Item]:
    items: dict[str, Item] = {}
    for track in TRACKS:
        for session in SESSIONS:
            key = f"{track}_{session}"
            html = cached_get(
                BASE_URL,
                source="iscb_posters",
                key=key,
                ext="html",
                refresh=refresh,
                params={"track": track, "session": session},
            )
            html = clean_text_preserve_tags(html)
            for item in _parse_page(html, track_hint=track):
                # Same poster can legitimately appear once; dedupe defensively by item_id.
                items[item.item_id] = item
    return list(items.values())


def clean_text_preserve_tags(html: str) -> str:
    """Fix mojibake across the whole page while keeping HTML tags intact."""
    import ftfy

    return ftfy.fix_text(html)


def _parse_page(html: str, track_hint: str) -> list[Item]:
    chunks = _ENTRY_SPLIT_RE.split(html)[1:]  # first chunk is pre-content boilerplate
    out: list[Item] = []
    for chunk in chunks:
        item = _parse_entry(chunk, track_hint)
        if item is not None:
            out.append(item)
    return out


def _parse_entry(chunk: str, track_hint: str) -> Item | None:
    title_m = _TITLE_RE.search(chunk)
    if not title_m:
        return None
    raw_title = clean_text(title_m.group(1))

    board_id = None
    title = raw_title
    if ":" in raw_title:
        maybe_board, _, rest = raw_title.partition(":")
        if BOARD_RE.match(maybe_board.strip()):
            board_id = maybe_board.strip()
            title = rest.strip()

    track_m = _TRACK_RE.search(chunk)
    track = clean_text(track_m.group(1)) if track_m else track_hint

    authors: list[Author] = []
    author_list_m = _AUTHOR_LIST_RE.search(chunk)
    author_block = author_list_m.group(1) if author_list_m else chunk
    author_lis = _AUTHOR_LI_RE.findall(author_block)
    for i, li_html in enumerate(author_lis, start=1):
        is_presenter = "<strong>" in li_html and "<u>" in li_html
        raw_author = strip_tags(li_html)
        parsed = parse_author_string(raw_author)
        if not parsed["name"]:
            continue
        authors.append(
            Author(
                **parsed,
                position=i,
                is_presenter=is_presenter,
                is_last=False,  # fixed up below once we know the count
            )
        )
    if authors:
        authors[-1].is_last = True
        # Fallback: if nobody was marked as presenter (rare formatting miss),
        # treat the first author as the de-facto presenter.
        if not any(a.is_presenter for a in authors):
            authors[0].is_presenter = True

    abstract_m = _ABSTRACT_RE.search(chunk)
    abstract = strip_tags(abstract_m.group(1)) if abstract_m else ""

    day = start = end = None
    if board_id:
        window = _SESSION_WINDOWS.get(board_id[0])
        if window:
            day, start, end = window

    item_key = board_id or re.sub(r"\W+", "-", title.lower()).strip("-")[:80]
    return Item(
        item_id=f"poster:{item_key}",
        kind="poster",
        title=title,
        abstract=abstract,
        track=track,
        board_id=board_id,
        day=day,
        start=start,
        end=end,
        authors=authors,
        source="S1",
        url=BASE_URL,
    )


if __name__ == "__main__":
    result = fetch_all()
    print(f"Fetched {len(result)} posters")
    with_board = sum(1 for it in result if it.board_id)
    print(f"  with board id: {with_board}")
    with_abstract = sum(1 for it in result if it.abstract)
    print(f"  with abstract: {with_abstract}")
    with_authors = sum(1 for it in result if it.authors)
    print(f"  with authors: {with_authors}")
