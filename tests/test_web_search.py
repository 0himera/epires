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


from unittest.mock import AsyncMock, MagicMock


class MockSDKResponse:
    def __init__(self, results):
        self.results = results
        self.data = None


def test_web_searcher_mocked_success():
    searcher = ParallelWebSearcher(api_key="test-api-key")
    mock_client = MagicMock()
    mock_response = MockSDKResponse(
        [
            {
                "title": "Hegselmann-Krause Dynamics",
                "url": "https://arxiv.org/abs/2106.00001",
                "snippet": "Consensus model",
            }
        ]
    )
    mock_client.search.return_value = mock_response
    searcher._client = mock_client

    res = searcher.search(queries=["ArXiv Hegselmann-Krause"], mode="deep")
    assert res["status"] == "success"
    assert res["mode"] == "deep"
    assert res["queries"] == ["ArXiv Hegselmann-Krause"]
    assert len(res["data"]) == 1
    assert res["data"][0]["title"] == "Hegselmann-Krause Dynamics"


def test_web_extract_mocked_success():
    searcher = ParallelWebSearcher(api_key="test-api-key")
    mock_client = MagicMock()
    mock_response = MockSDKResponse(
        [{"url": "https://arxiv.org/abs/2106.00001", "content": "# Hegselmann-Krause\nExtracted content"}]
    )
    mock_client.extract.return_value = mock_response
    searcher._client = mock_client

    res = searcher.extract(urls=["https://arxiv.org/abs/2106.00001"])
    assert res["status"] == "success"
    assert res["urls"] == ["https://arxiv.org/abs/2106.00001"]
    assert len(res["data"]) == 1
    assert "Extracted content" in res["data"][0]["content"]


@pytest.mark.asyncio
async def test_async_web_searcher_mocked_success():
    searcher = ParallelWebSearcher(api_key="test-api-key")
    mock_async_client = MagicMock()
    mock_response = MockSDKResponse([{"title": "Async Paper", "url": "https://arxiv.org/abs/2106.00002"}])
    mock_async_client.search = AsyncMock(return_value=mock_response)
    searcher._async_client = mock_async_client

    res = await searcher.asearch(queries=["Async Query"])
    assert res["status"] == "success"
    assert res["queries"] == ["Async Query"]
    assert len(res["data"]) == 1
