"""S5 — keynote speakers, from the (server-rendered) eccb2026.org page.

https://eccb2026.org/keynote-speakers

One request, ~4 speakers. High seniority signal, low realistic access -- these are
the most besieged people at the conference -- but their biography and lecture title
are useful context for dossiers, and worth including in the person pivot regardless.
"""
from __future__ import annotations

import re

import ftfy

from conference_connector.html_utils import clean_text, strip_tags
from conference_connector.http_client import cached_get
from conference_connector.models import Author, Item

URL = "https://eccb2026.org/keynote-speakers"

_SPEAKER_BLOCK_RE = re.compile(r'<div id="[\w-]+" class="[^"]*\bspeaker\b[^"]*"')
_NAME_RE = re.compile(r'<h2 class="speaker-name">([^<]+)</h2>')
_AFFIL_RE = re.compile(r'<div class="font-medium text-gray-600\s*">([^<]+)</div>')
_BIO_MARKER_RE = re.compile(r"Biography\s*</strong>\s*<br\s*/?>")
_LECTURE_MARKER_RE = re.compile(r"is giving a keynote lecture on", re.I)


def fetch_all(refresh: bool = False) -> list[Item]:
    html = cached_get(URL, source="eccb_keynotes", key="keynote-speakers", ext="html", refresh=refresh)
    html = ftfy.fix_text(html)
    return _parse(html)


def _parse(html: str) -> list[Item]:
    blocks = list(_SPEAKER_BLOCK_RE.finditer(html))
    out: list[Item] = []
    for i, m in enumerate(blocks):
        start = m.start()
        end = blocks[i + 1].start() if i + 1 < len(blocks) else len(html)
        block = html[start:end]

        name_m = _NAME_RE.search(block)
        if not name_m:
            continue
        name = clean_text(name_m.group(1))

        affil_m = _AFFIL_RE.search(block)
        affiliation = clean_text(affil_m.group(1)) if affil_m else ""

        bio_m = _BIO_MARKER_RE.search(block)
        lecture_m = _LECTURE_MARKER_RE.search(block)

        biography = ""
        if bio_m:
            seg_end = lecture_m.start() if lecture_m else len(block)
            biography = strip_tags(block[bio_m.end():seg_end])

        day, lecture_title = None, ""
        if lecture_m:
            # Bound the tail at the enclosing </p> and parse from clean text --
            # the markup here has mismatched <strong>/<em> nesting, so tag-stripping
            # first and pattern-matching the plain text is far more robust.
            tail_html = block[lecture_m.start():]
            close_m = re.search(r"</p>", tail_html)
            tail_html = tail_html[: close_m.start()] if close_m else tail_html
            tail_text = strip_tags(tail_html)
            m2 = re.match(r"is giving a keynote lecture on ([^:]+):\s*(.+)$", tail_text, re.I)
            if m2:
                day = m2.group(1).strip()
                lecture_title = m2.group(2).strip(" “”\"'")

        slug = re.sub(r"\W+", "-", name.lower()).strip("-")
        # The speaker's name/affiliation are carried as a single pseudo-author so
        # they flow through the same person-pivot path (Stage 4) as every other
        # item's authors.
        out.append(
            Item(
                item_id=f"keynote:{slug}",
                kind="keynote",
                title=lecture_title or f"Keynote: {name}",
                abstract=biography,
                authors=[
                    Author(
                        name=name,
                        affiliation_norm=affiliation,
                        position=1,
                        is_presenter=True,
                        is_last=True,
                    )
                ],
                day=day,
                source="S5",
                url=URL,
            )
        )
    return out


if __name__ == "__main__":
    result = fetch_all()
    print(f"Fetched {len(result)} keynotes")
    for it in result:
        a = it.authors[0]
        print(f"  {a.name:28s} | {a.affiliation_norm:45s} | {it.day} | {it.title}")
