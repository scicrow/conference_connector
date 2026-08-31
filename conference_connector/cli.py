"""conference_connector -- conference research pipeline.

    conference_connector recon <url>                # look at a page before scraping anything -- run this FIRST
    conference_connector ingest <adapter> [--refresh]
    conference_connector validate <adapter> [--refresh]
    conference_connector prefilter                  # keyword-prefilter -> data/interim/candidates_for_review.md
    conference_connector rank                       # item_scores.json (hand-written) -> people.json
    conference_connector render                     # item_scores.json + people.json -> outputs/*
    conference_connector card [--tiers A,B] [--pdf] # people.json -> outputs/reference_card.{html,pdf}

<adapter> is a registered adapter slug (see conference_connector.adapters), e.g. "eccb2026".

`card` builds a phone-browsable "who to see" reference: a day-by-day schedule plus one
card per person (day/time/room/board for every item), pulling in outputs/dossiers/*.md
if present for a hand-written hook/opener/ask, and falling back to item_scores.json's
`why` otherwise. --tiers defaults to A,B; --pdf attempts a local Chrome/Chromium for
PDF export (falls back to HTML-only with instructions if none is found).

Note on scoring: there is no `conference_connector score` command that calls an LLM API over the
full item pool. By design, the close-reading/scoring pass over the keyword-prefiltered
candidates (data/interim/candidates_for_review.md) is done by a human or an
LLM-in-the-loop session reading the file directly and hand-writing
data/processed/item_scores.json -- see skills/conference-scout/references/close-reading.md.
Re-run `rank` after editing item_scores.json to rebuild people.json from it.

Environment:
    CONFERENCE_CONNECTOR_CONTACT       optional, for any network request -- adds your
                             own contact on top of the default User-Agent (which
                             already identifies the tool + its GitHub URL).
    CONFERENCE_CONNECTOR_CONFIG_DIR    default: ./config
    CONFERENCE_CONNECTOR_DATA_DIR      default: ./data
    CONFERENCE_CONNECTOR_OUTPUT_DIR    default: ./outputs
"""
from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]
    refresh = "--refresh" in args
    positional = [a for a in args if not a.startswith("--")]

    if cmd == "recon":
        if not positional:
            print("usage: conference_connector recon <url>")
            sys.exit(1)
        from conference_connector import recon

        recon.main(positional[0])

    elif cmd == "ingest":
        if not positional:
            print("usage: conference_connector ingest <adapter> [--refresh]")
            sys.exit(1)
        from conference_connector import ingest

        ingest.main(positional[0], refresh=refresh)

    elif cmd == "validate":
        if not positional:
            print("usage: conference_connector validate <adapter> [--refresh]")
            sys.exit(1)
        from conference_connector import validate

        validate.main(positional[0], refresh=refresh)

    elif cmd == "prefilter":
        from conference_connector import score

        score.main()

    elif cmd == "rank":
        from conference_connector import pivot

        pivot.main()

    elif cmd == "render":
        from conference_connector import render

        render.main()

    elif cmd == "card":
        from conference_connector import card

        tiers_arg = next((a.split("=", 1)[1] for a in args if a.startswith("--tiers=")), "A,B")
        tiers = tuple(t.strip() for t in tiers_arg.split(",") if t.strip())
        make_pdf = "--pdf" in args
        card.main(tiers=tiers, make_pdf=make_pdf)

    else:
        print(f"Unknown command: {cmd}\n")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
