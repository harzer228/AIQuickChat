"""Page fetching and readable-text extraction.

Used to enrich search snippets with real page content: the top hits are
downloaded in parallel and reduced to plain text with a small HTMLParser
(no external dependency). Best-effort by design — a page that fails to load
simply keeps its snippet.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

import httpx

from local_websearch.backends import USER_AGENT

MAX_PAGE_BYTES = 1_500_000   # hard cap on downloaded HTML size
MAX_TEXT_CHARS = 1800        # per-page extracted text budget
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template",
              "nav", "header", "footer", "aside", "form", "iframe"}
_SKIP_ROLES = {"navigation", "banner", "footer", "contentinfo", "complementary"}
_TEXT_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "blockquote", "td"}


_AD_CLASS_RE = re.compile(
    r"(?:^|\s|_|-)(ad|ads|advert|banner|promo|sidebar|cookie|consent|modal)"
    r"(?:$|\s|_|-)", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    """Collect visible text from the main content of an HTML document."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self._skip_stack = []
        self._buf = []

    def _skip_start(self, tag, attrs) -> bool:
        a = attrs and dict(attrs) or {}
        if tag in _SKIP_TAGS or a.get("aria-hidden") == "true" or a.get("role") in _SKIP_ROLES:
            return True
        cls = a.get("class", "") or a.get("id", "") or ""
        return bool(_AD_CLASS_RE.search(f" {cls} "))

    def handle_starttag(self, tag, attrs):
        if self._skip_start(tag, attrs):
            self._skip_stack.append(tag)
            return
        if tag == "br":
            self._flush()

    def handle_endtag(self, tag):
        if self._skip_stack:
            # Close the skipped block only on its own end tag; stray inner
            # closers (e.g. an unclosed <span>) must not end the skip.
            if tag in self._skip_stack:
                while self._skip_stack and self._skip_stack.pop() != tag:
                    pass
            return
        if tag in _TEXT_TAGS or tag == "body":
            self._flush()

    def handle_data(self, data):
        if self._skip_stack or not data.strip():
            return
        self._buf.append(data)

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text:
            self.chunks.append(text)
        self._buf = []

    def text(self) -> str:
        self._flush()
        out = "\n".join(self.chunks)
        if len(out) > MAX_TEXT_CHARS:
            out = out[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
        return out


def extract_text(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html or "")
        extractor.close()
    except Exception:
        return ""
    return extractor.text()


def fetch_page(url: str, timeout: float = 6.0) -> str:
    """Download one page and return its readable text ("" on any failure)."""
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT,
                                   "Accept-Language": "ru,en;q=0.8"}) as resp:
            ctype = resp.headers.get("content-type", "")
            if resp.status_code != 200 or "html" not in ctype:
                return ""
            chunks = []
            received = 0
            for chunk in resp.iter_bytes(64_000):
                chunks.append(chunk)
                received += len(chunk)
                if received >= MAX_PAGE_BYTES:
                    break
            html = b"".join(chunks).decode("utf-8", errors="replace")
        return extract_text(html)
    except Exception:
        return ""


def fetch_pages(urls, timeout: float = 6.0, max_workers: int = 4) -> dict:
    """Fetch several pages in parallel: {url: readable_text}."""
    urls = list(dict.fromkeys(u for u in urls if u))[:6]
    if not urls:
        return {}
    out = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as pool:
        for url, text in zip(urls, pool.map(lambda u: fetch_page(u, timeout), urls)):
            if text:
                out[url] = text
    return out
