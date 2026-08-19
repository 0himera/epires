"""Parallel Web Search & Extraction SDK Integration (version 1.3.0).

Supports:
- Multi-query parallel deep search (fast, turbo, basic, advanced)
- Advanced search controls (max_results, max_chars_total, excerpt settings)
- URL text/markdown extraction via client.extract
- Fallback to agent native search tools (Claude Code / Codex / Antigravity / Cursor / OpenCode)
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from parallel import Parallel, AsyncParallel


def get_parallel_api_key() -> Optional[str]:
    """Discovers Parallel API key across environment, local .env, and global user credentials."""
    if os.getenv("PARALLEL_API_KEY"):
        return os.getenv("PARALLEL_API_KEY")

    for env_path in [Path(".env"), Path(".epires/.env")]:
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("PARALLEL_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
            except Exception:
                pass

    global_creds = Path.home() / ".epires" / "credentials.json"
    if global_creds.exists():
        try:
            data = json.loads(global_creds.read_text(encoding="utf-8"))
            if data.get("parallel_api_key"):
                return data["parallel_api_key"]
        except Exception:
            pass

    for p_path in [Path.home() / ".parallel" / "credentials.json", Path.home() / ".parallel" / "config.json"]:
        if p_path.exists():
            try:
                data = json.loads(p_path.read_text(encoding="utf-8"))
                val = data.get("api_key") or data.get("token") or data.get("PARALLEL_API_KEY")
                if val:
                    return val
            except Exception:
                pass

    return None


def save_global_api_key(api_key: str) -> Path:
    """Saves API key globally in ~/.epires/credentials.json."""
    creds_dir = Path.home() / ".epires"
    creds_dir.mkdir(parents=True, exist_ok=True)
    creds_file = creds_dir / "credentials.json"
    
    existing = {}
    if creds_file.exists():
        try:
            existing = json.loads(creds_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing["parallel_api_key"] = api_key.strip()
    creds_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return creds_file


class ParallelWebSearcher:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._client: Optional[Parallel] = None
        self._async_client: Optional[AsyncParallel] = None

    def _resolve_api_key(self) -> Optional[str]:
        if self.api_key is not None:
            return self.api_key if self.api_key else None
        return get_parallel_api_key()

    @property
    def is_available(self) -> bool:
        return bool(self._resolve_api_key())

    @property
    def client(self) -> Parallel:
        key = self._resolve_api_key()
        if not key:
            raise ValueError(
                "Parallel API key not configured. Use native harness search or run 'epires login'."
            )
        if self._client is None:
            self._client = Parallel(api_key=key)
        return self._client

    @property
    def async_client(self) -> AsyncParallel:
        key = self._resolve_api_key()
        if not key:
            raise ValueError(
                "Parallel API key not configured. Use native harness search or run 'epires login'."
            )
        if self._async_client is None:
            self._async_client = AsyncParallel(api_key=key)
        return self._async_client

    def search(
        self,
        queries: List[str],
        objective: Optional[str] = None,
        mode: str = "fast",
        max_chars: Optional[int] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Performs parallel multi-query search with advanced controls."""
        key = self._resolve_api_key()
        if not key:
            return {
                "status": "fallback_to_native",
                "message": "PARALLEL_API_KEY not configured. You can use your native harness/IDE search tool (Claude Code / Codex / Antigravity / Cursor / OpenCode), or run 'epires login'.",
                "queries": queries,
                "results": []
            }

        search_kwargs: Dict[str, Any] = {
            "search_queries": queries,
            "mode": mode,
        }
        if objective:
            search_kwargs["objective"] = objective
        if max_chars:
            search_kwargs["max_chars_total"] = max_chars
        if max_results:
            search_kwargs["advanced_settings"] = {"max_results": max_results}

        try:
            res = self.client.search(**search_kwargs)
            return {
                "status": "success",
                "queries": queries,
                "objective": objective,
                "mode": mode,
                "data": getattr(res, "data", None) or getattr(res, "results", None) or str(res)
            }
        except Exception as e:
            return {"status": "error", "message": str(e), "queries": queries}

    def extract(
        self,
        urls: List[str],
        objective: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extracts structured text/markdown content from specific research URLs."""
        key = self._resolve_api_key()
        if not key:
            return {
                "status": "fallback_to_native",
                "message": "PARALLEL_API_KEY not configured. Use native URL reader or run 'epires login'.",
                "urls": urls,
            }

        kwargs: Dict[str, Any] = {
            "urls": urls,
        }
        if objective:
            kwargs["objective"] = objective

        try:
            res = self.client.extract(**kwargs)
            return {
                "status": "success",
                "urls": urls,
                "data": getattr(res, "data", None) or getattr(res, "results", None) or str(res)
            }
        except Exception as e:
            return {"status": "error", "message": str(e), "urls": urls}

    async def asearch(
        self,
        queries: List[str],
        objective: Optional[str] = None,
        mode: str = "fast",
        max_chars: Optional[int] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Asynchronous multi-query search with advanced controls."""
        key = self._resolve_api_key()
        if not key:
            return {
                "status": "fallback_to_native",
                "message": "PARALLEL_API_KEY not configured. You can use your native harness/IDE search tool, or run 'epires login'.",
                "queries": queries,
                "results": []
            }

        search_kwargs: Dict[str, Any] = {
            "search_queries": queries,
            "mode": mode,
        }
        if objective:
            search_kwargs["objective"] = objective
        if max_chars:
            search_kwargs["max_chars_total"] = max_chars
        if max_results:
            search_kwargs["advanced_settings"] = {"max_results": max_results}

        try:
            res = await self.async_client.search(**search_kwargs)
            return {
                "status": "success",
                "queries": queries,
                "objective": objective,
                "mode": mode,
                "data": getattr(res, "data", None) or getattr(res, "results", None) or str(res)
            }
        except Exception as e:
            return {"status": "error", "message": str(e), "queries": queries}
