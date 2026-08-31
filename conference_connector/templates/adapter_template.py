"""Starter adapter -- copy this into your project and edit it.

    conference_connector init            # also drops a copy at ./my_adapter.py
    # ... edit the URL and the three parse points marked EDIT below ...
    python my_adapter.py                 # parse from cache + validate, no pipeline needed
    conference_connector ingest myconf    # once the counts look right

An adapter's entire contract is: expose SLUG and fetch_all(refresh) -> list[Item].
Everything downstream (scoring, the person pivot, ranking, rendering) is already
handled -- you only ever write the part that knows this one conference's markup.

Read conference_connector/skills/conference-scout/references/adapter-authoring.md before you start. It has
the bug catalogue from the reference adapter; every bug in it was silent (the parser
ran fine and returned wrong or incomplete data), which is why the __main__ block below
validates instead of just printing a count.
"""
from __future__ import annotations

import re

from conference_connector.html_utils import clean_text, parse_author_string, strip_tags
from conference_connector.http_client import cached_get
from conference_connector.models import Author, Item

# The slug you'll pass to `conference_connector ingest <slug>`.
SLUG = "myconf"

# EDIT 1: where the data actually lives. Run `conference_connector recon <url>` first --
# the page a human browses is often not the page holding the data (it may be an iframe
# to another host, an embedded JSON blob, or a plain REST endpoint underneath a fancy UI).
URL = "https://example-conference.org/programme"

# EDIT 2: the repeating marker that separates one entry from the next in the raw HTML.
# Find it by opening the cached file under data/raw/ in an editor. Count how many times
# it occurs -- that count is what your parser must return, and the check at the bottom
# of this file compares the two for you.
ENTRY_SPLIT_RE = re.compile(r"<div class=\"session-item\">")


def fetch_all(refresh: bool = False) -> list[Item]:
    html = cached_get(URL, source=SLUG, key="programme", ext="html", refresh=refresh)
    return _parse(html)


def _parse(html: str) -> list[Item]:
    chunks = ENTRY_SPLIT_RE.split(html)[1:]  # [0] is everything before the first entry
    items: list[Item] = []
    for i, chunk in enumerate(chunks):
        item = _parse_entry(chunk, i)
        if item is not None:
            items.append(item)
    return items


def _parse_entry(chunk: str, seq: int) -> Item | None:
    # EDIT 3: pull the fields out of one entry. clean_text() is not optional -- it runs
    # ftfy, and mojibake (double-encoded UTF-8) silently corrupts author names, which
    # are the join keys the person pivot groups on.
    title_m = re.search(r"<h3[^>]*>(.*?)</h3>", chunk, re.S)
    if not title_m:
        return None
    title = strip_tags(title_m.group(1))

    abstract_m = re.search(r"<p class=\"abstract\">(.*?)</p>", chunk, re.S)
    abstract = strip_tags(abstract_m.group(1)) if abstract_m else ""

    authors: list[Author] = []
    for pos, raw in enumerate(re.findall(r"<li class=\"author\">(.*?)</li>", chunk, re.S), start=1):
        parsed = parse_author_string(strip_tags(raw))
        if parsed["name"]:
            authors.append(Author(**parsed, position=pos))
    if authors:
        authors[-1].is_last = True
        if not any(a.is_presenter for a in authors):
            authors[0].is_presenter = True

    return Item(
        item_id=f"talk:{seq:04d}",     # must be unique; prefer a real code if the site has one
        kind="talk",                    # poster | talk | keynote | tutorial | workshop
        title=title,
        abstract=abstract,
        authors=authors,
        day=clean_text(""),             # fill these in if the source has them --
        start=None,                     # they're what makes the reference card useful
        end=None,
        room=None,
        url=URL,
        source=SLUG,
    )


if __name__ == "__main__":
    # Parse from cache and check the result, rather than trusting that "it ran".
    from conference_connector.validate import format_report, validate

    if "example-conference.org" in URL:
        raise SystemExit(
            "URL is still the placeholder. Run `conference_connector recon <your "
            "conference URL>` first to find where the data actually lives, then set "
            "URL (EDIT 1) before running this."
        )

    try:
        parsed = fetch_all()
        raw = cached_get(URL, source=SLUG, key="programme", ext="html")
    except Exception as e:  # noqa: BLE001 -- a bad URL here is a normal authoring mistake
        raise SystemExit(
            f"Could not fetch {URL}\n  {type(e).__name__}: {e}\n\n"
            "Check the URL is reachable (try it in a browser). If the site needs a "
            "login or renders only via JS, this adapter shape won't reach it -- re-run "
            "recon and look for an API endpoint or embedded JSON instead."
        ) from None

    expected = len(ENTRY_SPLIT_RE.findall(raw))
    print(f"entry markers in raw HTML: {expected}")
    print(f"items returned by parser : {len(parsed)}")
    if expected and len(parsed) < expected:
        print(
            f"  -> {expected - len(parsed)} entries were dropped. This is the most common "
            "adapter bug and it is always silent; fix it before going further."
        )
    print()
    print(format_report(validate(parsed)))
