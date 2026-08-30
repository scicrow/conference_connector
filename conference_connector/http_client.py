"""Polite, disk-cached HTTP GET. Used by every adapter and by recon.

Caches raw response bytes under {data_dir}/raw/{source}/{key}.{ext} so re-runs never
re-hit the target server. Rate-limits to one request at a time per host with a short
delay, and identifies itself in every request's User-Agent -- this tool points agents
at servers run by other people; it should never look anonymous.

By default that identification is just this project (name, version, a link back to
the GitHub repo) -- enough for a site admin who notices unusual traffic to find out
what's hitting their server and where to raise a concern, with no personal
information from you required. If you want to add your own contact on top of that
(not required), set it in config.yaml (`contact: you@example.com`, or any contact
string -- a project alias, a lab website, etc.) or override it per-shell with
CONFERENCE_CONNECTOR_CONTACT.
"""
from __future__ import annotations

import os
import time

import httpx

from conference_connector import __version__
from conference_connector.paths import raw_dir

PROJECT_URL = "https://github.com/scicrow/conference_connector"

_MIN_DELAY_S = 0.6
_last_request_time: dict[str, float] = {}


def user_agent() -> str:
    from conference_connector import config

    contact = os.environ.get("CONFERENCE_CONNECTOR_CONTACT") or config.load().get("contact")
    detail = f"+{PROJECT_URL}" + (f"; contact: {contact}" if contact else "")
    return f"conference_connector/{__version__} ({detail})"


def _throttle(host: str) -> None:
    last = _last_request_time.get(host)
    now = time.monotonic()
    if last is not None:
        wait = _MIN_DELAY_S - (now - last)
        if wait > 0:
            time.sleep(wait)
    _last_request_time[host] = time.monotonic()


def fetch(url: str, params: dict | None = None, timeout: float = 40.0) -> httpx.Response:
    """A single polite, throttled, identified GET. No caching -- used by recon, which
    deliberately touches few URLs and wants live responses, not cache hits."""
    host = httpx.URL(url).host
    _throttle(host)
    resp = httpx.get(
        url,
        params=params,
        headers={"User-Agent": user_agent()},
        timeout=timeout,
        follow_redirects=True,
    )
    return resp


def cached_get(
    url: str,
    source: str,
    key: str,
    ext: str = "html",
    refresh: bool = False,
    params: dict | None = None,
    timeout: float = 40.0,
) -> str:
    """GET `url`, caching the response text at {data_dir}/raw/{source}/{key}.{ext}.

    Returns the response text (from cache if present and refresh=False).
    """
    cache_dir = raw_dir() / source
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{key}.{ext}"

    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8", errors="replace")

    resp = fetch(url, params=params, timeout=timeout)
    resp.raise_for_status()
    text = resp.text
    cache_path.write_text(text, encoding="utf-8")
    return text
