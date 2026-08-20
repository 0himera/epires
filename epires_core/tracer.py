"""Automated Tracer: Synchronizes runtime events between SQLite and docs/agent-trace.md."""

from __future__ import annotations
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .models import TraceEntry
from .store import EpiresStore


class AutoTracer:
    def __init__(self, store: EpiresStore, trace_md_path: str | Path = "docs/agent-trace.md"):
        self.store = store
        self.trace_md_path = Path(trace_md_path)
        self.trace_md_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_trace_file()

    def _get_git_commit(self) -> str:
        try:
            res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False)
            return res.stdout.strip() or "uncommitted"
        except Exception:
            return "no-git"

    def _ensure_trace_file(self) -> None:
        if not self.trace_md_path.exists():
            header = (
                "# Agent Trace & Epistemic Log\n\n"
                "> Automated operational ledger for multisession persistence, evidence promotion, "
                "and cascading falsification audits.\n\n"
                "| Timestamp (UTC) | Role | Action | H-Tag | Commit | Summary |\n"
                "|---|---|---|---|---|---|\n"
            )
            self.trace_md_path.write_text(header, encoding="utf-8")

    def record(
        self,
        action: str,
        summary: str,
        h_tag: Optional[str] = None,
        agent_role: str = "Lead-PI",
        details: Optional[Dict[str, Any]] = None,
    ) -> TraceEntry:
        """Records a trace event both into SQLite and appends to docs/agent-trace.md."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        commit = self._get_git_commit()
        details_dict = details or {}

        entry = TraceEntry(
            timestamp=now, action=action, agent_role=agent_role, h_tag=h_tag, summary=summary, details=details_dict
        )

        # 1. Save to SQLite Store
        self.store.log_trace(entry)

        # 2. Append markdown row to docs/agent-trace.md
        h_col = f"`{h_tag}`" if h_tag else "—"
        clean_summary = summary.replace("|", "/")
        row = f"| {now} | **{agent_role}** | `{action}` | {h_col} | `{commit}` | {clean_summary} |\n"

        with open(self.trace_md_path, "a", encoding="utf-8") as f:
            f.write(row)

        return entry

    def sync_markdown_from_db(self) -> None:
        """Reconstructs docs/agent-trace.md from SQLite traces if needed."""
        traces = self.store.list_traces(limit=200)
        lines = [
            "# Agent Trace & Epistemic Log\n\n",
            "> Automated operational ledger for multisession persistence, evidence promotion, "
            "and cascading falsification audits.\n\n",
            "| Timestamp (UTC) | Role | Action | H-Tag | Summary |\n",
            "|---|---|---|---|---|\n",
        ]
        for t in traces:
            h_col = f"`{t.h_tag}`" if t.h_tag else "—"
            clean_summary = t.summary.replace("|", "/")
            lines.append(f"| {t.timestamp} | **{t.agent_role}** | `{t.action}` | {h_col} | {clean_summary} |\n")

        self.trace_md_path.write_text("".join(lines), encoding="utf-8")
