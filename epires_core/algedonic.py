"""Algedonic bypass — contradiction / audit_fail / n_failures / budget."""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List

ALGEDONIC_TRIGGERS = ["contradiction", "audit_fail", "n_failures", "budget_exhausted"]


def _downstream_ids(store: Any, node_id: str) -> List[str]:
    if hasattr(store, "_get_connection"):
        try:
            with store._get_connection() as conn:  # type: ignore
                cur = conn.execute(
                    "WITH RECURSIVE downstream AS (SELECT source_id AS child_id FROM relations WHERE target_id=? AND relation_type='DEPENDS_ON' UNION SELECT r.source_id FROM relations r JOIN downstream d ON r.target_id=d.child_id WHERE r.relation_type='DEPENDS_ON') SELECT child_id FROM downstream;",
                    (node_id,),
                )
                return [r["child_id"] for r in cur.fetchall()]
        except Exception:
            pass
    try:
        rels = store.list_relations() if hasattr(store, "list_relations") else []  # type: ignore
        ch: Dict[str, List[str]] = {}
        for e in rels:
            rt = getattr(getattr(e, "relation_type", ""), "value", str(getattr(e, "relation_type", "")))
            if rt == "DEPENDS_ON":
                ch.setdefault(getattr(e, "target_id", ""), []).append(getattr(e, "source_id", ""))
        out: List[str] = []
        queue = list(ch.get(node_id, []))
        seen: set[str] = set()
        while queue:
            cur = queue.pop(0)
            if cur in seen:
                continue
            seen.add(cur)
            out.append(cur)
            queue.extend(ch.get(cur, []))
        return out
    except Exception:
        return []


def check_triggers(store: Any, n_failures_threshold: int = 3) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    try:
        hyps = store.list_hypotheses() if hasattr(store, "list_hypotheses") else []
    except Exception:
        hyps = []
    try:
        from .audit import audit_hypothesis  # type: ignore
    except Exception:
        audit_hypothesis = None  # type: ignore
    for h in hyps:
        hid = getattr(h, "id", "")
        try:
            evs = store.get_evidence_for_hypothesis(hid) if hasattr(store, "get_evidence_for_hypothesis") else []
        except Exception:
            evs = []
        has_true = any(getattr(e, "falsification_triggered", False) for e in evs)
        has_false = any(not getattr(e, "falsification_triggered", False) for e in evs)
        if has_true and has_false and len(evs) >= 2:
            out.append({"trigger": "contradiction", "node_id": hid, "severity": "high"})
        if audit_hypothesis is not None:
            try:
                a = audit_hypothesis(hid, store)  # type: ignore
                if not a["passed"]:
                    out.append({"trigger": "audit_fail", "node_id": hid, "severity": "high"})
            except Exception:
                pass
        downstream = _downstream_ids(store, hid)
        blocked = 0
        for cid in downstream:
            try:
                ch2 = store.get_hypothesis(cid) if hasattr(store, "get_hypothesis") else None
                st = getattr(getattr(ch2, "status", ""), "value", str(getattr(ch2, "status", ""))) if ch2 else ""
                if st == "BLOCKED":
                    blocked += 1
            except Exception:
                continue
        if blocked >= n_failures_threshold:
            out.append({"trigger": "n_failures", "node_id": hid, "severity": "medium"})
    try:
        traces = store.list_traces(limit=10001) if hasattr(store, "list_traces") else []  # type: ignore
        if len(traces) > 10000:
            out.append({"trigger": "budget_exhausted", "node_id": "global", "severity": "critical"})
    except Exception:
        pass
    return out


def freeze_branch(node_id: str, store: Any) -> List[str]:
    if hasattr(store, "_cascade_falsification"):
        try:
            return store._cascade_falsification(node_id)  # type: ignore
        except Exception:
            pass
    downstream = _downstream_ids(store, node_id)
    blocked: List[str] = []
    if hasattr(store, "_get_connection"):
        try:
            with store._get_connection() as conn:  # type: ignore
                now = datetime.now(timezone.utc).isoformat()
                for cid in downstream:
                    row = conn.execute("SELECT status FROM hypotheses WHERE id=?", (cid,)).fetchone()
                    if row and row["status"] != "BLOCKED":
                        conn.execute("UPDATE hypotheses SET status=?, updated_at=? WHERE id=?", ("BLOCKED", now, cid))
                    blocked.append(cid)
        except Exception:
            return downstream
        return blocked
    for cid in downstream:
        try:
            if hasattr(store, "update_hypothesis"):
                from epires_core.models import HypothesisStatus  # type: ignore

                store.update_hypothesis(h_id=cid, status=HypothesisStatus.BLOCKED)  # type: ignore
            blocked.append(cid)
        except Exception:
            blocked.append(cid)
    return blocked
