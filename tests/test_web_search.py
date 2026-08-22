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
