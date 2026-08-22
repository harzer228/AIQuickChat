"""Local search engine: source cascade + snippet enrichment + cache.

The cascade tries free public sources in order until one returns results:

    1. DuckDuckGo HTML    (scraped, no key)
    2. DuckDuckGo Lite    (scraped, no key)
    3. Public SearXNG     (JSON API, no key)
    4. Wikipedia API      (official, no key)

Then the top pages are fetched and their text is appended to the snippets so
the chat model receives real page content, not just search summaries.
"""

import time

from local_websearch import backends
from local_websearch.backends import Result
from local_websearch.fetcher import fetch_pages

# In-memory cache: repeated queries within TTL don't hit the network.
CACHE_TTL = 600  # seconds
_cache = {}

ENRICH_TOP_N = 3          # how many found pages to download
CONTENT_LIMIT = 1200      # max chars per result content


def _backends():
    return (
        ("duckduckgo", backends.search_ddg_html),
        ("duckduckgo-lite", backends.search_ddg_lite),
        ("searxng", backends.search_searxng),
        ("wikipedia", backends.search_wikipedia),
    )


def _enrich(results, timeout: float):
    """Append readable page text to the top results' snippets."""
    top = [r for r in results[:ENRICH_TOP_N] if r.url]
    pages = fetch_pages([r.url for r in top], timeout=min(timeout, 8.0))
    for r in results:
        text = pages.get(r.url, "")
        if text:
            extra = text[:CONTENT_LIMIT]
            if extra not in r.snippet:
                r.snippet = (r.snippet + "\n" + extra).strip()[:CONTENT_LIMIT + 400]
    return results


def search(query: str, max_results: int = 5, timeout: float = 15.0,
           enrich: bool = True):
    """Search the web through the cascade. Returns [Result].

    Raises RuntimeError when every source failed (network down etc.) —
    the caller converts it to its own error type.
    """
    query = (query or "").strip()
    if not query:
        return []

    key = (query.lower(), max_results)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return list(hit[1])

    # Budget: at most half the timeout for the whole search cascade,
    # at least 4 seconds so slow sources still get a chance.
    budget = max(4.0, min(float(timeout), 15.0))
    per_source = min(6.0, budget / 2.0)

    errors = []
    results = []
    for name, fn in _backends():
        started = time.monotonic()
        try:
            results = fn(query, max_results=max_results, timeout=per_source)
        except Exception as e:  # noqa: BLE001 - fall through to next source
            errors.append(f"{name}: {e}")
        if results:
            results = [Result(title=r.title, url=r.url, snippet=r.snippet)
                       for r in results]
            if enrich:
                _enrich(results, timeout=budget)
            _cache[key] = (now, list(results))
            return results
        budget -= (time.monotonic() - started)
        if budget <= 1.0:
            break

    if errors:
        raise RuntimeError("; ".join(errors)[:300])
    return []
