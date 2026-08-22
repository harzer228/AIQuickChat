"""Search backends — free public sources, no API keys.

Each backend is a callable ``search(query, max_results, timeout) -> [Result]``
that never raises on "no results / blocked": it returns an empty list instead,
so the engine cascade in ``engine.py`` can fall through to the next source.
Hard configuration errors should not happen here — everything is best-effort.
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "ru,en;q=0.8",
}

# Skip obviously non-page links that search engines inject into results.
_BAD_URL_PARTS = ("duckduckgo.com", "google.com/search", "yandex.ru/search",
                  "bing.com/search", "javascript:", "mailto:")


@dataclass
class Result:
    """Raw search hit (title + url + short snippet)."""
    title: str = ""
    url: str = ""
    snippet: str = ""


def _clean(text: str, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _ok_url(url: str) -> bool:
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return False
    return not any(part in url for part in _BAD_URL_PARTS)


def _dedupe(results: list, max_results: int) -> list:
    seen = set()
    out = []
    for r in results:
        if not _ok_url(r.url) or r.url in seen:
            continue
        seen.add(r.url)
        out.append(Result(title=_clean(r.title, 220), url=r.url,
                          snippet=_clean(r.snippet)))
        if len(out) >= max_results:
            break
    return out


def _get(url: str, timeout: float, **kwargs) -> httpx.Response:
    return httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers=_HEADERS, **kwargs)


# ---------------------------------------------------------------------------
# DuckDuckGo HTML endpoint
# ---------------------------------------------------------------------------

class _DDGHtmlParser(HTMLParser):
    """Collect result links/snippets from html.duckduckgo.com/html."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._cur = None
        self._capture = None      # 'link' | 'snippet'
        self._buf = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag == "a":
            href = dict(attrs).get("href", "") or ""
            uddg = self._uddg(href)
            if uddg and "result__a" in cls:
                self._flush()
                self._cur = Result(url=uddg)
                self._capture = "link"
                self._buf = []
            elif "result__snippet" in cls and self._cur is not None:
                self._capture = "snippet"
                self._buf = []
        elif tag == "div" and "result__body" in cls and self._cur is not None:
            pass  # snippet may follow the link inside the same result body

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "a" and self._capture == "link":
            if self._cur is not None:
                self._cur.title = "".join(self._buf).strip()
            self._capture = None
        elif self._capture == "snippet" and tag == "a":
            if self._cur is not None:
                self._cur.snippet = "".join(self._buf).strip()
            self._capture = None

    def handle_data(self, data):
        if self._capture:
            self._buf.append(data)

    def _flush(self):
        if self._cur is not None and self._cur.title:
            self.results.append(self._cur)
        self._cur = None
        self._capture = None

    def close(self):
        super().close()
        self._flush()

    @staticmethod
    def _uddg(href: str):
        """DDG wraps external links as /l/?uddg=<urlencoded>."""
        if href.startswith("//"):
            href = "https:" + href
        parsed = urlparse(href)
        if parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return unquote(target) if target else None
        if parsed.netloc and "duckduckgo.com" not in parsed.netloc:
            return href
        return None


def search_ddg_html(query: str, max_results: int = 5, timeout: float = 8.0) -> list:
    """DuckDuckGo HTML version — no JS, parseable result list."""
    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
    resp = _get(url, timeout)
    if resp.status_code != 200 or not resp.text.strip().startswith("<"):
        return []
    parser = _DDGHtmlParser()
    try:
        parser.feed(resp.text)
        parser.close()
    except Exception:
        pass
    return _dedupe(parser.results, max_results)


# ---------------------------------------------------------------------------
# DuckDuckGo Lite
# ---------------------------------------------------------------------------

class _DDGLiteParser(HTMLParser):
    """lite.duckduckgo.com — one <a class='result-link'> per result,
    the snippet is the <td class='result-snippet'> right after the link row."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._in_link = False
        self._in_snippet = False
        self._title = ""
        self._cur_url = ""
        self._buf = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag == "a" and "result-link" in cls:
            self._in_link = True
            self._buf = []
            href = a.get("href", "") or ""
            if href.startswith("//"):
                href = "https:" + href
            parsed = urlparse(href)
            if parsed.path.startswith("/l/"):
                href = unquote(parse_qs(parsed.query).get("uddg", [href])[0])
            self._cur_url = href
        elif tag == "td" and "result-snippet" in cls:
            self._in_snippet = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "a" and self._in_link:
            self._in_link = False
            self._title = "".join(self._buf).strip()
        elif tag == "td" and self._in_snippet:
            self._in_snippet = False
            snippet = "".join(self._buf).strip()
            if self._title and self._cur_url:
                self.results.append(Result(title=self._title, url=self._cur_url,
                                           snippet=snippet))

    def handle_data(self, data):
        if self._in_link or self._in_snippet:
            self._buf.append(data)


def search_ddg_lite(query: str, max_results: int = 5, timeout: float = 8.0) -> list:
    """DuckDuckGo Lite — table-based, even simpler markup."""
    url = "https://lite.duckduckgo.com/lite/?q=" + quote_plus(query)
    resp = _get(url, timeout)
    if resp.status_code != 200:
        return []
    parser = _DDGLiteParser()
    try:
        parser.feed(resp.text)
        parser.close()
    except Exception:
        pass
    return _dedupe(parser.results, max_results)


# ---------------------------------------------------------------------------
# SearXNG public instances (JSON, no key)
# ---------------------------------------------------------------------------

SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://searx.tiekoetter.com",
    "https://priv.au",
    "https://searx.work",
]


def search_searxng(query: str, max_results: int = 5, timeout: float = 8.0) -> list:
    """Public SearXNG instances that expose ?format=json without a key."""
    per_instance = min(timeout, 6.0)
    results = []
    for base in SEARXNG_INSTANCES:
        if not base.startswith("http"):
            continue
        url = base.rstrip("/") + "/search"
        try:
            resp = _get(url, per_instance,
                        params={"q": query, "format": "json", "safesearch": "0"})
            if resp.status_code != 200:
                continue
            data = resp.json()
            for item in (data.get("results") or [])[: max_results * 2]:
                results.append(Result(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or "")))
            if results:
                break
        except Exception:
            continue
    return _dedupe(results, max_results)


# ---------------------------------------------------------------------------
# Wikipedia search API (official, keyless)
# ---------------------------------------------------------------------------

def _wiki_langs(query: str):
    has_cyrillic = any("\u0400" <= ch <= "\u04FF" for ch in query)
    return ("ru", "en") if has_cyrillic else ("en", "ru")


def search_wikipedia(query: str, max_results: int = 5, timeout: float = 8.0) -> list:
    """MediaWiki search API — reliable last resort for encyclopedic queries."""
    results = []
    for lang in _wiki_langs(query):
        api = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query", "list": "search", "format": "json",
            "srsearch": query, "srlimit": str(max_results), "utf8": "1",
        }
        try:
            resp = _get(api, min(timeout, 6.0), params=params)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for item in (data.get("query", {}).get("search") or []):
                title = str(item.get("title") or "")
                if not title:
                    continue
                snippet = _clean(re.sub(r"<[^>]+>", " ",
                                        str(item.get("snippet") or "")))
                results.append(Result(
                    title=title,
                    url=f"https://{lang}.wikipedia.org/wiki/"
                        + quote_plus(title.replace(" ", "_")),
                    snippet=snippet))
        except Exception:
            continue
        if len(results) >= max_results:
            break
    return _dedupe(results, max_results)
