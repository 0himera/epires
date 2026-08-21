"""Pure metric collectors over an EpiresStore. No LLM, no IO beyond the store."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict

from epires_core.audit import posiwid_report
from epires_core.models import RelationType
from epires_core.stigmergy import bateson_filter


def false_cascade_count(store: Any) -> int:
    """BLOCKS edges whose source was falsified on evidence lacking assumption_ids (unattributed cascade)."""
    n = 0
    for edge in store.list_relations(RelationType.BLOCKS):
        fals = [ev for ev in store.get_evidence_for_hypothesis(edge.source_id) if ev.falsification_triggered]
        if fals and not any(ev.assumption_ids for ev in fals):
            n += 1
    return n


def attribution_verdicts(store: Any) -> list[str]:
    with store._get_connection() as conn:
        rows = conn.execute("SELECT details_json FROM traces WHERE action = 'ANOMALY_ATTRIBUTED'").fetchall()
    return [json.loads(r["details_json"]).get("verdict", "") for r in rows]


def brier(store: Any) -> float | None:
    """Mean (stated_p - outcome)^2 over evidence with stated_p."""
    # ponytail: store does not persist stated_p yet -> always None until schema grows
    pairs = [
        (ev.stated_p, 1.0 if ev.falsification_triggered else 0.0)
        for ev in store.list_evidence()
        if ev.stated_p is not None
    ]
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def collect(store: Any, scenario: str) -> Dict[str, Any]:
    statuses = Counter(h.status.value for h in store.list_hypotheses())
    evidence = store.list_evidence()
    return {
        "scenario": scenario,
        "integrity_gap": posiwid_report(store)["integrity_gap"],
        "n_confirmed": statuses.get("CONFIRMED", 0),
        "n_falsified": statuses.get("FALSIFIED", 0),
        "n_blocked": statuses.get("BLOCKED", 0),
        "attribution_verdicts": attribution_verdicts(store),
        "false_cascade_count": false_cascade_count(store),
        "bateson_hot": sum(1 for ev in evidence if bateson_filter(ev)),
        "bateson_total": len(evidence),
        "brier": brier(store),
    }
