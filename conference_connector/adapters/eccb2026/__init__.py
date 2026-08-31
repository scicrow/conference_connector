"""Reference adapter: ECCB 2026 (European Conference on Computational Biology, Geneva).

Not a general "ISCB platform" adapter -- these four sub-modules were reverse-engineered
against ECCB 2026's actual pages on 28 Aug 2026 and are known to work for that
conference specifically. Other ISCB-family conferences (ISMB, RECOMB, PSB, ...) share
some infrastructure (transition.iscb.org) but have NOT been verified to use the same
URL grammar, board-ID format, or page markup -- treat this as a worked example and a
starting point for writing their adapters, not as a drop-in.

See conference_connector/skills/conference-scout/references/adapter-authoring.md for the four real bugs
found building this (each one silently dropped or mis-parsed a chunk of the data) and
the checks that would have caught them.
"""
from __future__ import annotations

from conference_connector.adapters.eccb2026 import eccb_keynotes, eccb_workshops, iscb_posters, iscb_talks
from conference_connector.models import Item

SLUG = "eccb2026"


def fetch_all(refresh: bool = False) -> list[Item]:
    items: list[Item] = []
    items += iscb_posters.fetch_all(refresh=refresh)
    items += iscb_talks.fetch_all(refresh=refresh)
    items += eccb_workshops.fetch_all(refresh=refresh)
    items += eccb_keynotes.fetch_all(refresh=refresh)
    return items
