"""Local web search without third-party paid APIs.

Self-contained module (only httpx, which the app already depends on).
Delete this folder to remove the feature — the app detects the module's
absence and hides the "local" search provider from the settings.

Usage:
    from local_websearch import search
    results = search("python asyncio tutorial", max_results=5, timeout=15.0)
    # -> [Result(title=..., url=..., snippet=...)]
"""

from local_websearch.backends import Result
from local_websearch.engine import search

__all__ = ["search", "Result"]
