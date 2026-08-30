"""The contract every adapter implements.

An adapter turns one conference's website into a list of conference_connector.models.Item. That's
the whole interface -- how it gets there (scraping HTML, calling a REST API, reading an
iCal export) is entirely up to the adapter.
"""
from __future__ import annotations

from typing import Protocol

from conference_connector.models import Item


class Adapter(Protocol):
    """Module-level protocol: an adapter is any module exposing SLUG and fetch_all."""

    SLUG: str

    def fetch_all(self, refresh: bool = False) -> list[Item]:
        """Fetch and normalise every item this adapter knows how to get.

        Must use conference_connector.http_client.cached_get (or cache raw responses some other
        way) so re-runs don't re-hit the target server. Must run every extracted
        string through conference_connector.html_utils.clean_text (mojibake is common and silent).
        """
        ...
