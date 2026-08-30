"""Polite, disk-cached HTTP GET. Used by every adapter and by recon.

Caches raw response bytes under {data_dir}/raw/{source}/{key}.{ext} so re-runs never
re-hit the target server. Rate-limits to one request at a time per host with a short
delay, and identifies itself with a real contact -- this tool points agents at servers
run by other people; it should never look anonymous.
"""
from __future__ import annotations

import os
import time

import httpx

from conference_connector.paths import raw_dir

_MIN_DELAY_S = 0.6
_last_request_time: dict[str, float] = {}


def user_agent() -> str:
    contact = os.environ.get("CONFERENCE_CONNECTOR_CONTACT")
    if not contact:
        raise RuntimeError(
            "Set CONFERENCE_CONNECTOR_CONTACT (e.g. an email address) before making network "
            "requests. conference_connector identifies itself honestly to every server it talks to."
        )
    return f"conference_connector/0.1 (conference research tool; contact: {contact})"


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
