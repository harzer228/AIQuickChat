"""Offline tests for the local (keyless) web search module.

All parsing is exercised against inline HTML/JSON fixtures — no network.
"""

from local_websearch.backends import (
    _DDGHtmlParser,
    _DDGLiteParser,
    _dedupe,
    _ok_url,
)
from local_websearch.engine import _backends
from local_websearch.fetcher import extract_text

DDG_HTML = """
<div class="result results_links">
  <h2 class="result__title"><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2Flibrary%2Fasyncio.html&amp;rut=abc">Asyncio docs</a></h2>
  <a class="result__snippet" href="...">Coroutine framework for <b>concurrent</b> code</a>
</div>
<div class="result results_links">
  <h2 class="result__title"><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Frealpython.com%2Fasyncio-python%2F&rut=def">Real Python walkthrough</a></h2>
  <a class="result__snippet">Tutorial about async/await</a>
</div>
<script>var junk = 1;</script>
"""

DDG_LITE = """
<table>
<tr><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fos" class="result-link">os module</a></td></tr>
<tr><td class="result-snippet">Functions for <b>interacting</b> with the OS</td></tr>
<tr><td><a rel="nofollow" href="https://example.org/zip" class="result-link">zip() Function</a></td></tr>
<tr><td class="result-snippet">Joins tuples pairwise</td></tr>
</table>
"""

TEXT_PAGE = """<html><body><nav>menu</nav>
<h1>Big Title</h1><script>bad()</script>
<p>First paragraph.</p>
<div role="navigation">skip me</div>
<div class="ads"><span>AD</span><p>buy now</p></div>
<div class="gradient happy">keep gradients</div>
<ul><li>Item one</li></ul>
<footer>(c) footer</footer>
</body></html>"""


def test_ddg_html_parser():
    parser = _DDGHtmlParser()
    parser.feed(DDG_HTML)
    parser.close()
    results = _dedupe(parser.results, 5)
    assert len(results) == 2
    assert results[0].url == "https://docs.python.org/3/library/asyncio.html"
    assert results[0].title == "Asyncio docs"
    assert "concurrent" in results[0].snippet
    assert results[1].url == "https://realpython.com/asyncio-python/"


def test_ddg_lite_parser():
    parser = _DDGLiteParser()
    parser.feed(DDG_LITE)
    parser.close()
    results = _dedupe(parser.results, 5)
    assert len(results) == 2
    assert results[0].url == "https://example.com/os"
    assert results[0].title == "os module"
    assert "interacting" in results[0].snippet
    assert results[1].url == "https://example.org/zip"


def test_extract_text_drops_noise_keeps_content():
    text = extract_text(TEXT_PAGE)
    for needed in ("Big Title", "First paragraph.", "Item one", "keep gradients"):
        assert needed in text
    for banned in ("bad()", "menu", "skip me", "buy now", "AD", "(c)"):
        assert banned not in text


def test_extract_text_empty_and_broken():
    assert extract_text("") == ""
    assert extract_text("<p>unclosed <b>bold") != ""


def test_dedupe_drops_search_engine_links_and_duplicates():
    raw = []
    for url in ("https://a.com/1", "https://a.com/1",
                "https://duckduckgo.com/x", "not-a-url", "https://b.com/2"):
        raw.append(type("R", (), {"title": "t", "url": url, "snippet": "s"})())
    out = _dedupe(raw, 5)
    assert [r.url for r in out] == ["https://a.com/1", "https://b.com/2"]


def test_ok_url_filter():
    assert _ok_url("https://example.com/page")
    assert not _ok_url("https://duckduckgo.com/x")
    assert not _ok_url("ftp://example.com")
    assert not _ok_url("")


def test_engine_cascade_order():
    names = [name for name, _fn in _backends()]
    assert names == ["duckduckgo", "duckduckgo-lite", "searxng", "wikipedia"]
