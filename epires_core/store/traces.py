"""Trace logging and markdown audit synchronization."""

from __future__ import annotations

import json
from typing import List
from ..models import TraceEntry


class TraceMixin:
    """Provides operational trace ledger storage and Markdown documentation sync."""

    def log_trace(self, entry: TraceEntry) -> None:
        now = self._now()
        entry.timestamp = entry.timestamp or now
        with self._get_connection() as conn:
            conn.execute(
                """
            INSERT INTO traces (timestamp, action, agent_role, h_tag, summary, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    entry.timestamp,
                    entry.action,
                    entry.agent_role,
                    entry.h_tag,
                    entry.summary,
                    json.dumps(entry.details),
                ),
            )

        # Append to docs/agent-trace.md for real-time Markdown synchronization
        if self.trace_md_path and self.trace_md_path.parent.exists():
            try:
                # Rotate at 1MB, keep one previous generation (.1)
                if self.trace_md_path.exists() and self.trace_md_path.stat().st_size > 1_000_000:
                    self.trace_md_path.replace(self.trace_md_path.with_name(self.trace_md_path.name + ".1"))

                if not self.trace_md_path.exists():
                    header = (
                        "# Agent Trace & Epistemic Log\n\n"
                        "> Automated operational ledger for multisession persistence, evidence promotion, "
                        "and cascading falsification audits.\n\n"
                        "| Timestamp (UTC) | Role | Action | H-Tag | Commit | Summary |\n"
                        "|---|---|---|---|---|---|\n"
                    )
                    self.trace_md_path.write_text(header, encoding="utf-8")

                h_col = f"`{entry.h_tag}`" if entry.h_tag else "—"
                clean_summary = entry.summary.replace("|", "/")
                row = f"| {entry.timestamp} | `{entry.agent_role}` | **{entry.action}** | {h_col} | `local` | {clean_summary} |\n"
                with open(self.trace_md_path, "a", encoding="utf-8") as f:
                    f.write(row)
            except Exception:
                pass

    def list_traces(self, limit: int = 50) -> List[TraceEntry]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM traces ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [
                TraceEntry(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    action=r["action"],
                    agent_role=r["agent_role"],
                    h_tag=r["h_tag"],
                    summary=r["summary"],
                    details=json.loads(r["details_json"]),
                )
                for r in reversed(rows)
            ]
