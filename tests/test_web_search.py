"""Tests for ParallelWebSearcher."""

import pytest
from tools.web_search import ParallelWebSearcher


def test_web_searcher_unconfigured():
    searcher = ParallelWebSearcher(api_key=None)
    res = searcher.search(queries=["ArXiv Hegselmann-Krause"])
    assert "error" in res
    assert res["error"] == "PARALLEL_API_KEY not configured"
    assert res["queries"] == ["ArXiv Hegselmann-Krause"]


@pytest.mark.asyncio
async def test_async_web_searcher_unconfigured():
    searcher = ParallelWebSearcher(api_key=None)
    res = await searcher.asearch(queries=["ArXiv Avellaneda-Stoikov"])
    assert "error" in res
    assert res["error"] == "PARALLEL_API_KEY not configured"
