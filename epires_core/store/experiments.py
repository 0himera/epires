"""Experiment registration, provenance tracking, and reproducibility ledger."""

from __future__ import annotations

import json
from typing import Any, List, Optional
from ..models import ExperimentNode, TraceEntry


class ExperimentMixin:
    """Provides experiment logging and provenance tracking."""

    def register_experiment(self, exp: ExperimentNode, emit_trace: bool = True) -> ExperimentNode:
        """Registers a reproducible computational experiment associated with a hypothesis."""
        now = self._now()
        exp.created_at = exp.created_at or now

        with self._get_connection() as conn:
            existing = conn.execute("SELECT * FROM experiments WHERE id = ?", (exp.id,)).fetchone()
            if existing:
                existing_params = json.loads(existing["parameters_json"] or "{}")
                existing_metrics = json.loads(existing["metrics_json"] or "{}")
                if (
                    existing["script_path"] == exp.script_path
                    and existing_params == exp.parameters
                    and existing_metrics == exp.metrics
                ):
                    return exp

                conn.execute(
                    """
                UPDATE experiments SET
                    name = ?, script_path = ?, commit_hash = ?,
                    parameters_json = ?, metrics_json = ?, artifact_paths_json = ?
                WHERE id = ?
                """,
                    (
                        exp.name,
                        exp.script_path,
                        exp.commit_hash,
                        json.dumps(exp.parameters),
                        json.dumps(exp.metrics),
                        json.dumps(exp.artifact_paths),
                        exp.id,
                    ),
                )
            else:
                conn.execute(
                    """
                INSERT INTO experiments (
                    id, hypothesis_id, name, script_path, commit_hash,
                    parameters_json, metrics_json, artifact_paths_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        exp.id,
                        exp.hypothesis_id,
                        exp.name,
                        exp.script_path,
                        exp.commit_hash,
                        json.dumps(exp.parameters),
                        json.dumps(exp.metrics),
                        json.dumps(exp.artifact_paths),
                        exp.created_at,
                    ),
                )

        if emit_trace:
            self.log_trace(
                TraceEntry(
                    timestamp=now,
                    action="REGISTER_EXPERIMENT",
                    agent_role="Lead-PI",
                    h_tag=exp.hypothesis_id,
                    summary=f"Registered experiment {exp.id} for {exp.hypothesis_id}: {exp.name}",
                    details={"script": exp.script_path, "metrics": exp.metrics, "commit": exp.commit_hash},
                )
            )

        return exp

    def list_experiments(self, hypothesis_id: Optional[str] = None) -> List[ExperimentNode]:
        """List experiment records, tolerating legacy rows with missing JSON values."""
        with self._get_connection() as conn:
            if hypothesis_id is None:
                rows = conn.execute("SELECT * FROM experiments ORDER BY created_at ASC, id ASC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM experiments WHERE hypothesis_id = ? ORDER BY created_at ASC, id ASC",
                    (hypothesis_id,),
                ).fetchall()

            def decode(value: Optional[str], default: Any, expected_type: type) -> Any:
                if not value:
                    return default
                try:
                    loaded = json.loads(value)
                    if isinstance(loaded, expected_type):
                        return loaded
                    return default
                except Exception:
                    return default

            return [
                ExperimentNode(
                    id=row["id"],
                    hypothesis_id=row["hypothesis_id"],
                    name=row["name"],
                    script_path=row["script_path"],
                    commit_hash=row["commit_hash"],
                    parameters=decode(row["parameters_json"], {}, dict),
                    metrics=decode(row["metrics_json"], {}, dict),
                    evidence_ids=[],
                    artifact_paths=decode(row["artifact_paths_json"], [], list),
                    created_at=row["created_at"],
                )
                for row in rows
            ]
