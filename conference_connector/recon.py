"""Recon: look at a conference site before deciding how to scrape it.

This is a deliberately separate, explicit command -- `conference_connector recon <url>` -- run
once per candidate site and read by a person (or an agent, with the person watching)
before any adapter gets written or any bulk ingest happens. Nothing in this module
loops over a site or follows links beyond the one page given plus a small, fixed set
of well-known-path probes. If more pages need checking, run recon again on each one by
hand. That's the checkpoint: scraping starts only after someone has looked at what
this prints and decided how to proceed.

What it looks for, and why:

- **Platform fingerprints** (generator meta tags, known JS bundles, cookie names) --
  if this site runs on a platform conference_connector already has an adapter pattern for
  (Indico, Sched, a stock WordPress REST API, ...), there may be no new parsing code
  to write at all.
- **Embedded data blobs** (__NEXT_DATA__, __NUXT__, application/json scripts) -- many
  "JS-rendered" sites ship the full dataset as JSON in the initial HTML; if so, no
  headless browser is needed, just a different parse target.
- **Iframes to other hosts** -- the single most useful ECCB-2026 finding: the
  conference's own site was a shell around a different platform's pages. Always
  check where the content actually lives before concluding a page is unscrapable.
- **Well-known paths** (robots.txt, sitemap.xml, /wp-json/wp/v2/, .ics feeds) -- cheap
  to check, sometimes hands you a full data feed with no HTML parsing at all.
- **Static-vs-hydrated heuristic** -- a large page with little text and few repeated
  structural blocks is probably rendered client-side after load; the real content is
  likely fetched from an API worth finding, not scraped from this HTML.
- **Link classification** -- same-page links whose text/URL match programme-ish
  keywords (schedule, posters, abstracts, keynote, tutorial, workshop), surfaced as
  candidates for the next recon call.

robots.txt is fetched and its rules for conference_connector's user-agent (or `*`) are reported,
but NOT enforced by mechanically blocking requests here -- the report gives you (or the
agent) the information to make that call explicitly before ingest.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from conference_connector import http_client

_WELL_KNOWN_PATHS = [
    "/robots.txt",
    "/sitemap.xml",
    "/wp-json/wp/v2/",
    "/wp-json/",
    "/api/",
    "/feed/",
]

_PLATFORM_SIGNATURES: dict[str, list[str]] = {
    "wordpress": ["wp-content/", "wp-json", 'name="generator" content="WordPress'],
    "indico": ["indico", "Indico"],
    "sched": ["sched.com", "schedjs"],
    "confex": ["confex.com"],
    "drupal": ["Drupal.settings", 'name="generator" content="Drupal'],
    "nextjs": ["__NEXT_DATA__", "_next/static"],
    "nuxt": ["__NUXT__", "_nuxt/"],
    "react": ["react-dom", "id=\"root\""],
}

_EMBEDDED_DATA_MARKERS = [
    "__NEXT_DATA__",
    "__NUXT__",
    "window.__INITIAL_STATE__",
    'type="application/json"',
]

_PROGRAMME_KEYWORDS = [
    "programme", "program", "schedule", "agenda", "poster", "abstract",
    "session", "keynote", "tutorial", "workshop", "speaker", "talk",
]

_LINK_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)
_IFRAME_RE = re.compile(r'<iframe\b[^>]*src=["\']([^"\']+)["\']', re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


def _strip_tags(s: str) -> str:
    return _TAG_RE.sub(" ", s).strip()


def _detect_platform(html: str) -> list[str]:
    hits = []
    for name, sigs in _PLATFORM_SIGNATURES.items():
        if any(sig in html for sig in sigs):
            hits.append(name)
    return hits


def _detect_embedded_data(html: str) -> list[str]:
    return [m for m in _EMBEDDED_DATA_MARKERS if m in html]


def _extract_iframes(html: str, base_url: str) -> list[str]:
    base_host = urlparse(base_url).netloc
    out = []
    for src in _IFRAME_RE.findall(html):
        full = urljoin(base_url, src)
        flag = " <-- DIFFERENT HOST" if urlparse(full).netloc != base_host else ""
        out.append(f"{full}{flag}")
    return out


def _classify_links(html: str, base_url: str, max_links: int) -> list[dict]:
    out = []
    seen = set()
    for href, text in _LINK_RE.findall(html):
        full = urljoin(base_url, href)
        if full in seen:
            continue
        label = _strip_tags(text).lower()
        haystack = f"{label} {full.lower()}"
        matched = [kw for kw in _PROGRAMME_KEYWORDS if kw in haystack]
        if matched:
            seen.add(full)
            out.append({"url": full, "text": _strip_tags(text)[:80], "matched_keywords": matched})
            if len(out) >= max_links:
                break
    return out


def _hydration_heuristic(html: str) -> dict:
    visible_text = _strip_tags(html)
    size = len(html)
    text_len = len(visible_text)
    time_hits = len(_TIME_RE.findall(html))
    ratio = text_len / size if size else 0
    likely_hydrated = size > 50_000 and ratio < 0.05
    return {
        "html_bytes": size,
        "visible_text_chars": text_len,
        "text_to_html_ratio": round(ratio, 4),
        "time_pattern_hits": time_hits,
        "likely_client_rendered": likely_hydrated,
        "note": (
            "Large page, little visible text -- content is probably fetched by JS after "
            "load. Look for an API call in embedded_data or well_known_probes rather "
            "than trying to parse this HTML directly."
            if likely_hydrated
            else "Text-to-HTML ratio looks normal for a server-rendered page."
        ),
    }


def _probe_well_known(base_url: str) -> list[dict]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    results = []
    for path in _WELL_KNOWN_PATHS:
        url = origin + path
        try:
            resp = http_client.fetch(url, timeout=15.0)
            results.append({
                "url": url,
                "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "bytes": len(resp.content),
            })
        except Exception as e:  # noqa: BLE001 -- recon should never crash on a dead probe
            results.append({"url": url, "status": None, "error": str(e)})
    return results


def recon(url: str, max_links: int = 30, probe: bool = True) -> dict:
    """Fetch one page and report what it looks like. Makes 1 + (up to 6, if probe=True)
    requests total -- nothing recursive, nothing beyond this."""
    resp = http_client.fetch(url)
    html = resp.text

    report = {
        "url": url,
        "final_url": str(resp.url),
        "status": resp.status_code,
        "platform_fingerprints": _detect_platform(html),
        "embedded_data_markers": _detect_embedded_data(html),
        "iframes": _extract_iframes(html, str(resp.url)),
        "hydration": _hydration_heuristic(html),
        "programme_links": _classify_links(html, str(resp.url), max_links),
    }
    if probe:
        report["well_known_probes"] = _probe_well_known(str(resp.url))
    return report


def format_report(report: dict) -> str:
    lines = [f"recon: {report['url']}"]
    if report["final_url"] != report["url"]:
        lines.append(f"  redirected to: {report['final_url']}")
    lines.append(f"  status: {report['status']}")

    lines.append("")
    lines.append("platform fingerprints: " + (", ".join(report["platform_fingerprints"]) or "none detected"))
    lines.append("embedded data markers: " + (", ".join(report["embedded_data_markers"]) or "none detected"))

    lines.append("")
    if report["iframes"]:
        lines.append(f"iframes ({len(report['iframes'])}):")
        for src in report["iframes"]:
            lines.append(f"  - {src}")
    else:
        lines.append("iframes: none")

    lines.append("")
    h = report["hydration"]
    lines.append(
        f"hydration check: {h['html_bytes']} bytes html, {h['visible_text_chars']} chars "
        f"visible text (ratio {h['text_to_html_ratio']}), {h['time_pattern_hits']} time-pattern hits"
    )
    lines.append(f"  -> {h['note']}")

    if "well_known_probes" in report:
        lines.append("")
        lines.append("well-known path probes:")
        for p in report["well_known_probes"]:
            status = p.get("status")
            if status and status < 400:
                lines.append(f"  [{status}] {p['url']}  ({p.get('content_type', '')}, {p.get('bytes', 0)}B)")
            else:
                lines.append(f"  [{status or 'ERR'}] {p['url']}")

    lines.append("")
    if report["programme_links"]:
        lines.append(f"programme-looking links ({len(report['programme_links'])}, run recon on the promising ones):")
        for link in report["programme_links"]:
            lines.append(f"  - {link['text'] or '(no text)'} -- {link['url']}  [{', '.join(link['matched_keywords'])}]")
    else:
        lines.append("programme-looking links: none found on this page")

    return "\n".join(lines)


def main(url: str) -> None:
    report = recon(url)
    print(format_report(report))
