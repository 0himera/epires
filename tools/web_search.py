"""Parallel Web Search SDK Integration (version 1.3.0).

Supports global credential discovery from ~/.epires/credentials.json,
~/.parallel/, local .env, and environment variables.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from parallel import Parallel, AsyncParallel


def get_parallel_api_key() -> Optional[str]:
    """Discovers Parallel API key across environment, local .env, and global user credentials."""
    # 1. Environment variable
    if os.getenv("PARALLEL_API_KEY"):
        return os.getenv("PARALLEL_API_KEY")

    # 2. Local .env
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

    # 3. Global ~/.epires/credentials.json
    global_creds = Path.home() / ".epires" / "credentials.json"
    if global_creds.exists():
        try:
            data = json.loads(global_creds.read_text(encoding="utf-8"))
            if data.get("parallel_api_key"):
                return data["parallel_api_key"]
        except Exception:
            pass

    # 4. Global ~/.parallel/ credentials
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
    def client(self) -> Parallel:
        if not self.api_key:
            raise ValueError(
                "Parallel API key not found. Run 'epires login' or set PARALLEL_API_KEY."
            )
        if self._client is None:
            self._client = Parallel(api_key=self.api_key)
        return self._client

    @property
    def async_client(self) -> AsyncParallel:
        if not self.api_key:
            raise ValueError(
                "Parallel API key not found. Run 'epires login' or set PARALLEL_API_KEY."
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
        key = self.api_key or get_parallel_api_key()
        if not key:
            return {
                "error": "PARALLEL_API_KEY not configured. Run 'epires login' to connect your account.",
                "queries": queries,
                "results": []
            }

        self.api_key = key
        kwargs: Dict[str, Any] = {"search_queries": queries, "mode": mode}
        if objective:
            kwargs["objective"] = objective
        if max_chars:
            kwargs["max_chars_total"] = max_chars

        res = self.client.search(**kwargs)
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
        key = self.api_key or get_parallel_api_key()
        if not key:
            return {
                "error": "PARALLEL_API_KEY not configured. Run 'epires login' to connect your account.",
                "queries": queries,
                "results": []
            }

        self.api_key = key
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
