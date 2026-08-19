"""Tests for ParallelWebSearcher and Fallback Mechanisms."""

import pytest
from tools.web_search import ParallelWebSearcher


def test_web_searcher_unconfigured():
    searcher = ParallelWebSearcher(api_key="")
    res = searcher.search(queries=["ArXiv Hegselmann-Krause"])
    assert res["status"] == "fallback_to_native"
    assert "PARALLEL_API_KEY not configured" in res["message"]
    assert res["queries"] == ["ArXiv Hegselmann-Krause"]


def test_web_extract_unconfigured():
    searcher = ParallelWebSearcher(api_key="")
    res = searcher.extract(urls=["https://arxiv.org/abs/2106.00000"])
    assert res["status"] == "fallback_to_native"
    assert "PARALLEL_API_KEY not configured" in res["message"]


@pytest.mark.asyncio
async def test_async_web_searcher_unconfigured():
    searcher = ParallelWebSearcher(api_key="")
    res = await searcher.asearch(queries=["ArXiv Avellaneda-Stoikov"])
    assert res["status"] == "fallback_to_native"
    assert "PARALLEL_API_KEY not configured" in res["message"]
