"""Web search client wiring (offline: provider registry, config validation)."""

import pytest

from api.errors import APIError
from api.web_search import (
    _HANDLERS,
    PROVIDER_LABELS,
    WebSearchClient,
    mask_key,
)


def test_local_provider_registered():
    assert "local" in PROVIDER_LABELS
    assert "local" in _HANDLERS


def test_mask_key():
    assert mask_key("tvly-abcdef123456") == "tvly-****3456"
    assert mask_key("short") == "*****"
    assert mask_key("") == ""
    assert "abcdef123456" not in mask_key("tvly-abcdef123456")


def test_client_clamps_values():
    client = WebSearchClient(max_results=999, timeout=-5)
    assert client.max_results == 20
    assert client.timeout == 1.0  # negative clamps to the 1s minimum


def test_local_needs_no_url_or_key():
    client = WebSearchClient(provider="local")
    client._require_config()  # must not raise


def test_tavily_requires_key():
    client = WebSearchClient(provider="tavily", api_url="https://x/y")
    with pytest.raises(APIError) as err:
        client._require_config()
    assert err.value.code == "no_api_key"


def test_unknown_provider_rejected():
    client = WebSearchClient(provider="does-not-exist")
    with pytest.raises(APIError):
        client._require_config()


def test_empty_query_rejected():
    client = WebSearchClient(provider="local")
    with pytest.raises(APIError):
        client.search("   ")


# ----------------------------------------------------------- multi-search

from api.web_search import SearchResult, build_search_context  # noqa: E402
from ui.chat_window import (  # noqa: E402
    _dedupe_queries,
    _parse_search_decision,
    _search_decision_system,
)


def test_parse_search_decision_multi_query():
    needs, queries = _parse_search_decision(
        '{"needs_search": true, "queries": ["price of X", "reviews of Y"]}')
    assert needs is True
    assert queries == ["price of X", "reviews of Y"]


def test_parse_search_decision_legacy_single_query():
    needs, queries = _parse_search_decision(
        '{"needs_search": true, "query": "single query"}')
    assert needs is True
    assert queries == ["single query"]


def test_parse_search_decision_no_search():
    needs, queries = _parse_search_decision(
        '{"needs_search": false, "queries": []}')
    assert needs is False
    assert queries == []


def test_parse_search_decision_garbage_defaults_to_search():
    needs, queries = _parse_search_decision("not json at all")
    assert needs is True
    assert queries == []


def test_dedupe_queries_keeps_order_and_caps_limit():
    queries = ["A", "a", "B", "C", "D"]
    assert _dedupe_queries(queries, 3) == ["A", "B", "C"]


def test_search_decision_prompt_bakes_in_budget():
    prompt = _search_decision_system(5)
    assert "at most 5 queries" in prompt
    # The JSON examples inside must stay intact.
    assert '"needs_search": true/false' in prompt


def test_build_search_context_accepts_query_list():
    results = [SearchResult(title="T", url="https://x", content="C")]
    context = build_search_context(["q1", "q2"], results)
    assert "Queries:" in context
    assert "1. q1" in context
    assert "2. q2" in context
    assert "URL: https://x" in context


def test_build_search_context_single_query_unchanged():
    context = build_search_context("only q", [])
    assert "Query:" in context
    assert "only q" in context


def test_multi_search_settings_roundtrip(chat_window, monkeypatch):
    """The multi-search toggle and query budget survive save + reload."""
    import ui.settings_window as sw
    monkeypatch.setattr(sw, "set_start_with_windows", lambda enabled: None)

    win = sw.SettingsWindow(chat_window.config)
    win.load_from_config()
    win.ws_multi_check.setChecked(True)
    win.ws_max_queries.setValue(5)
    win._save()

    reloaded = sw.SettingsWindow(chat_window.config)
    reloaded.load_from_config()
    assert reloaded.ws_multi_check.isChecked()
    assert reloaded.ws_max_queries.value() == 5

    # Disabling multi-search keeps the budget but the flow uses one query.
    reloaded.ws_multi_check.setChecked(False)
    reloaded._save()
    assert chat_window.config.get("web_search", "multi_search") is False
    assert chat_window.config.get("web_search", "max_queries") == 5
