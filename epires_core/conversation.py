"""Pask conversation for CONFLICTS_WITH — asserted→in_conversation→resolved."""

from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone

_VALID = {"merge", "split", "add_condition"}


def init_conversation_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS conversations(
        id TEXT PRIMARY KEY,
        a_id TEXT NOT NULL,
        b_id TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS conversation_turns(
        conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        agent TEXT NOT NULL,
        content TEXT NOT NULL,
        ts TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);
    CREATE INDEX IF NOT EXISTS idx_turns_conv ON conversation_turns(conv_id);
    """)


def open_conversation(a_id: str, b_id: str, conn: sqlite3.Connection) -> str:
    cid = f"c_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO conversations(id,a_id,b_id,status,created_at) VALUES (?,?,?,?,?)",
        (cid, a_id, b_id, "asserted", now),
    )
    return cid


def add_turn(conv_id: str, agent: str, content: str, conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT status FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not row:
        raise ValueError(f"conversation {conv_id} not found")
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO conversation_turns(conv_id,agent,content,ts) VALUES (?,?,?,?)",
        (conv_id, agent, content, ts),
    )
    # ponytail: asserted→in_conversation on first turn
    if row[0] == "asserted":
        conn.execute("UPDATE conversations SET status=? WHERE id=?", ("in_conversation", conv_id))


def resolve_conversation(conv_id: str, resolution: str, merged_id: str | None, conn: sqlite3.Connection) -> None:
    if resolution not in _VALID:
        raise ValueError(f"resolution must be one of {_VALID}, got {resolution!r}")
    if resolution == "merge" and not merged_id:
        raise ValueError("merged_id required when resolution='merge'")
    row = conn.execute("SELECT status FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not row:
        raise ValueError(f"conversation {conv_id} not found")
    conn.execute("UPDATE conversations SET status=? WHERE id=?", ("resolved", conv_id))
    # audit trail for merge
    if merged_id:
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversation_turns(conv_id,agent,content,ts) VALUES (?,?,?,?)",
            (conv_id, "system", f"resolution={resolution} merged_id={merged_id}", ts),
        )
