"""Parallel Web Search & Extraction SDK Integration (version 1.3.0).

Supports:
- Multi-query parallel deep search (fast, turbo, basic, advanced)
- Full content extraction and excerpt configuration (fetch_all, fetch_snippets_first)
- URL text/markdown extraction via client.extract
- Entity & finding discovery via client.beta
- Seamless fallback to agent native search tools (Claude Code / Codex / Antigravity / Cursor)
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
        self.api_key = api_key or get_parallel_api_key()
        self._client: Optional[Parallel] = None
        self._async_client: Optional[AsyncParallel] = None

    @property
    def is_available(self) -> bool:
        return bool(self.api_key or get_parallel_api_key())

    @property
    def client(self) -> Parallel:
        key = self.api_key or get_parallel_api_key()
        if not key:
            raise ValueError(
                "Parallel API key not configured. Use native harness search or run 'epires login'."
            )
        if self._client is None or self.api_key != key:
            self.api_key = key
            self._client = Parallel(api_key=self.api_key)
        return self._client

    @property
    def async_client(self) -> AsyncParallel:
        key = self.api_key or get_parallel_api_key()
        if not key:
            raise ValueError(
                "Parallel API key not configured. Use native harness search or run 'epires login'."
            )
        if self._async_client is None or self.api_key != key:
            self.api_key = key
            self._async_client = AsyncParallel(api_key=self.api_key)
        return self._async_client

    def search(
        self,
        queries: List[str],
        objective: Optional[str] = None,
        mode: str = "fast",
        max_chars: Optional[int] = None,
        include_full_content: bool = False,
        num_excerpts: int = 3,
    ) -> Dict[str, Any]:
        """Performs parallel multi-query search with advanced excerpt & content controls."""
        key = self.api_key or get_parallel_api_key()
        if not key:
            return {
                "status": "fallback_to_native",
                "message": "PARALLEL_API_KEY not configured. You can use your native harness/IDE search tool (Claude Code / Codex / Antigravity), or run 'epires login'.",
                "queries": queries,
                "results": []
            }

        self.api_key = key
        advanced_settings: Dict[str, Any] = {
            "excerpt_settings": {
                "include_excerpts": True,
                "num_excerpts": num_excerpts
            },
            "full_content_settings": {
                "include_full_content": include_full_content
            },
            "fetch_policy": {
                "policy": "fetch_all" if include_full_content else "fetch_snippets_first"
            }
        }

        kwargs: Dict[str, Any] = {
            "search_queries": queries,
            "mode": mode,
            "advanced_settings": advanced_settings
        }
        if objective:
            kwargs["objective"] = objective
        if max_chars:
            kwargs["max_chars_total"] = max_chars

        res = self.client.search(**kwargs)
        return {
            "status": "success",
            "queries": queries,
            "objective": objective,
            "mode": mode,
            "data": getattr(res, "data", None) or getattr(res, "results", None) or str(res)
        }

    def extract(
        self,
        urls: List[str],
        objective: Optional[str] = None,
        include_full_content: bool = True,
    ) -> Dict[str, Any]:
        """Extracts structured text/markdown content from specific research URLs."""
        key = self.api_key or get_parallel_api_key()
        if not key:
            return {
                "status": "fallback_to_native",
                "message": "PARALLEL_API_KEY not configured. Use native URL reader or run 'epires login'.",
                "urls": urls,
            }

        self.api_key = key
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
        include_full_content: bool = False,
        num_excerpts: int = 3,
    ) -> Dict[str, Any]:
        """Asynchronous multi-query search with advanced controls."""
        key = self.api_key or get_parallel_api_key()
        if not key:
            return {
                "status": "fallback_to_native",
                "message": "PARALLEL_API_KEY not configured. You can use your native harness/IDE search tool, or run 'epires login'.",
                "queries": queries,
                "results": []
            }

        self.api_key = key
        advanced_settings: Dict[str, Any] = {
            "excerpt_settings": {
                "include_excerpts": True,
                "num_excerpts": num_excerpts
            },
            "full_content_settings": {
                "include_full_content": include_full_content
            },
            "fetch_policy": {
                "policy": "fetch_all" if include_full_content else "fetch_snippets_first"
            }
        }

        kwargs: Dict[str, Any] = {
            "search_queries": queries,
            "mode": mode,
            "advanced_settings": advanced_settings
        }
        if objective:
            kwargs["objective"] = objective
        if max_chars:
            kwargs["max_chars_total"] = max_chars

        res = await self.async_client.search(**kwargs)
        return {
            "status": "success",
            "queries": queries,
            "objective": objective,
            "mode": mode,
            "data": getattr(res, "data", None) or getattr(res, "results", None) or str(res)
        }
