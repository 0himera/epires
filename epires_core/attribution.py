"""Duhem-Quine anomaly attribution: blame auxiliary assumptions before condemning the hypothesis."""

from __future__ import annotations

import json


def rank_suspects(ev, store) -> list[dict]:
    """Rank assumption_ids of `ev` by prior support in non-falsified evidence of OTHER hypotheses."""
    with store._get_connection() as conn:
        rows = conn.execute(
            "SELECT assumption_ids_json, falsification_triggered, hypothesis_id FROM evidence"
        ).fetchall()
    supports: dict[str, int] = {}
    for r in rows:
        if r["falsification_triggered"] or r["hypothesis_id"] == ev.hypothesis_id:
            continue
        for aid in json.loads(r["assumption_ids_json"] or "[]"):
            supports[aid] = supports.get(aid, 0) + 1
    return [
        {"assumption_id": aid, "prior_supports": supports.get(aid, 0)}
        for aid in sorted(set(ev.assumption_ids), key=lambda a: (supports.get(a, 0), a))
    ]


def attribute_anomaly(ev, store, min_independent: int = 2) -> str:
    """Decide where an anomaly bites: the hypothesis itself, an auxiliary assumption, or nobody."""
    with store._get_connection() as conn:
        rows = conn.execute(
            "SELECT assumption_ids_json FROM evidence WHERE hypothesis_id = ? AND falsification_triggered = 1",
            (ev.hypothesis_id,),
        ).fetchall()
    distinct_sets = {tuple(sorted(json.loads(r["assumption_ids_json"] or "[]"))) for r in rows}
    if len(distinct_sets) >= min_independent:
        return "attributed:hypothesis"
    suspects = rank_suspects(ev, store)
    if suspects:
        return f"attributed:auxiliary:{suspects[0]['assumption_id']}"
    return "inconclusive"
