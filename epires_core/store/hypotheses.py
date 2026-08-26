"""Hypothesis and Relation management, DAG graph node persistence."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import numpy as np

from ..models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    ExperimentNode,
    HypothesisNode,
    HypothesisStatus,
    RelationEdge,
    RelationType,
    TraceEntry,
)


class HypothesisMixin:
    """Hypothesis and Relation CRUD and bulk import operations."""

    def register_hypothesis(
        self,
        h: HypothesisNode,
        allow_status_override: bool = False,
        emit_trace: bool = True,
        preregistration_artifact: str | None = None,
    ) -> HypothesisNode:
        preregistration_hash: str | None = None
        if preregistration_artifact:
            artifact = Path(preregistration_artifact)
            if not artifact.is_file():
                raise ValueError(f"Preregistration artifact is not a readable file: {preregistration_artifact}")
            preregistration_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()

        # Check DAG cycle safety
        self._check_dag_cycle(h.id, h.parent_ids)

        now = self._now()
        existing = self.get_hypothesis(h.id)
        h.created_at = h.created_at or (existing.created_at if existing else now)
        h.updated_at = now

        # Invariant: a falsified, dependency-blocked, or confirmed node cannot be reopened
        # by a re-registration unless explicit override is permitted (e.g. via retraction).
        if existing and not allow_status_override:
            if existing.status in {HypothesisStatus.FALSIFIED, HypothesisStatus.BLOCKED, HypothesisStatus.CONFIRMED}:
                h.status = existing.status
            if existing.current_evidence_level.value > h.current_evidence_level.value:
                h.current_evidence_level = existing.current_evidence_level

        blocked_parent_ids = []
        for parent_id in h.parent_ids:
            parent = self.get_hypothesis(parent_id)
            if parent and parent.status in {HypothesisStatus.FALSIFIED, HypothesisStatus.BLOCKED}:
                blocked_parent_ids.append(parent_id)
        if blocked_parent_ids and h.status != HypothesisStatus.FALSIFIED:
            h.status = HypothesisStatus.BLOCKED

        # Encode VSA Hypervector
        vec = self.encoder.encode_hypothesis(h)
        vec_bytes = vec.astype(np.int8).tobytes()

        # Invalidate cached BinaryIndex so vector changes are immediately reflected
        self._index = None

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

            generated_block_metadata = json.dumps({"reason": "parent_falsified"})
            conn.execute(
                "DELETE FROM relations WHERE target_id = ? AND relation_type = ? AND metadata_json = ?",
                (h.id, RelationType.BLOCKS.value, generated_block_metadata),
            )
            for pid in blocked_parent_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO relations (source_id, target_id, relation_type, metadata_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (pid, h.id, RelationType.BLOCKS.value, generated_block_metadata),
                )

            # Mirror DEPENDS_ON into JTMS-lite justifications
            try:
                from ..tms import add_premise, add_justification

                if h.parent_ids:
                    add_justification(h.id, h.parent_ids, conn)
                else:
                    add_premise(h.id, conn)
            except Exception:
                pass

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
            if preregistration_artifact and preregistration_hash:
                self.log_trace(
                    TraceEntry(
                        timestamp=now,
                        action="PREREGISTRATION",
                        agent_role="Lead-PI",
                        h_tag=h.id,
                        summary=f"Preregistered {h.id} with artifact {preregistration_artifact}",
                        details={
                            "artifact_path": preregistration_artifact,
                            "artifact_hash": preregistration_hash,
                            "hash_algorithm": "sha256",
                        },
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
        allow_status_override: bool = True,
        agent_role: str = "Lead-PI",
    ) -> Optional[HypothesisNode]:
        """Explicitly update properties and/or status of an existing hypothesis."""
        h = self.get_hypothesis(h_id)
        if not h:
            return None

        if status == HypothesisStatus.CONFIRMED and not allow_status_override:
            target_lvl = target_evidence_level or h.target_evidence_level
            if h.current_evidence_level.value < target_lvl.value:
                raise ValueError(
                    f"Cannot manually set status of '{h_id}' to CONFIRMED: "
                    f"current evidence level ({h.current_evidence_level.value}) is lower than "
                    f"target evidence level ({target_lvl.value}). Empirical evidence must be logged to reach target level."
                )

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
            # CONFLICTS_WITH -> Pask conversation
            if edge.relation_type == RelationType.CONFLICTS_WITH:
                try:
                    from ..conversation import init_conversation_tables, open_conversation

                    init_conversation_tables(conn)
                    open_conversation(edge.source_id, edge.target_id, conn)
                except Exception:
                    pass

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

    def list_relations(self, relation_type: Optional[RelationType] = None) -> List[RelationEdge]:
        with self._get_connection() as conn:
            if relation_type:
                rows = conn.execute(
                    "SELECT * FROM relations WHERE relation_type = ? ORDER BY source_id ASC",
                    (relation_type.value,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM relations ORDER BY source_id ASC").fetchall()

            return [
                RelationEdge(
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    relation_type=RelationType(row["relation_type"]),
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
                for row in rows
            ]

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

        # Run bulk operations inside a transaction
        with self._get_connection() as conn:
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
                        pass

            # 3. Ingest relations
            for rel in relations or []:
                self.add_relation(rel, emit_trace=False)
                ingested_rel += 1

            # 4. Ingest experiments
            for exp in experiments or []:
                try:
                    self.register_experiment(exp, emit_trace=False)
                    ingested_exp += 1
                except ValueError:
                    if upsert:
                        pass

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
