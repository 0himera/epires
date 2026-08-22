"""TMS JTMS minimal — premises, justifications, IN/OUT propagation."""

from __future__ import annotations

import sqlite3
import uuid

TMS_DDL = """\
CREATE TABLE IF NOT EXISTS justifications(id TEXT PRIMARY KEY, consequent TEXT, is_premise INTEGER);
CREATE TABLE IF NOT EXISTS justification_inputs(just_id TEXT, antecedent TEXT);
CREATE INDEX IF NOT EXISTS idx_justifications_consequent ON justifications(consequent);
CREATE INDEX IF NOT EXISTS idx_justification_inputs_just_id ON justification_inputs(just_id);
CREATE INDEX IF NOT EXISTS idx_justification_inputs_antecedent ON justification_inputs(antecedent);
"""


def init_tms_tables(conn: sqlite3.Connection) -> None:
    """Создает таблицы JTMS (executescript TMS_DDL)."""
    conn.executescript(TMS_DDL)


def add_premise(node_id: str, conn: sqlite3.Connection) -> str:
    """Добавляет premise-узел p_<node_id> (is_premise=1)."""
    jid = f"p_{node_id}"
    conn.execute(
        "INSERT OR REPLACE INTO justifications(id, consequent, is_premise) VALUES (?, ?, 1)",
        (jid, node_id),
    )
    conn.commit()
    return jid


def add_justification(consequent: str, antecedents: list[str], conn: sqlite3.Connection) -> str:
    """Добавляет justification j_<hex4> для consequent от antecedents."""
    jid = f"j_{uuid.uuid4().hex[:4]}"
    conn.execute(
        "INSERT INTO justifications(id, consequent, is_premise) VALUES (?, ?, 0)",
        (jid, consequent),
    )
    for a in antecedents:
        conn.execute("INSERT INTO justification_inputs(just_id, antecedent) VALUES (?, ?)", (jid, a))
    conn.commit()
    return jid


def propagate_status(conn: sqlite3.Connection) -> dict[str, str]:
    """Вычисляет IN/OUT статусы до fixpoint (bounded 100)."""
    cur = conn.cursor()
    rows = cur.execute("SELECT id, consequent, is_premise FROM justifications").fetchall()
    inputs = cur.execute("SELECT just_id, antecedent FROM justification_inputs").fetchall()
    if not rows and not inputs:
        return {}
    just_ants: dict[str, list[str]] = {}
    for jid, ant in inputs:
        just_ants.setdefault(jid, []).append(ant)
    # ensure every justification has entry
    for jid, _, _ in rows:
        just_ants.setdefault(jid, [])
    premise_nodes: set[str] = {cons for _, cons, is_p in rows if is_p}
    cons_to_jids: dict[str, list[str]] = {}
    jid_to_cons: dict[str, str] = {}
    for jid, cons, _ in rows:
        jid_to_cons[jid] = cons
        cons_to_jids.setdefault(cons, []).append(jid)
    nodes: set[str] = set()
    for _, cons, _ in rows:
        nodes.add(cons)
    for _, ant in inputs:
        nodes.add(ant)
    nodes.update(premise_nodes)
    if not nodes:
        return {}
    # init: premise IN else OUT
    status: dict[str, str] = {n: ("IN" if n in premise_nodes else "OUT") for n in nodes}
    for _ in range(100):
        changed = False
        new_status = dict(status)
        for n in nodes:
            if n in premise_nodes:
                ns = "IN"
            else:
                jids = cons_to_jids.get(n, [])
                if not jids:
                    ns = "OUT"
                else:
                    ns = "OUT"
                    for jid in jids:
                        ants = just_ants.get(jid, [])
                        if not ants:
                            ns = "IN"
                            break
                        if all(status.get(a, "OUT") == "IN" for a in ants):
                            ns = "IN"
                            break
            if new_status[n] != ns:
                changed = True
                new_status[n] = ns
        status = new_status
        if not changed:
            break
    return status
