"""Calibration: Brier score, Platt scaling, per-agent rolling Brier + skeptical prior.

Brier: (p - o)^2, o∈{0,1}. Platt: σ(a·p+b)=1/(1+exp(-(a·p+b))).
fit_platt: gradient descent on logloss without sklearn.
calibrated_weight: ledger → rolling Brier per agent → Platt; <30 → 0.5.
"""

from __future__ import annotations

import json
import math
from typing import Any

MIN_RECORDS = 30  # ponytail: skeptical prior threshold, lower if agents scarce


def brier_score(stated_p: float, outcome: int) -> float:
    p = min(1.0, max(0.0, float(stated_p)))
    o = 1 if outcome else 0
    return (p - o) ** 2


def rolling_brier(records: list[tuple[float, int]]) -> float:
    if not records:
        return 0.0
    return sum(brier_score(p, o) for p, o in records) / len(records)


def platt_scale(p: float, a: float, b: float) -> float:
    p = min(1.0, max(0.0, float(p)))
    z = float(a) * p + float(b)
    # stable sigmoid
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    return math.exp(z) / (1.0 + math.exp(z))


def fit_platt(records: list[tuple[float, int]], lr: float = 0.5, iters: int = 500) -> tuple[float, float]:
    if len(records) < 2:
        return (1.0, 0.0)
    # clip targets to avoid log(0), standard Platt target smoothing
    a, b = 1.0, 0.0
    n = len(records)
    for _ in range(iters):
        ga = 0.0
        gb = 0.0
        for p, y in records:
            y = 1 if y else 0
            pred = platt_scale(p, a, b)
            # clip pred for grad stability
            pred = min(0.999, max(0.001, pred))
            err = pred - y
            ga += err * float(p)
            gb += err
        ga /= n
        gb /= n
        # L2 tiny
        ga += 1e-4 * a
        gb += 1e-4 * b
        a -= lr * ga
        b -= lr * gb
        if abs(ga) < 1e-6 and abs(gb) < 1e-6:
            break
    return (float(a), float(b))


def _load_records(agent_id: str, store: Any) -> list[tuple[float, int]]:
    rec: list[tuple[float, int]] = []
    # 1) store.list_traces (preferred)
    try:
        if hasattr(store, "list_traces"):
            traces = store.list_traces(limit=10000)  # type: ignore
            for t in traces or []:
                details = getattr(t, "details", None) or {}
                role = getattr(t, "agent_role", "") or ""
                aid = details.get("agent_id", role) if isinstance(details, dict) else role
                if aid != agent_id:
                    continue
                if isinstance(details, dict) and "stated_p" in details and "outcome" in details:
                    rec.append((float(details["stated_p"]), int(details["outcome"])))
                elif isinstance(details, dict) and "p" in details and "outcome" in details:
                    rec.append((float(details["p"]), int(details["outcome"])))
            if rec:
                return rec
    except Exception:
        pass
    # 2) direct SQL on traces
    try:
        if hasattr(store, "_get_connection"):
            with store._get_connection() as conn:  # type: ignore
                rows = conn.execute("SELECT details_json, agent_role FROM traces").fetchall()
                for r in rows:
                    try:
                        d = json.loads(r["details_json"] or "{}")
                    except Exception:
                        continue
                    role = r["agent_role"] or ""
                    aid = d.get("agent_id", role) if isinstance(d, dict) else role
                    if aid != agent_id:
                        continue
                    if isinstance(d, dict) and "stated_p" in d and "outcome" in d:
                        rec.append((float(d["stated_p"]), int(d["outcome"])))
                    elif isinstance(d, dict) and "p" in d and "outcome" in d:
                        rec.append((float(d["p"]), int(d["outcome"])))
                if rec:
                    return rec
    except Exception:
        pass
    # 3) store is dict mock
    try:
        if isinstance(store, dict):
            raw = store.get(agent_id) or store.get("records") or store.get("ledger") or []
            for r in raw or []:
                if isinstance(r, dict) and "stated_p" in r and "outcome" in r:
                    rec.append((float(r["stated_p"]), int(r["outcome"])))
                elif isinstance(r, (list, tuple)) and len(r) == 2:
                    rec.append((float(r[0]), int(r[1])))
    except Exception:
        pass
    return rec


def calibrated_weight(agent_id: str, stated_p: float, store: Any) -> float:
    """Return calibrated p for agent; <30 records → 0.5 skeptical prior.

    Usage in gates: p_cal = calibrated_weight(ev.agent_id, ev.stated_p, store)
                    weight = p_cal  # or 1 - brier, cap E-level if p_cal<0.6
    """
    p = min(1.0, max(0.0, float(stated_p)))
    records = _load_records(agent_id, store)
    if len(records) < MIN_RECORDS:
        return 0.5
    a, b = fit_platt(records)
    return platt_scale(p, a, b)
