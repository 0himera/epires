"""Empirical evidence ledger, strict epistemic gate validation, soft retraction, and falsification cascades."""

from __future__ import annotations

import json
import sqlite3
from typing import List, Optional, Tuple

from ..criteria import evaluate_falsification_condition, parse_falsification_criteria
from ..gates import STRICT as GATES_STRICT, compute_level
from ..models import (
    EvidenceClaim,
    EvidenceLevel,
    HypothesisStatus,
    SourceConfidence,
    TraceEntry,
)


class EvidenceMixin:
    """Provides append-only empirical evidence logging, soft retraction, and epistemic level computation."""

    def log_evidence(
        self,
        ev: EvidenceClaim,
        emit_trace: bool = True,
        auto_falsification: bool = True,
    ) -> Tuple[EvidenceClaim, List[str]]:
        """Logs an empirical evidence claim to an immutable append-only ledger and cascades falsification/promotion."""
        now = self._now()
        ev.timestamp = ev.timestamp or now
        blocked_children: List[str] = []

        h = self.get_hypothesis(ev.hypothesis_id)

        # Automatic machine evaluation of Popperian falsification criteria
        if (
            not ev.falsification_triggered
            and auto_falsification
            and h
            and h.falsification_criteria
            and ev.evidence_level in {EvidenceLevel.E3, EvidenceLevel.E4, EvidenceLevel.E5}
            and bool((ev.metric_name or "").strip())
            and any(
                value is not None for value in (ev.metric_value, ev.delta_vs_baseline, ev.ci_95_lower, ev.ci_95_upper)
            )
        ):
            conditions = parse_falsification_criteria(h.falsification_criteria)
            for cond in conditions:
                eval_res = evaluate_falsification_condition(
                    cond=cond,
                    metric_name=ev.metric_name,
                    metric_value=ev.metric_value,
                    delta_vs_baseline=ev.delta_vs_baseline,
                    ci_lower=ev.ci_95_lower,
                    ci_upper=ev.ci_95_upper,
                )
                if eval_res is True:
                    ev.falsification_triggered = True
                    break

        # Epistemic rigor validation: Positive E4 promotion requires confidence intervals
        if not ev.falsification_triggered and ev.evidence_level == EvidenceLevel.E4:
            if ev.ci_95_lower is None or ev.ci_95_upper is None:
                raise ValueError("Evidence level E4 requires 95% confidence intervals (ci_95_lower and ci_95_upper).")

        with self._get_connection() as conn:
            self._insert_evidence_row(conn, ev)

        if h:
            if GATES_STRICT:
                # STRICT: level is computed from full evidence set, registered experiments, and traces
                all_evs = self.get_evidence_for_hypothesis(ev.hypothesis_id)
                exps = self.list_experiments(ev.hypothesis_id)
                trs = self.list_traces()
                computed = compute_level(all_evs, h, experiments=exps, traces=trs)
                if computed.value > h.current_evidence_level.value:
                    h.current_evidence_level = computed
            else:
                # Monotonic evidence promotion
                if ev.evidence_level.value > h.current_evidence_level.value:
                    h.current_evidence_level = ev.evidence_level

            if ev.falsification_triggered:
                try:
                    from ..attribution import attribute_anomaly

                    verdict = attribute_anomaly(ev, self)
                    if verdict.startswith("attributed:auxiliary"):
                        h.status = HypothesisStatus.BLOCKED  # blame auxiliary, no cascade
                        self.register_hypothesis(h, allow_status_override=True, emit_trace=False)
                        self.log_trace(
                            TraceEntry(
                                timestamp=self._now(),
                                action="ANOMALY_ATTRIBUTED",
                                agent_role="System-DAG",
                                h_tag=ev.hypothesis_id,
                                summary=f"Anomaly attributed to auxiliary ({verdict}); hypothesis BLOCKED, no cascade",
                                details={"evidence_id": ev.id, "verdict": verdict},
                            )
                        )
                        return ev, []
                except Exception:
                    pass
                h.status = HypothesisStatus.FALSIFIED
                self.register_hypothesis(h, allow_status_override=True, emit_trace=False)
                blocked_children = self._cascade_falsification(ev.hypothesis_id)
            else:
                # Non-falsifying observations cannot reopen an invalidated or dependency-blocked hypothesis
                if h.status in {HypothesisStatus.FALSIFIED, HypothesisStatus.BLOCKED}:
                    pass
                elif h.current_evidence_level.value >= h.target_evidence_level.value:
                    h.status = HypothesisStatus.CONFIRMED
                else:
                    h.status = HypothesisStatus.IN_PROGRESS
                self.register_hypothesis(h, allow_status_override=True, emit_trace=False)

        if emit_trace:
            self.log_trace(
                TraceEntry(
                    timestamp=now,
                    action="LOG_EVIDENCE",
                    agent_role="Lead-PI",
                    h_tag=ev.hypothesis_id,
                    summary=f"Evidence [{ev.evidence_level.value}, {ev.source_confidence.value}] logged for {ev.hypothesis_id}: {ev.claim}"
                    + (
                        f" -> FALSIFIED! Blocked {len(blocked_children)} child hypotheses."
                        if ev.falsification_triggered
                        else ""
                    ),
                    details={
                        "evidence_id": ev.id,
                        "metric": ev.metric_name,
                        "value": ev.metric_value,
                        "delta": ev.delta_vs_baseline,
                        "falsified": ev.falsification_triggered,
                    },
                )
            )
        return ev, blocked_children

    @staticmethod
    def _insert_evidence_row(conn: sqlite3.Connection, ev: EvidenceClaim) -> None:
        """Insert one validated evidence row without graph, FTS, or trace side effects."""
        existing = conn.execute("SELECT id FROM evidence WHERE id = ?", (ev.id,)).fetchone()
        if existing:
            raise ValueError(
                f"Evidence claim '{ev.id}' already exists in ledger. Evidence records are immutable and append-only."
            )
        conn.execute(
            """
            INSERT INTO evidence (
                id, hypothesis_id, evidence_level, source_confidence,
                claim, metric_name, metric_value, delta_vs_baseline,
                ci_95_lower, ci_95_upper, falsification_triggered,
                citation_or_path, artifact_hash, commit_hash, prediction,
                timestamp, assumption_ids_json, is_retracted, retraction_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
            """,
            (
                ev.id,
                ev.hypothesis_id,
                ev.evidence_level.value,
                ev.source_confidence.value,
                ev.claim,
                ev.metric_name,
                ev.metric_value,
                ev.delta_vs_baseline,
                ev.ci_95_lower,
                ev.ci_95_upper,
                1 if ev.falsification_triggered else 0,
                ev.citation_or_path,
                ev.artifact_hash,
                ev.commit_hash,
                ev.prediction,
                ev.timestamp,
                json.dumps(ev.assumption_ids),
            ),
        )

    def append_evidence_row_only(self, ev: EvidenceClaim) -> Tuple[EvidenceClaim, dict[str, object]]:
        """Append exactly one evidence row, without promotion, relations, FTS, or traces."""
        ev.timestamp = ev.timestamp or self._now()
        if not self.get_hypothesis(ev.hypothesis_id):
            raise ValueError(f"Hypothesis '{ev.hypothesis_id}' does not exist in research graph.")
        with self._get_connection() as conn:
            self._insert_evidence_row(conn, ev)
        return ev, {
            "changed_tables": ["evidence"],
            "inserted_evidence_ids": [ev.id],
            "graph_updated": False,
            "trace_emitted": False,
        }

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceClaim]:
        """Fetch a single evidence record by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            return self._row_to_evidence(row) if row else None

    def retract_evidence(
        self, evidence_id: str, reason: str, agent_role: str = "Lead-PI"
    ) -> Tuple[Optional[EvidenceClaim], List[str]]:
        """Retracts an erroneous evidence record via soft retraction (append-only ledger integrity),

        recalculates the parent hypothesis's evidence level and status, and cascades unblocking
        to downstream child hypotheses if all their parents are valid.
        """
        now = self._now()
        target_ev = self.get_evidence(evidence_id)
        if not target_ev:
            return None, []

        hypothesis_id = target_ev.hypothesis_id
        unblocked_children: List[str] = []

        # Soft retraction: preserve record in ledger with retraction tombstone
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE evidence SET is_retracted = 1, retraction_reason = ? WHERE id = ?",
                (reason, evidence_id),
            )

        h = self.get_hypothesis(hypothesis_id)
        if h:
            remaining_evidence = self.get_evidence_for_hypothesis(hypothesis_id)

            # Recalculate evidence level from active remaining records
            if remaining_evidence:
                if GATES_STRICT:
                    exps = self.list_experiments(hypothesis_id)
                    trs = self.list_traces()
                    h.current_evidence_level = compute_level(remaining_evidence, h, experiments=exps, traces=trs)
                else:
                    max_lvl = max(ev.evidence_level.value for ev in remaining_evidence)
                    h.current_evidence_level = EvidenceLevel(max_lvl)
            else:
                h.current_evidence_level = EvidenceLevel.E0

            was_falsified = h.status == HypothesisStatus.FALSIFIED
            has_remaining_falsification = any(ev.falsification_triggered for ev in remaining_evidence)

            if has_remaining_falsification:
                h.status = HypothesisStatus.FALSIFIED
            else:
                # Restore status based on active evidence
                if len(remaining_evidence) == 0:
                    h.status = HypothesisStatus.PROPOSED
                elif h.current_evidence_level.value >= h.target_evidence_level.value:
                    h.status = HypothesisStatus.CONFIRMED
                else:
                    h.status = HypothesisStatus.IN_PROGRESS

            self.register_hypothesis(h, allow_status_override=True, emit_trace=False)

            # If hypothesis was falsified and is now un-falsified, unblock downstream children
            if was_falsified and not has_remaining_falsification:
                unblocked_children = self._cascade_unblock(hypothesis_id)

        self.log_trace(
            TraceEntry(
                timestamp=now,
                action="RETRACT_EVIDENCE",
                agent_role=agent_role,
                h_tag=hypothesis_id or "",
                summary=f"Retracted evidence [{evidence_id}] for {hypothesis_id}: {reason}"
                + (
                    f" -> UNBLOCKED {len(unblocked_children)} child hypotheses: {', '.join(unblocked_children)}"
                    if unblocked_children
                    else ""
                ),
                details={"evidence_id": evidence_id, "reason": reason, "unblocked": unblocked_children},
            )
        )

        return target_ev, unblocked_children

    def get_evidence_for_hypothesis(self, h_id: str) -> List[EvidenceClaim]:
        """Returns all active (non-retracted) evidence claims for the given hypothesis."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE hypothesis_id = ? AND (is_retracted = 0 OR is_retracted IS NULL) ORDER BY timestamp ASC",
                (h_id,),
            ).fetchall()
            return [self._row_to_evidence(r) for r in rows]

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> EvidenceClaim:
        raw_assumptions = row["assumption_ids_json"] if "assumption_ids_json" in row.keys() else "[]"
        try:
            aids = json.loads(raw_assumptions or "[]")
        except Exception:
            aids = []
        return EvidenceClaim(
            id=row["id"],
            hypothesis_id=row["hypothesis_id"],
            evidence_level=EvidenceLevel(row["evidence_level"]),
            source_confidence=SourceConfidence(row["source_confidence"]),
            claim=row["claim"],
            metric_name=row["metric_name"],
            metric_value=row["metric_value"],
            delta_vs_baseline=row["delta_vs_baseline"],
            ci_95_lower=row["ci_95_lower"],
            ci_95_upper=row["ci_95_upper"],
            falsification_triggered=bool(row["falsification_triggered"]),
            citation_or_path=row["citation_or_path"],
            artifact_hash=row["artifact_hash"],
            commit_hash=row["commit_hash"] if "commit_hash" in row.keys() else None,
            prediction=row["prediction"] if "prediction" in row.keys() else None,
            timestamp=row["timestamp"],
            assumption_ids=aids,
        )

    def list_evidence(
        self, hypothesis_id: Optional[str] = None, include_retracted: bool = False
    ) -> List[EvidenceClaim]:
        """List evidence records, optionally filtering by hypothesis and active retraction status."""
        retract_clause = "" if include_retracted else "AND (is_retracted = 0 OR is_retracted IS NULL)"
        with self._get_connection() as conn:
            if hypothesis_id:
                query = f"SELECT * FROM evidence WHERE hypothesis_id = ? {retract_clause} ORDER BY timestamp ASC"
                rows = conn.execute(query, (hypothesis_id,)).fetchall()
            else:
                query = f"SELECT * FROM evidence WHERE 1=1 {retract_clause} ORDER BY timestamp ASC"
                rows = conn.execute(query).fetchall()
            return [self._row_to_evidence(r) for r in rows]
