"""SQLite Embedded Storage & VSA Hypergraph Engine with Cascading Falsification DAG."""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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
    def __init__(self, db_path: str | Path = ".epires/hypotheses.db", vsa_dim: int = 10000):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vsa = BipolarVSA(dim=vsa_dim)
        self.encoder = HypergraphEncoder(self.vsa)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

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

            CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON hypotheses(status);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_h_id ON evidence(hypothesis_id);
            CREATE INDEX IF NOT EXISTS idx_traces_h_tag ON traces(h_tag);
            """)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # -------------------------------------------------------------------------
    # Hypotheses
    # -------------------------------------------------------------------------
    def register_hypothesis(self, h: HypothesisNode) -> HypothesisNode:
        now = self._now()
        h.created_at = h.created_at or now
        h.updated_at = now

        # Get existing relations for encoding
        relations = [
            RelationEdge(source_id=h.id, target_id=pid, relation_type=RelationType.DEPENDS_ON)
            for pid in h.parent_ids
        ]
        evidence_claims = self.get_evidence_for_hypothesis(h.id)
        
        # Build VSA Hypervector
        vec = self.encoder.encode_hypothesis(h, relations=relations, evidence_claims=evidence_claims)
        vec_bytes = vec.tobytes()

        with self._get_connection() as conn:
            conn.execute("""
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
            """, (
                h.id, h.title, h.a_priori_mechanism, h.falsification_criteria,
                h.target_evidence_level.value, h.current_evidence_level.value, h.status.value,
                json.dumps(h.parent_ids), json.dumps([e.model_dump() for e in h.entities]),
                json.dumps(h.tags), vec_bytes, h.created_at, h.updated_at
            ))

            # Sync relations
            for pid in h.parent_ids:
                conn.execute("""
                INSERT OR IGNORE INTO relations (source_id, target_id, relation_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """, (h.id, pid, RelationType.DEPENDS_ON.value, json.dumps({})))

        self.log_trace(TraceEntry(
            timestamp=now,
            action="REGISTER_HYPOTHESIS",
            agent_role="Lead-PI",
            h_tag=h.id,
            summary=f"Registered hypothesis {h.id}: {h.title} [Status: {h.status.value}]",
            details={"a_priori": h.a_priori_mechanism, "falsification": h.falsification_criteria}
        ))
        return h

    def get_hypothesis(self, h_id: str) -> Optional[HypothesisNode]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM hypotheses WHERE id = ?", (h_id,)).fetchone()
            if not row:
                return None
            return self._row_to_hypothesis(row)

    def list_hypotheses(self, status: Optional[HypothesisStatus] = None) -> List[HypothesisNode]:
        with self._get_connection() as conn:
            if status:
                rows = conn.execute("SELECT * FROM hypotheses WHERE status = ? ORDER BY id ASC", (status.value,)).fetchall()
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
    def log_evidence(self, ev: EvidenceClaim) -> Tuple[EvidenceClaim, List[str]]:
        """Logs an empirical evidence claim and cascades falsification/promotion."""
        now = self._now()
        ev.timestamp = ev.timestamp or now
        blocked_children: List[str] = []

        with self._get_connection() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO evidence (
                id, hypothesis_id, evidence_level, source_confidence,
                claim, metric_name, metric_value, delta_vs_baseline,
                ci_95_lower, ci_95_upper, falsification_triggered,
                citation_or_path, artifact_hash, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ev.id, ev.hypothesis_id, ev.evidence_level.value, ev.source_confidence.value,
                ev.claim, ev.metric_name, ev.metric_value, ev.delta_vs_baseline,
                ev.ci_95_lower, ev.ci_95_upper, 1 if ev.falsification_triggered else 0,
                ev.citation_or_path, ev.artifact_hash, ev.timestamp
            ))

        h = self.get_hypothesis(ev.hypothesis_id)
        if h:
            if ev.falsification_triggered:
                h.status = HypothesisStatus.FALSIFIED
                self.register_hypothesis(h)
                blocked_children = self._cascade_falsification(ev.hypothesis_id)
            else:
                # Promote evidence level
                h.current_evidence_level = ev.evidence_level
                if ev.evidence_level.value >= h.target_evidence_level.value:
                    h.status = HypothesisStatus.CONFIRMED
                else:
                    h.status = HypothesisStatus.IN_PROGRESS
                self.register_hypothesis(h)

        self.log_trace(TraceEntry(
            timestamp=now,
            action="LOG_EVIDENCE",
            agent_role="Lead-PI",
            h_tag=ev.hypothesis_id,
            summary=f"Evidence [{ev.evidence_level.value}, {ev.source_confidence.value}] logged for {ev.hypothesis_id}: {ev.claim}"
                    + (f" -> FALSIFIED! Blocked {len(blocked_children)} child hypotheses." if ev.falsification_triggered else ""),
            details={"metric": ev.metric_name, "value": ev.metric_value, "delta": ev.delta_vs_baseline, "falsified": ev.falsification_triggered}
        ))
        return ev, blocked_children

    def _cascade_falsification(self, falsified_h_id: str) -> List[str]:
        """Finds all child hypotheses that depend on the falsified parent and marks them BLOCKED."""
        blocked: List[str] = []
        with self._get_connection() as conn:
            # Recursive query to find all downstream dependent hypotheses
            cursor = conn.execute("""
            WITH RECURSIVE downstream AS (
                SELECT source_id AS child_id FROM relations
                WHERE target_id = ? AND relation_type = 'DEPENDS_ON'
                UNION
                SELECT r.source_id FROM relations r
                JOIN downstream d ON r.target_id = d.child_id
                WHERE r.relation_type = 'DEPENDS_ON'
            )
            SELECT child_id FROM downstream;
            """, (falsified_h_id,))
            rows = cursor.fetchall()
            for r in rows:
                child_id = r["child_id"]
                conn.execute(
                    "UPDATE hypotheses SET status = ?, updated_at = ? WHERE id = ?",
                    (HypothesisStatus.BLOCKED.value, self._now(), child_id)
                )
                conn.execute("""
                INSERT OR IGNORE INTO relations (source_id, target_id, relation_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """, (falsified_h_id, child_id, RelationType.BLOCKS.value, json.dumps({"reason": "parent_falsified"})))
                blocked.append(child_id)

        if blocked:
            self.log_trace(TraceEntry(
                timestamp=self._now(),
                action="CASCADING_BLOCK",
                agent_role="System-DAG",
                h_tag=falsified_h_id,
                summary=f"Falsification of {falsified_h_id} cascaded to block dependent hypotheses: {', '.join(blocked)}",
                details={"blocked_hypotheses": blocked}
            ))
        return blocked

    def get_evidence_for_hypothesis(self, h_id: str) -> List[EvidenceClaim]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM evidence WHERE hypothesis_id = ? ORDER BY timestamp ASC", (h_id,)).fetchall()
            return [
                EvidenceClaim(
                    id=r["id"],
                    hypothesis_id=r["hypothesis_id"],
                    evidence_level=EvidenceLevel(r["evidence_level"]),
                    source_confidence=SourceConfidence(r["source_confidence"]),
                    claim=r["claim"],
                    metric_name=r["metric_name"],
                    metric_value=r["metric_value"],
                    delta_vs_baseline=r["delta_vs_baseline"],
                    ci_95_lower=r["ci_95_lower"],
                    ci_95_upper=r["ci_95_upper"],
                    falsification_triggered=bool(r["falsification_triggered"]),
                    citation_or_path=r["citation_or_path"] or "",
                    artifact_hash=r["artifact_hash"],
                    timestamp=r["timestamp"],
                ) for r in rows
            ]

    # -------------------------------------------------------------------------
    # VSA Associative Search & Gap Discovery
    # -------------------------------------------------------------------------
    def search(self, sq: SearchQuery) -> List[Tuple[HypothesisNode, float]]:
        """Performs sub-millisecond VSA cosine similarity search across all hypotheses."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM hypotheses WHERE vector_blob IS NOT NULL").fetchall()
            if not rows:
                return []

            ids = [r["id"] for r in rows]
            vectors = [np.frombuffer(r["vector_blob"], dtype=np.int8) for r in rows]
            matrix = np.stack(vectors, axis=0)

        # Build query hypervector
        terms = sq.query.split() if sq.query else []
        q_vec = self.encoder.encode_query(
            text_terms=terms,
            entities=sq.entities or [],
            status=sq.status.value if sq.status else None
        )

        sims = self.vsa.batch_similarity(q_vec, matrix)
        scored = list(zip(ids, sims))
        scored.sort(key=lambda x: x[1], reverse=True)

        results: List[Tuple[HypothesisNode, float]] = []
        for h_id, score in scored[:sq.limit]:
            h = self.get_hypothesis(h_id)
            if h:
                results.append((h, float(score)))
        return results

    def find_gaps(self, gq: GapQuery) -> List[Dict[str, Any]]:
        """Finds under-explored or untested entity combinations (White Spots / Gaps in research)."""
        all_h = self.list_hypotheses()
        tested_combinations: Dict[Tuple[str, ...], int] = {}
        dimension_values: Dict[str, set[str]] = {dim: set() for dim in gq.dimensions}

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
                tested_combinations[combo] = tested_combinations.get(combo, 0) + 1

        # Compute Cartesian product of seen dimension values
        import itertools
        all_combos = list(itertools.product(*[list(dimension_values[d]) for d in gq.dimensions]))

        gaps: List[Dict[str, Any]] = []
        for combo in all_combos:
            count = tested_combinations.get(combo, 0)
            if count < gq.min_tested:
                gaps.append({
                    "combination": {dim: val for dim, val in zip(gq.dimensions, combo)},
                    "tested_count": count,
                    "status": "UNTESTED" if count == 0 else "UNDER_TESTED"
                })
        return gaps

    # -------------------------------------------------------------------------
    # Tracing & Markdown / Mermaid Export
    # -------------------------------------------------------------------------
    def log_trace(self, entry: TraceEntry) -> None:
        now = self._now()
        entry.timestamp = entry.timestamp or now
        with self._get_connection() as conn:
            conn.execute("""
            INSERT INTO traces (timestamp, action, agent_role, h_tag, summary, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (entry.timestamp, entry.action, entry.agent_role, entry.h_tag, entry.summary, json.dumps(entry.details)))

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
                ) for r in reversed(rows)
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
            lines.append(f'  {h.id}["{h.id}: {title_clean}<br/>[{h.current_evidence_level.value} | {h.status.value}]"]:::{status_style}')

        for edge in edges:
            rel = edge["relation_type"]
            src = edge["source_id"]
            tgt = edge["target_id"]
            if rel == RelationType.DEPENDS_ON.value:
                lines.append(f"  {src} -->|depends_on| {tgt}")
            elif rel == RelationType.BLOCKS.value:
                lines.append(f"  {src} -.->|BLOCKS| {tgt}")
            elif rel == RelationType.FALSIFIES.value:
                lines.append(f"  {src} ==>|FALSIFIES| {tgt}")

        lines.append("```")
        return "\n".join(lines)
