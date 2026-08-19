"""Tests for ParallelWebSearcher."""

import pytest
from tools.web_search import ParallelWebSearcher


def test_web_searcher_unconfigured():
    searcher = ParallelWebSearcher(api_key=None)
    searcher.api_key = ""  # override any ambient env key
    res = searcher.search(queries=["ArXiv Hegselmann-Krause"])
    assert "error" in res
    assert "PARALLEL_API_KEY not configured" in res["error"]
    assert res["queries"] == ["ArXiv Hegselmann-Krause"]


@pytest.mark.asyncio
async def test_async_web_searcher_unconfigured():
    searcher = ParallelWebSearcher(api_key=None)
    searcher.api_key = ""
    res = await searcher.asearch(queries=["ArXiv Avellaneda-Stoikov"])
    assert "error" in res
    assert "PARALLEL_API_KEY not configured" in res["error"]
