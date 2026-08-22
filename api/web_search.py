"""Pluggable web search client.

The provider is isolated here so it can be swapped later without touching the
UI. Supported providers (real HTTP search services):

    - tavily  : POST https://api.tavily.com/search
                authentication via `Authorization: Bearer <key>` header
                (official current format — see docs.tavily.com). The legacy
                `api_key` body field is NOT used anymore.
    - searxng : GET  {api_url}/search     ?q=..&format=json   (no key required)
    - serper  : POST {api_url}            header X-API-KEY     (Google via Serper)
    - brave   : GET  {api_url}?q=..       header X-Subscription-Token

Results are cleaned (HTML stripped, truncated) and turned into structured
context for the chat model. No fake/invented results are ever returned.

NOTE on the official Tavily MCP server: it was evaluated for this project but
intentionally NOT integrated. Using it would require spawning an external MCP
server subprocess (Node `npx` or Python `uvx`), bridging an async MCP client
into the synchronous QThread worker, and adding the heavy `mcp`/`anyio`
dependency — all for a single authenticated HTTP POST. That is exactly the kind
of unreliable plumbing the task warned against. The fixed direct Tavily REST
integration is used instead.
"""

import json
import re
from dataclasses import dataclass, field

import httpx

from api.errors import APIError
from utils.i18n import t

PROVIDER_LABELS = {
    "tavily": "Tavily",
    "searxng": "SearXNG",
    "serper": "Serper (Google)",
    "brave": "Brave Search",
}

PROVIDER_URLS = {
    "tavily": "https://api.tavily.com/search",
    "searxng": "",
    "serper": "https://google.serper.dev/search",
    "brave": "https://api.search.brave.com/res/v1/web/search",
}

# Providers that require an API key.
KEY_REQUIRED = {"tavily", "serper", "brave"}

# Local no-API provider (local_websearch/ folder) — registered only when the
# module exists, so deleting the folder cleanly removes it from the UI.
try:
    import local_websearch as _local_websearch  # noqa: F401
    LOCAL_AVAILABLE = True
except Exception:
    _local_websearch = None
    LOCAL_AVAILABLE = False

if LOCAL_AVAILABLE:
    PROVIDER_LABELS["local"] = "Local (no API)"
    PROVIDER_URLS["local"] = ""

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Tavily-specific HTTP codes (per official docs).
_TAVILY_PLAN_LIMIT = 432   # key / plan usage limit exceeded
_TAVILY_PAYGO_LIMIT = 433  # pay-as-you-go limit exceeded


@dataclass
class SearchResult:
    """A single cleaned search result."""

    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0.0
    source: str = field(default="", repr=False)

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "score": self.score,
        }


def _provider_name(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, (provider or "").capitalize() or "Поисковый сервис")


def mask_key(api_key: str) -> str:
    """Mask a secret key for display, e.g. `tvly-****abcd`. Never leaks it fully."""
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    dash = key.find("-")
    prefix = key[:dash + 1] if 0 < dash < 8 else key[:4]
    return f"{prefix}****{key[-4:]}"


def _clean_text(text: str, limit: int = 600) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _valid_url(url: str) -> bool:
    url = (url or "").strip()
    return url.lower().startswith(("http://", "https://"))


def _error_detail(body: str) -> str:
    """Pull the human-readable reason out of an error JSON body if possible.

    Tavily returns `{"detail": {"error": "..."}}`; other providers use
    `{"error": ...}` or `{"message": ...}`.
    """
    body = (body or "").strip()
    if not body:
        return ""
    try:
        data = json.loads(body)
    except Exception:
        return body[:300]
    if not isinstance(data, dict):
        return body[:300]
    detail = data.get("detail")
    if isinstance(detail, dict):
        err = detail.get("error") or detail.get("message")
        return str(err)[:300] if err else str(detail)[:300]
    if isinstance(detail, str):
        return detail[:300]
    err = data.get("error")
    if isinstance(err, str):
        return err[:300]
    message = data.get("message")
    if isinstance(message, str):
        return message[:300]
    return body[:300]


def _code_for_status(status: int) -> str:
    if status == 400:
        return "bad_request"
    if status == 401:
        return "auth"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limit"
    if status == _TAVILY_PLAN_LIMIT:
        return "plan_limit"
    if status == _TAVILY_PAYGO_LIMIT:
        return "paygo_limit"
    if 400 <= status < 500:
        return "client_error"
    return "server"


def _http_error_message(status: int, reason: str, masked_key: str, provider: str) -> str:
    name = _provider_name(provider)
    if status == 400:
        head = f"{name}: {t('search.http_400')}"
    elif status == 401:
        head = f"{name}: {t('search.http_401')}"
    elif status == 403:
        head = f"{name}: {t('search.http_403')}"
    elif status == 404:
        head = f"{name}: {t('search.http_404')}"
    elif status == 429:
        head = f"{name}: {t('search.http_429')}"
    elif status == _TAVILY_PLAN_LIMIT:
        head = f"{name}: {t('search.http_432')}"
    elif status == _TAVILY_PAYGO_LIMIT:
        head = f"{name}: {t('search.http_433')}"
    elif 400 <= status < 500:
        head = f"{name}: {t('search.http_client', status=status)}"
    else:
        head = f"{name}: {t('search.http_server', status=status)}"

    lines = [head]
    if masked_key:
        lines.append(t("search.api_key_label", masked=masked_key))
    if reason:
        lines.append(t("search.reason_label", reason=reason))
    return "\n".join(lines)


def _check_response(resp: "httpx.Response", provider: str, api_key: str) -> dict:
    """Validate the response, raise a diagnostic APIError, or return JSON."""
    if resp.status_code == 200:
        try:
            return resp.json()
        except ValueError:
            raise APIError(
                f"{_provider_name(provider)}: {t('search.json')}",
                code="json", detail=(resp.text or "")[:600])
    raise APIError(
        _http_error_message(resp.status_code, _error_detail(resp.text),
                            mask_key(api_key), provider),
        code=_code_for_status(resp.status_code),
        detail=(resp.text or "")[:600])


def _extract(data: dict, items_key: str, title_key: str, url_key: str,
             content_key: str, max_results: int, source: str = "",
             score_key: str = "score") -> list[SearchResult]:
    items = data or {}
    for key in items_key.split("."):
        items = items.get(key, {}) if isinstance(items, dict) else {}
    if not isinstance(items, list):
        return []
    results = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get(url_key) or "").strip()
        if not _valid_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        score = 0.0
        try:
            score = float(item.get(score_key) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        results.append(SearchResult(
            title=_clean_text(str(item.get(title_key) or ""), 300),
            url=url,
            content=_clean_text(str(item.get(content_key) or ""), 600),
            score=score,
            source=source,
        ))
        if len(results) >= max_results:
            break
    return results


# -- provider handlers ------------------------------------------------------

def _search_tavily(client: "WebSearchClient", query: str, timeout: float) -> list[SearchResult]:
    # Current official Tavily API: Bearer token header, api_key NOT in the body.
    url = client.api_url if client.api_url.endswith("/search") else f"{client.api_url}/search"
    resp = httpx.post(
        url,
        json={
            "query": query,
            "search_depth": "basic",
            "max_results": client.max_results,
        },
        headers={
            "Authorization": f"Bearer {client.api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout)
    return _extract(_check_response(resp, client.provider, client.api_key),
                    "results", "title", "url", "content",
                    client.max_results, source=client.provider)


def _search_searxng(client: "WebSearchClient", query: str, timeout: float) -> list[SearchResult]:
    base = client.api_url
    url = base if base.endswith("/search") else f"{base}/search"
    resp = httpx.get(
        url,
        params={"q": query, "format": "json"},
        timeout=timeout)
    return _extract(_check_response(resp, client.provider, client.api_key),
                    "results", "title", "url", "content",
                    client.max_results, source=client.provider)


def _search_serper(client: "WebSearchClient", query: str, timeout: float) -> list[SearchResult]:
    resp = httpx.post(
        client.api_url,
        json={"q": query, "num": client.max_results},
        headers={
            "X-API-KEY": client.api_key,
            "Content-Type": "application/json",
        },
        timeout=timeout)
    return _extract(_check_response(resp, client.provider, client.api_key),
                    "organic", "title", "link", "snippet",
                    client.max_results, source=client.provider)


def _search_brave(client: "WebSearchClient", query: str, timeout: float) -> list[SearchResult]:
    resp = httpx.get(
        client.api_url,
        params={"q": query, "count": client.max_results},
        headers={"X-Subscription-Token": client.api_key},
        timeout=timeout)
    return _extract(_check_response(resp, client.provider, client.api_key),
                    "web.results", "title", "url", "description",
                    client.max_results, source=client.provider)


def _search_local(client: "WebSearchClient", query: str, timeout: float) -> list[SearchResult]:
    """Keyless local search via the removable local_websearch module."""
    try:
        from local_websearch import search as local_search
    except Exception:
        raise APIError(t("search.local_missing"), code="config")
    try:
        raw = local_search(query, max_results=client.max_results,
                           timeout=timeout or client.timeout)
    except RuntimeError as e:
        raise APIError(t("search.local_failed", error=str(e)),
                       code="network", detail=str(e))
    return [SearchResult(title=r.title, url=r.url, content=r.snippet,
                         score=0.5, source="local") for r in raw]


_HANDLERS = {
    "tavily": _search_tavily,
    "searxng": _search_searxng,
    "serper": _search_serper,
    "brave": _search_brave,
}
if LOCAL_AVAILABLE:
    _HANDLERS["local"] = _search_local


class WebSearchClient:
    """Search the web through a configurable HTTP search provider."""

    def __init__(self, provider: str = "tavily", api_url: str = "",
                 api_key: str = "", max_results: int = 5, timeout: float = 15.0):
        self.provider = (provider or "tavily").strip().lower()
        self.api_url = (api_url or "").strip().rstrip("/")
        self.api_key = (api_key or "").strip()
        try:
            self.max_results = max(1, min(20, int(max_results)))
        except (TypeError, ValueError):
            self.max_results = 5
        try:
            self.timeout = max(1.0, float(timeout))
        except (TypeError, ValueError):
            self.timeout = 15.0

    def _require_config(self):
        if self.provider not in _HANDLERS:
            raise APIError(t("search.unknown_provider", provider=self.provider),
                           code="config")
        if self.provider in KEY_REQUIRED and not self.api_key:
            raise APIError(t("search.no_key"), code="no_api_key")
        if not self.api_url and self.provider != "local":
            raise APIError(t("search.no_url"), code="no_url")

    def search(self, query: str, timeout: float | None = None) -> list[SearchResult]:
        """Run a real search and return cleaned results (never invented)."""
        self._require_config()
        query = (query or "").strip()
        if not query:
            raise APIError(t("search.empty_query"), code="empty")
        handler = _HANDLERS[self.provider]
        try:
            results = handler(self, query, timeout or self.timeout)
        except httpx.TimeoutException:
            raise APIError(
                t("search.timeout", sec=int(timeout or self.timeout)),
                code="timeout")
        except httpx.ConnectError:
            raise APIError(t("search.network"), code="network")
        except httpx.HTTPError as e:
            raise APIError(t("search.network_err", e=e), code="network", detail=str(e))
        return results or []

    def test(self, timeout: float | None = None) -> str:
        """Real minimal request against the provider (never a fake check)."""
        self._require_config()
        results = self.search("latest artificial intelligence news", timeout=timeout)
        if not results:
            raise APIError(t("search.empty_results"), code="empty")
        return t("search.connected")


def build_search_context(query: str, results: list[SearchResult]) -> str:
    """Build the structured context block passed to DeepSeek."""
    lines = ["WEB SEARCH RESULTS", "", "Query:", (query or "").strip(), ""]
    if not results:
        lines.append("No sources found.")
    else:
        for i, result in enumerate(results, 1):
            lines.append(f"Source {i}:")
            lines.append(f"Title: {result.title or '(no title)'}")
            lines.append(f"URL: {result.url}")
            if result.score:
                lines.append(f"Score: {result.score:.4f}")
            if result.source:
                lines.append(f"Source: {result.source}")
            lines.append(f"Content: {result.content}")
            lines.append("")
    lines += [
        "Use these sources to answer the user's question.",
        "Prefer information from reliable and relevant sources.",
        "If sources disagree, mention the disagreement.",
        "Do not invent information that is not supported by the sources.",
    ]
    return "\n".join(lines)
