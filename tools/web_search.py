"""Parallel Web Search SDK Integration (version 1.3.0).

Enables the Principal Investigator (Lead-PI) agent to execute high-throughput,
multi-topic parallel web searches across scientific literature, ArXiv, and primary sources.
"""

from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
from parallel import Parallel, AsyncParallel


class ParallelWebSearcher:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("PARALLEL_API_KEY")
        self._client: Optional[Parallel] = None
        self._async_client: Optional[AsyncParallel] = None

    @property
    def client(self) -> Parallel:
        if not self.api_key:
            raise ValueError(
                "PARALLEL_API_KEY environment variable is not set. "
                "Please configure PARALLEL_API_KEY to use parallel web search."
            )
        if self._client is None:
            self._client = Parallel(api_key=self.api_key)
        return self._client

    @property
    def async_client(self) -> AsyncParallel:
        if not self.api_key:
            raise ValueError(
                "PARALLEL_API_KEY environment variable is not set. "
                "Please configure PARALLEL_API_KEY to use parallel web search."
            )
        if self._async_client is None:
            self._async_client = AsyncParallel(api_key=self.api_key)
        return self._async_client

    def search(
        self,
        queries: List[str],
        objective: Optional[str] = None,
        mode: str = "fast",
        max_chars: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Performs parallel multi-query search synchronously."""
        if not self.api_key:
            return {
                "error": "PARALLEL_API_KEY not configured",
                "queries": queries,
                "results": []
            }

        kwargs: Dict[str, Any] = {"search_queries": queries, "mode": mode}
        if objective:
            kwargs["objective"] = objective
        if max_chars:
            kwargs["max_chars_total"] = max_chars

        res = self.client.search(**kwargs)
        # Parse SearchResult object into dict/json-friendly format
        return {
            "queries": queries,
            "objective": objective,
            "raw": str(res) if hasattr(res, "__dict__") else res,
            "data": getattr(res, "data", None) or getattr(res, "results", None) or str(res)
        }

    async def asearch(
        self,
        queries: List[str],
        objective: Optional[str] = None,
        mode: str = "fast",
        max_chars: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Performs parallel multi-query search asynchronously."""
        if not self.api_key:
            return {
                "error": "PARALLEL_API_KEY not configured",
                "queries": queries,
                "results": []
            }

        kwargs: Dict[str, Any] = {"search_queries": queries, "mode": mode}
        if objective:
            kwargs["objective"] = objective
        if max_chars:
            kwargs["max_chars_total"] = max_chars

        res = await self.async_client.search(**kwargs)
        return {
            "queries": queries,
            "objective": objective,
            "raw": str(res) if hasattr(res, "__dict__") else res,
            "data": getattr(res, "data", None) or getattr(res, "results", None) or str(res)
        }
