"""Base SQLite storage, connection management, and schema initialization."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from ..hypergraph import HypergraphEncoder
from ..vsa import BipolarVSA


class StoreBase:
    """Base class providing SQLite connection lifecycle and schema setup."""

    def __init__(
        self,
        db_path: str | Path = ".epires/hypotheses.db",
        vsa_dim: int = 10000,
        trace_md_path: Optional[str | Path] = "docs/agent-trace.md",
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.trace_md_path = Path(trace_md_path) if trace_md_path else None
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and self.trace_md_path
            and str(self.trace_md_path).endswith("docs/agent-trace.md")
        ):
            self.trace_md_path = None  # ponytail: no docs write in pytest
        self.vsa = BipolarVSA(dim=vsa_dim)
        self.encoder = HypergraphEncoder(self.vsa)
        self._index: Any = None  # ponytail: lazy BinaryIndex, rebuilt on size mismatch or vector update
        self._dual_vsa: Any = None
        self._shard_router: Any = None
        self._compressor: Any = None
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
                commit_hash TEXT,
                prediction TEXT,
                timestamp TEXT NOT NULL,
                assumption_ids_json TEXT NOT NULL DEFAULT '[]',
                is_retracted INTEGER NOT NULL DEFAULT 0,
                retraction_reason TEXT,
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

            # TMS tables
            try:
                from ..tms import init_tms_tables

                init_tms_tables(conn)
            except Exception:
                pass

            # Safe migrations for pre-existing databases
            try:
                conn.execute("ALTER TABLE evidence ADD COLUMN assumption_ids_json TEXT NOT NULL DEFAULT '[]'")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE evidence ADD COLUMN is_retracted INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE evidence ADD COLUMN retraction_reason TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE evidence ADD COLUMN commit_hash TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE evidence ADD COLUMN prediction TEXT")
            except Exception:
                pass

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
