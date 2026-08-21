"""SQLite Embedded Storage & VSA Hypergraph Engine with Cascading Falsification DAG."""

from __future__ import annotations
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple
import numpy as np

from .models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    ExperimentNode,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    RelationEdge,
    RelationType,
    SearchQuery,
    SourceConfidence,
    TraceEntry,
)
from .vsa import BipolarVSA
from .hypergraph import HypergraphEncoder


class EpiresStore:
    def __init__(
        self,
        db_path: str | Path = ".epires/hypotheses.db",
        vsa_dim: int = 10000,
        trace_md_path: Optional[str | Path] = "docs/agent-trace.md",
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_md_path = Path(trace_md_path) if trace_md_path else None
        if os.getenv("PYTEST_CURRENT_TEST") and self.trace_md_path and str(self.trace_md_path).endswith("docs/agent-trace.md"):
            self.trace_md_path = None  # ponytail: no docs write in pytest
        self.vsa = BipolarVSA(dim=vsa_dim)
        self.encoder = HypergraphEncoder(self.vsa)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS hypotheses (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                a_priori_mechanism TEXT NOT NULL,
                falsification_criteria TEXT NOT NULL,
                target_evidence_level TEXT NOT NULL,
                current_evidence_level TEXT NOT NULL,
                status TEXT NOT NULL,
                parent_ids_json TEXT NOT NULL,
                entities_json TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                vector_blob BLOB,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS relations (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id, relation_type)
            );

            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                hypothesis_id TEXT NOT NULL,
                evidence_level TEXT NOT NULL,
                source_confidence TEXT NOT NULL,
                claim TEXT NOT NULL,
                metric_name TEXT,
                metric_value REAL,
                delta_vs_baseline REAL,
                ci_95_lower REAL,
                ci_95_upper REAL,
                falsification_triggered INTEGER NOT NULL DEFAULT 0,
                citation_or_path TEXT,
                artifact_hash TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                hypothesis_id TEXT NOT NULL,
                name TEXT NOT NULL,
                script_path TEXT NOT NULL,
                commit_hash TEXT,
                parameters_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                artifact_paths_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (hypothesis_id) REFERENCES hypotheses(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                agent_role TEXT NOT NULL,
                h_tag TEXT,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS hypotheses_fts USING fts5(
                id UNINDEXED,
                title,
                a_priori_mechanism,
                falsification_criteria,
                tags
            );

            CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON hypotheses(status);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_h_id ON evidence(hypothesis_id);
            CREATE INDEX IF NOT EXISTS idx_traces_h_tag ON traces(h_tag);
            """)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _check_dag_cycle(self, node_id: str, proposed_parents: List[str]) -> None:
        """Verifies that adding proposed_parents as dependencies to node_id does not form a directed cycle."""
        if not proposed_parents:
            return

        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT source_id, target_id FROM relations WHERE relation_type = ?", (RelationType.DEPENDS_ON.value,)
            ).fetchall()

        adj: Dict[str, List[str]] = {}
        for r in rows:
            src, tgt = r["source_id"], r["target_id"]
            if src != node_id:  # replace existing parent edges for this node
                adj.setdefault(src, []).append(tgt)

        for parent in proposed_parents:
            if parent == node_id:
                raise ValueError(f"Self-dependency cycle detected: hypothesis '{node_id}' cannot depend on itself.")

            # BFS from parent to see if it can reach node_id
            visited = set()
            queue = [parent]
            while queue:
                curr = queue.pop(0)
                if curr == node_id:
                    raise ValueError(
                        f"DAG cycle detected: hypothesis '{node_id}' cannot depend on '{parent}' "
                        f"because '{parent}' already transitively depends on '{node_id}'."
                    )
                if curr not in visited:
                    visited.add(curr)
                    queue.extend(adj.get(curr, []))

    # -------------------------------------------------------------------------
    # Hypotheses
    # -------------------------------------------------------------------------
    def register_hypothesis(
        self, h: HypothesisNode, allow_status_override: bool = False, emit_trace: bool = True
    ) -> HypothesisNode:
        # Check DAG cycle safety
        self._check_dag_cycle(h.id, h.parent_ids)

        now = self._now()
        existing = self.get_hypothesis(h.id)
        h.created_at = h.created_at or (existing.created_at if existing else now)
        h.updated_at = now

        if existing and not allow_status_override:
            # Preserve terminal/authoritative statuses against accidental overwrite
            if existing.current_evidence_level.value > h.current_evidence_level.value:
                h.current_evidence_level = existing.current_evidence_level
            if existing.status == HypothesisStatus.FALSIFIED:
                h.status = existing.status
            elif h.status == HypothesisStatus.FALSIFIED:
                pass
            elif existing.status in {HypothesisStatus.BLOCKED, HypothesisStatus.REFINED}:
                h.status = existing.status
            elif existing.status == HypothesisStatus.CONFIRMED and h.status in {
                HypothesisStatus.PROPOSED,
                HypothesisStatus.IN_PROGRESS,
            }:
                h.status = existing.status
            elif existing.status == HypothesisStatus.IN_PROGRESS and h.status == HypothesisStatus.PROPOSED:
                h.status = existing.status

        # Get existing relations for encoding
        relations = [
            RelationEdge(source_id=h.id, target_id=pid, relation_type=RelationType.DEPENDS_ON) for pid in h.parent_ids
        ]
        evidence_claims = self.get_evidence_for_hypothesis(h.id)

        # Build VSA Hypervector
        vec = self.encoder.encode_hypothesis(h, relations=relations, evidence_claims=evidence_claims)
        vec_bytes = vec.tobytes()

        with self._get_connection() as conn:
            conn.execute(
                """
            INSERT INTO hypotheses (
                id, title, a_priori_mechanism, falsification_criteria,
                target_evidence_level, current_evidence_level, status,
                parent_ids_json, entities_json, tags_json, vector_blob,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                a_priori_mechanism=excluded.a_priori_mechanism,
                falsification_criteria=excluded.falsification_criteria,
                target_evidence_level=excluded.target_evidence_level,
                current_evidence_level=excluded.current_evidence_level,
                status=excluded.status,
                parent_ids_json=excluded.parent_ids_json,
                entities_json=excluded.entities_json,
                tags_json=excluded.tags_json,
                vector_blob=excluded.vector_blob,
                updated_at=excluded.updated_at
            """,
                (
                    h.id,
                    h.title,
                    h.a_priori_mechanism,
                    h.falsification_criteria,
                    h.target_evidence_level.value,
                    h.current_evidence_level.value,
                    h.status.value,
                    json.dumps(h.parent_ids),
                    json.dumps([e.model_dump() for e in h.entities]),
                    json.dumps(h.tags),
                    vec_bytes,
                    h.created_at,
                    h.updated_at,
                ),
            )

            # Sync FTS5 index
            try:
                conn.execute("DELETE FROM hypotheses_fts WHERE id = ?", (h.id,))
                conn.execute(
                    """
                INSERT INTO hypotheses_fts (id, title, a_priori_mechanism, falsification_criteria, tags)
                VALUES (?, ?, ?, ?, ?)
                """,
                    (h.id, h.title, h.a_priori_mechanism, h.falsification_criteria, " ".join(h.tags)),
                )
            except Exception:
                pass

            # Sync relations
            conn.execute(
                "DELETE FROM relations WHERE source_id = ? AND relation_type = ?",
                (h.id, RelationType.DEPENDS_ON.value),
            )
            for pid in h.parent_ids:
                conn.execute(
                    """
                INSERT OR IGNORE INTO relations (source_id, target_id, relation_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                    (h.id, pid, RelationType.DEPENDS_ON.value, json.dumps({})),
                )

        if emit_trace:
            self.log_trace(
                TraceEntry(
                    timestamp=now,
                    action="REGISTER_HYPOTHESIS",
                    agent_role="Lead-PI",
                    h_tag=h.id,
                    summary=f"Registered hypothesis {h.id}: {h.title} [Status: {h.status.value}]",
                    details={"a_priori": h.a_priori_mechanism, "falsification": h.falsification_criteria},
                )
            )
        return h

    def update_hypothesis(
        self,
        h_id: str,
        title: Optional[str] = None,
        a_priori_mechanism: Optional[str] = None,
        falsification_criteria: Optional[str] = None,
        target_evidence_level: Optional[EvidenceLevel] = None,
        status: Optional[HypothesisStatus] = None,
        parent_ids: Optional[List[str]] = None,
        entities: Optional[List[Entity]] = None,
        tags: Optional[List[str]] = None,
        agent_role: str = "Lead-PI",
    ) -> Optional[HypothesisNode]:
        """Explicitly update properties and/or status of an existing hypothesis."""
        h = self.get_hypothesis(h_id)
        if not h:
            return None

        if title is not None:
            h.title = title
        if a_priori_mechanism is not None:
            h.a_priori_mechanism = a_priori_mechanism
        if falsification_criteria is not None:
            h.falsification_criteria = falsification_criteria
        if target_evidence_level is not None:
            h.target_evidence_level = target_evidence_level
        if status is not None:
            h.status = status
        if parent_ids is not None:
            h.parent_ids = parent_ids
        if entities is not None:
            h.entities = entities
        if tags is not None:
            h.tags = tags

        saved = self.register_hypothesis(h, allow_status_override=True, emit_trace=False)
        self.log_trace(
            TraceEntry(
                timestamp=self._now(),
                action="UPDATE_HYPOTHESIS",
                agent_role=agent_role,
                h_tag=h.id,
                summary=f"Updated hypothesis {h.id} -> Status: {h.status.value}, Target: {h.target_evidence_level.value}",
                details={"title": h.title, "status": h.status.value},
            )
        )
        return saved

    def add_relation(
        self,
        edge: RelationEdge,
        emit_trace: bool = True,
    ) -> RelationEdge:
        """Persists a graph relation edge between hypotheses, experiments, or evidence."""
        # If relation is DEPENDS_ON, verify DAG cycle
        if edge.relation_type == RelationType.DEPENDS_ON:
            h = self.get_hypothesis(edge.source_id)
            if h and edge.target_id not in h.parent_ids:
                new_parents = list(set(h.parent_ids + [edge.target_id]))
                self._check_dag_cycle(edge.source_id, new_parents)
                h.parent_ids = new_parents
                self.register_hypothesis(h, allow_status_override=True, emit_trace=False)
                return edge

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO relations (source_id, target_id, relation_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (edge.source_id, edge.target_id, edge.relation_type.value, json.dumps(edge.metadata)),
            )

        if emit_trace:
            self.log_trace(
                TraceEntry(
                    timestamp=self._now(),
                    action="ADD_RELATION",
                    agent_role="Lead-PI",
                    h_tag=edge.source_id,
                    summary=f"Linked {edge.source_id} ==[{edge.relation_type.value}]==> {edge.target_id}",
                    details={"metadata": edge.metadata},
                )
            )
        return edge

    def bulk_import(
        self,
        hypotheses: List[HypothesisNode],
        evidence: Optional[List[EvidenceClaim]] = None,
        relations: Optional[List[RelationEdge]] = None,
        experiments: Optional[List[ExperimentNode]] = None,
        traces: Optional[List[TraceEntry]] = None,
        upsert: bool = True,
        emit_summary_trace: bool = True,
        agent_role: str = "Lead-PI",
    ) -> Dict[str, Any]:
        """Fast bulk import of hypotheses, evidence, relations, experiments, and traces in a single transaction."""
        now = self._now()
        ingested_h = 0
        ingested_ev = 0
        ingested_rel = 0
        ingested_exp = 0
        ingested_tr = 0

        # 1. Ingest hypotheses
        for h in hypotheses:
            existing = self.get_hypothesis(h.id)
            if existing and not upsert:
                continue
            self.register_hypothesis(h, allow_status_override=True, emit_trace=False)
            ingested_h += 1

        # 2. Ingest evidence claims
        for ev in evidence or []:
            try:
                self.log_evidence(ev, emit_trace=False)
                ingested_ev += 1
            except ValueError:
                if upsert:
                    # If already exists in append-only ledger and upsert=True, keep existing
                    pass

        # 3. Ingest relations
        for rel in relations or []:
            self.add_relation(rel, emit_trace=False)
            ingested_rel += 1

        # 4. Ingest experiments
        for exp in experiments or []:
            self.register_experiment(exp, emit_trace=False)
            ingested_exp += 1

        # 5. Ingest traces
        for tr in traces or []:
            self.log_trace(tr)
            ingested_tr += 1

        if emit_summary_trace and (ingested_h > 0 or ingested_ev > 0 or ingested_rel > 0 or ingested_exp > 0):
            self.log_trace(
                TraceEntry(
                    timestamp=now,
                    action="BULK_INGEST",
                    agent_role=agent_role,
                    h_tag="",
                    summary=f"Bulk ingested {ingested_h} hypotheses, {ingested_ev} evidence, {ingested_rel} relations, {ingested_exp} experiments.",
                    details={
                        "hypotheses_count": ingested_h,
                        "evidence_count": ingested_ev,
                        "relations_count": ingested_rel,
                        "experiments_count": ingested_exp,
                    },
                )
            )

        return {
            "hypotheses_ingested": ingested_h,
            "evidence_ingested": ingested_ev,
            "relations_ingested": ingested_rel,
            "experiments_ingested": ingested_exp,
            "traces_ingested": ingested_tr,
            "total_hypotheses": len(self.list_hypotheses()),
            "total_evidence": len(self.list_evidence()),
            "total_relations": len(self.list_relations()),
            "total_experiments": len(self.list_experiments()),
        }

    def get_hypothesis(self, h_id: str) -> Optional[HypothesisNode]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM hypotheses WHERE id = ?", (h_id,)).fetchone()
            if not row:
                return None
            return self._row_to_hypothesis(row)

    def list_hypotheses(self, status: Optional[HypothesisStatus] = None) -> List[HypothesisNode]:
        with self._get_connection() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM hypotheses WHERE status = ? ORDER BY id ASC", (status.value,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM hypotheses ORDER BY id ASC").fetchall()
            return [self._row_to_hypothesis(r) for r in rows]

    def _row_to_hypothesis(self, row: sqlite3.Row) -> HypothesisNode:
        raw_entities = json.loads(row["entities_json"])
        entities = [Entity(**e) if isinstance(e, dict) else e for e in raw_entities]
        return HypothesisNode(
            id=row["id"],
            title=row["title"],
            a_priori_mechanism=row["a_priori_mechanism"],
            falsification_criteria=row["falsification_criteria"],
            target_evidence_level=EvidenceLevel(row["target_evidence_level"]),
            current_evidence_level=EvidenceLevel(row["current_evidence_level"]),
            status=HypothesisStatus(row["status"]),
            parent_ids=json.loads(row["parent_ids_json"]),
            entities=entities,
            tags=json.loads(row["tags_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # -------------------------------------------------------------------------
    # Evidence & Cascading Falsification
    # -------------------------------------------------------------------------
    def log_evidence(self, ev: EvidenceClaim, emit_trace: bool = True) -> Tuple[EvidenceClaim, List[str]]:
        """Logs an empirical evidence claim to an immutable append-only ledger and cascades falsification/promotion."""
        now = self._now()
        ev.timestamp = ev.timestamp or now
        blocked_children: List[str] = []

        # Epistemic rigor validation: Positive E4 promotion requires confidence intervals
        if not ev.falsification_triggered and ev.evidence_level == EvidenceLevel.E4:
            if ev.ci_95_lower is None or ev.ci_95_upper is None:
                raise ValueError("Evidence level E4 requires 95% confidence intervals (ci_95_lower and ci_95_upper).")

        with self._get_connection() as conn:
            # Check duplicate ID for strict append-only immutability
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
                citation_or_path, artifact_hash, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ev.timestamp,
                ),
            )

        h = self.get_hypothesis(ev.hypothesis_id)
        if h:
            # Evidence promotion is monotonic (records the highest rigor level reached)
            if ev.evidence_level.value > h.current_evidence_level.value:
                h.current_evidence_level = ev.evidence_level

            if ev.falsification_triggered:
                h.status = HypothesisStatus.FALSIFIED
                self.register_hypothesis(h, allow_status_override=True, emit_trace=False)
                blocked_children = self._cascade_falsification(ev.hypothesis_id)
            else:
                # Non-falsifying observations cannot reopen an invalidated or
                # dependency-blocked hypothesis.
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
                        "metric": ev.metric_name,
                        "value": ev.metric_value,
                        "delta": ev.delta_vs_baseline,
                        "falsified": ev.falsification_triggered,
                    },
                )
            )
        return ev, blocked_children

    def _cascade_falsification(self, falsified_h_id: str) -> List[str]:
        """Finds all child hypotheses that depend on the falsified parent and marks them BLOCKED."""
        blocked: List[str] = []
        with self._get_connection() as conn:
            # Recursive query to find all downstream dependent hypotheses
            cursor = conn.execute(
                """
            WITH RECURSIVE downstream AS (
                SELECT source_id AS child_id FROM relations
                WHERE target_id = ? AND relation_type = 'DEPENDS_ON'
                UNION
                SELECT r.source_id FROM relations r
                JOIN downstream d ON r.target_id = d.child_id
                WHERE r.relation_type = 'DEPENDS_ON'
            )
            SELECT child_id FROM downstream;
            """,
                (falsified_h_id,),
            )
            rows = cursor.fetchall()
            for r in rows:
                child_id = r["child_id"]
                child_status = conn.execute("SELECT status FROM hypotheses WHERE id = ?", (child_id,)).fetchone()
                # A separately falsified child remains FALSIFIED; do not
                # replace one terminal scientific result with another label.
                if child_status and child_status["status"] == HypothesisStatus.FALSIFIED.value:
                    continue
                conn.execute(
                    "UPDATE hypotheses SET status = ?, updated_at = ? WHERE id = ?",
                    (HypothesisStatus.BLOCKED.value, self._now(), child_id),
                )
                conn.execute(
                    """
                INSERT OR IGNORE INTO relations (source_id, target_id, relation_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                    (falsified_h_id, child_id, RelationType.BLOCKS.value, json.dumps({"reason": "parent_falsified"})),
                )
                blocked.append(child_id)

        if blocked:
            self.log_trace(
                TraceEntry(
                    timestamp=self._now(),
                    action="CASCADING_BLOCK",
                    agent_role="System-DAG",
                    h_tag=falsified_h_id,
                    summary=f"Falsification of {falsified_h_id} cascaded to block dependent hypotheses: {', '.join(blocked)}",
                    details={"blocked_hypotheses": blocked},
                )
            )
        return blocked

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceClaim]:
        """Fetch a single evidence record by ID."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
            return self._row_to_evidence(row) if row else None

    def retract_evidence(
        self, evidence_id: str, reason: str, agent_role: str = "Lead-PI"
    ) -> Tuple[Optional[EvidenceClaim], List[str]]:
        """Retracts an erroneous evidence record, recalculates the parent hypothesis's evidence level

        and status, and cascades unblocking to downstream child hypotheses if all their parents are valid.
        """
        now = self._now()
        target_ev = self.get_evidence(evidence_id)
        if not target_ev:
            return None, []

        hypothesis_id = target_ev.hypothesis_id
        unblocked_children: List[str] = []

        with self._get_connection() as conn:
            conn.execute("DELETE FROM evidence WHERE id = ?", (evidence_id,))

        h = self.get_hypothesis(hypothesis_id)
        if h:
            remaining_evidence = self.get_evidence_for_hypothesis(hypothesis_id)

            # Recalculate maximum evidence level from remaining records
            if remaining_evidence:
                max_lvl = max(ev.evidence_level.value for ev in remaining_evidence)
                h.current_evidence_level = EvidenceLevel(max_lvl)
            else:
                h.current_evidence_level = EvidenceLevel.E0

            was_falsified = h.status == HypothesisStatus.FALSIFIED
            has_remaining_falsification = any(ev.falsification_triggered for ev in remaining_evidence)

            if has_remaining_falsification:
                h.status = HypothesisStatus.FALSIFIED
            else:
                # Not falsified anymore! Restore status based on remaining evidence
                if len(remaining_evidence) == 0:
                    h.status = HypothesisStatus.PROPOSED
                elif h.current_evidence_level.value >= h.target_evidence_level.value:
                    h.status = HypothesisStatus.CONFIRMED
                else:
                    h.status = HypothesisStatus.IN_PROGRESS

            self.register_hypothesis(h, allow_status_override=True)

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

    def _cascade_unblock(self, unblocked_h_id: str) -> List[str]:
        """Finds all child hypotheses that were BLOCKED by unblocked_h_id, checks if all their

        parents are now valid, and if so restores their status and cascades to their descendants.
        """
        unblocked: List[str] = []
        with self._get_connection() as conn:
            # Remove BLOCKS relations originating from this unblocked parent
            conn.execute(
                "DELETE FROM relations WHERE source_id = ? AND relation_type = ?",
                (unblocked_h_id, RelationType.BLOCKS.value),
            )

            # Query all downstream candidates that depend on unblocked_h_id
            cursor = conn.execute(
                """
            WITH RECURSIVE downstream AS (
                SELECT source_id AS child_id FROM relations
                WHERE target_id = ? AND relation_type = 'DEPENDS_ON'
                UNION
                SELECT r.source_id FROM relations r
                JOIN downstream d ON r.target_id = d.child_id
                WHERE r.relation_type = 'DEPENDS_ON'
            )
            SELECT DISTINCT child_id FROM downstream;
            """,
                (unblocked_h_id,),
            )
            candidates = [r["child_id"] for r in cursor.fetchall()]

        # Process candidates
        for child_id in candidates:
            child = self.get_hypothesis(child_id)
            if not child or child.status != HypothesisStatus.BLOCKED:
                continue

            # Check if ANY parent of child_id is currently FALSIFIED or BLOCKED
            parent_ids = child.parent_ids
            has_blocked_parent = False
            for p_id in parent_ids:
                parent = self.get_hypothesis(p_id)
                if parent and parent.status in {HypothesisStatus.FALSIFIED, HypothesisStatus.BLOCKED}:
                    has_blocked_parent = True
                    break

            if not has_blocked_parent:
                # All parents are healthy! Restore child status based on its own evidence
                child_ev = self.get_evidence_for_hypothesis(child_id)
                has_own_falsification = any(ev.falsification_triggered for ev in child_ev)
                if has_own_falsification:
                    child.status = HypothesisStatus.FALSIFIED
                elif len(child_ev) == 0:
                    child.status = HypothesisStatus.PROPOSED
                elif child.current_evidence_level.value >= child.target_evidence_level.value:
                    child.status = HypothesisStatus.CONFIRMED
                else:
                    child.status = HypothesisStatus.IN_PROGRESS

                self.register_hypothesis(child, allow_status_override=True)
                unblocked.append(child_id)

        if unblocked:
            self.log_trace(
                TraceEntry(
                    timestamp=self._now(),
                    action="CASCADING_UNBLOCK",
                    agent_role="System-DAG",
                    h_tag=unblocked_h_id,
                    summary=f"Unfalsification of {unblocked_h_id} cascaded to unblock dependent hypotheses: {', '.join(unblocked)}",
                    details={"unblocked_hypotheses": unblocked},
                )
            )

        return unblocked

    def get_evidence_for_hypothesis(self, h_id: str) -> List[EvidenceClaim]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE hypothesis_id = ? ORDER BY timestamp ASC", (h_id,)
            ).fetchall()
            return [self._row_to_evidence(r) for r in rows]

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> EvidenceClaim:
        """Convert an evidence row without exposing SQLite-specific values."""
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
            citation_or_path=row["citation_or_path"] or "",
            artifact_hash=row["artifact_hash"],
            timestamp=row["timestamp"],
        )

    def list_evidence(self, hypothesis_id: Optional[str] = None) -> List[EvidenceClaim]:
        """List evidence claims in insertion order (optionally for one hypothesis)."""
        with self._get_connection() as conn:
            if hypothesis_id is None:
                rows = conn.execute("SELECT * FROM evidence ORDER BY timestamp ASC, id ASC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM evidence WHERE hypothesis_id = ? ORDER BY timestamp ASC, id ASC",
                    (hypothesis_id,),
                ).fetchall()
            return [self._row_to_evidence(row) for row in rows]

    def list_relations(self, relation_type: Optional[RelationType] = None) -> List[RelationEdge]:
        """Return persisted graph edges in deterministic order."""
        with self._get_connection() as conn:
            if relation_type is None:
                rows = conn.execute(
                    "SELECT * FROM relations ORDER BY source_id ASC, target_id ASC, relation_type ASC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM relations WHERE relation_type = ? ORDER BY source_id ASC, target_id ASC",
                    (relation_type.value,),
                ).fetchall()
            return [
                RelationEdge(
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    relation_type=RelationType(row["relation_type"]),
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
                for row in rows
            ]

    def register_experiment(self, exp: ExperimentNode, emit_trace: bool = True) -> ExperimentNode:
        """Registers a reproducible computational experiment associated with a hypothesis."""
        now = self._now()
        exp.created_at = exp.created_at or now

        with self._get_connection() as conn:
            conn.execute(
                """
            INSERT INTO experiments (
                id, hypothesis_id, name, script_path, commit_hash,
                parameters_json, metrics_json, artifact_paths_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                script_path=excluded.script_path,
                commit_hash=excluded.commit_hash,
                parameters_json=excluded.parameters_json,
                metrics_json=excluded.metrics_json,
                artifact_paths_json=excluded.artifact_paths_json
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
                    decoded = json.loads(value)
                except (TypeError, ValueError):
                    return default
                return decoded if isinstance(decoded, expected_type) else default

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

    # -------------------------------------------------------------------------
    # Hybrid FTS5 + VSA Associative Search & Gap Discovery
    # -------------------------------------------------------------------------
    def search(self, sq: SearchQuery) -> List[Tuple[HypothesisNode, float]]:
        """Performs hybrid full-text (SQLite FTS5) and VSA cosine similarity search."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM hypotheses WHERE vector_blob IS NOT NULL").fetchall()
            if not rows:
                return []

            ids = [r["id"] for r in rows]
            vectors = [np.frombuffer(r["vector_blob"], dtype=np.int8) for r in rows]
            matrix = np.stack(vectors, axis=0)

        # 1. Full-text search via SQLite FTS5
        fts_matches: Dict[str, float] = {}
        if sq.query and sq.query.strip():
            with self._get_connection() as conn:
                try:
                    words = [w for w in sq.query.replace('"', " ").replace("'", " ").split() if len(w) >= 2]
                    if words:
                        match_query = " OR ".join([f'"{w}"*' for w in words])
                        fts_rows = conn.execute(
                            "SELECT id, rank FROM hypotheses_fts WHERE hypotheses_fts MATCH ? ORDER BY rank LIMIT 50",
                            (match_query,),
                        ).fetchall()
                        for r in fts_rows:
                            fts_matches[r["id"]] = max(0.5, 1.0 / (1.0 + abs(float(r["rank"]))))
                except Exception:
                    pass

        # 2. VSA query hypervector
        terms = sq.query.split() if sq.query else []
        q_vec = self.encoder.encode_query(
            text_terms=terms, entities=sq.entities or [], status=sq.status.value if sq.status else None
        )

        sims = self.vsa.batch_similarity(q_vec, matrix)

        # 3. Hybrid fusion
        combined_scores: List[Tuple[str, float]] = []
        for h_id, vsa_sim in zip(ids, sims):
            score = float(vsa_sim) + fts_matches.get(h_id, 0.0)
            combined_scores.append((h_id, score))

        combined_scores.sort(key=lambda x: x[1], reverse=True)

        results: List[Tuple[HypothesisNode, float]] = []
        for h_id, score in combined_scores[: sq.limit]:
            h = self.get_hypothesis(h_id)
            if h:
                results.append((h, float(score)))
        return results

    def find_gaps(self, gq: GapQuery) -> List[Dict[str, Any]]:
        """Finds under-explored or untested entity combinations (White Spots / Gaps in research).

        Distinguishes mere conceptual hypotheses from empirically tested combinations.
        """
        all_h = self.list_hypotheses()
        tested_combinations: Dict[Tuple[str, ...], int] = {}
        hypothesized_combinations: Dict[Tuple[str, ...], int] = {}
        dimension_values: Dict[str, set[str]] = {dim: set() for dim in gq.dimensions}

        # Cache evidence and experiment counts per hypothesis
        with self._get_connection() as conn:
            ev_counts = {
                r["hypothesis_id"]: r["c"]
                for r in conn.execute(
                    "SELECT hypothesis_id, COUNT(*) as c FROM evidence GROUP BY hypothesis_id"
                ).fetchall()
            }
            exp_counts = {
                r["hypothesis_id"]: r["c"]
                for r in conn.execute(
                    "SELECT hypothesis_id, COUNT(*) as c FROM experiments GROUP BY hypothesis_id"
                ).fetchall()
            }

        for h in all_h:
            ent_map: Dict[str, str] = {
                e.type if hasattr(e, "type") else e["type"]: e.value if hasattr(e, "value") else e["value"]
                for e in h.entities
            }
            for dim in gq.dimensions:
                if dim in ent_map:
                    dimension_values[dim].add(ent_map[dim])

            # Check if hypothesis covers all requested dimensions
            if all(dim in ent_map for dim in gq.dimensions):
                combo = tuple(ent_map[dim] for dim in gq.dimensions)
                hypothesized_combinations[combo] = hypothesized_combinations.get(combo, 0) + 1

                # An entity combination is considered empirically tested if it has evidence/experiments
                empirical_weight = ev_counts.get(h.id, 0) + exp_counts.get(h.id, 0)
                if empirical_weight > 0 or h.status in {HypothesisStatus.CONFIRMED, HypothesisStatus.FALSIFIED}:
                    tested_combinations[combo] = tested_combinations.get(combo, 0) + max(1, empirical_weight)

        # Compute Cartesian product of seen dimension values
        import itertools

        all_combos = list(itertools.product(*[list(dimension_values[d]) for d in gq.dimensions]))

        gaps: List[Dict[str, Any]] = []
        for combo in all_combos:
            tested_count = tested_combinations.get(combo, 0)
            hypo_count = hypothesized_combinations.get(combo, 0)
            if tested_count < gq.min_tested:
                gaps.append(
                    {
                        "combination": {dim: val for dim, val in zip(gq.dimensions, combo)},
                        "tested_count": tested_count,
                        "hypothesized_count": hypo_count,
                        "status": "UNTESTED" if tested_count == 0 else "UNDER_TESTED",
                    }
                )
        return gaps

    # -------------------------------------------------------------------------
    # Tracing & Markdown / Mermaid Export
    # -------------------------------------------------------------------------
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

    def export_mermaid_dag(self) -> str:
        """Generates a Mermaid graph markdown representing the hypothesis dependency DAG."""
        all_h = self.list_hypotheses()
        if not all_h:
            return "```mermaid\ngraph TD\n  Empty[No Hypotheses Registered]\n```"

        lines = ["```mermaid", "graph TD"]

        # Color classes
        lines.append("  classDef confirmed fill:#2ea043,stroke:#1b4b27,color:#fff;")
        lines.append("  classDef falsified fill:#da3633,stroke:#8e1519,color:#fff;")
        lines.append("  classDef blocked fill:#6e7681,stroke:#30363d,color:#fff;")
        lines.append("  classDef in_prog fill:#d29922,stroke:#bb8009,color:#fff;")
        lines.append("  classDef proposed fill:#58a6ff,stroke:#1f6feb,color:#fff;")

        with self._get_connection() as conn:
            edges = conn.execute("SELECT * FROM relations").fetchall()

        for h in all_h:
            status_style = {
                HypothesisStatus.CONFIRMED: "confirmed",
                HypothesisStatus.FALSIFIED: "falsified",
                HypothesisStatus.BLOCKED: "blocked",
                HypothesisStatus.IN_PROGRESS: "in_prog",
                HypothesisStatus.PROPOSED: "proposed",
                HypothesisStatus.REFINED: "in_prog",
            }.get(h.status, "proposed")

            title_clean = h.title.replace('"', "'")
            lines.append(
                f'  {h.id}["{h.id}: {title_clean}<br/>[{h.current_evidence_level.value} | {h.status.value}]"]:::{status_style}'
            )

        for edge in edges:
            rel = edge["relation_type"]
            src = edge["source_id"]
            tgt = edge["target_id"]
            if rel == RelationType.DEPENDS_ON.value:
                lines.append(f"  {src} -->|depends_on| {tgt}")
            elif rel == RelationType.SUPERSEDES.value:
                lines.append(f"  {src} ==>|SUPERSEDES| {tgt}")
            elif rel == RelationType.CONFLICTS_WITH.value:
                lines.append(f"  {src} <-.->|CONFLICTS_WITH| {tgt}")
            elif rel == RelationType.REFINES.value:
                lines.append(f"  {src} -->|REFINES| {tgt}")
            elif rel == RelationType.BLOCKS.value:
                lines.append(f"  {src} -.->|BLOCKS| {tgt}")
            elif rel == RelationType.FALSIFIES.value:
                lines.append(f"  {src} ==>|FALSIFIES| {tgt}")
            elif rel == RelationType.PRODUCES.value:
                lines.append(f"  {src} -->|PRODUCES| {tgt}")
            elif rel == RelationType.GATED_BY.value:
                lines.append(f"  {src} -.->|GATED_BY| {tgt}")
            else:
                lines.append(f"  {src} -->|{rel}| {tgt}")

        lines.append("```")
        return "\n".join(lines)
