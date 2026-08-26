"""Audit S3* — POSIWID + G1-G3 gates. Pure functions, no LLM."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List


def _is_url_like(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _citation_resolves(citation: str) -> bool:
    c = (citation or "").strip()
    if not c:
        return False
    if _is_url_like(c):
        return True
    # ponytail: file existence check, stdlib only
    return Path(c).exists()


def _hash_matches(citation: str, artifact_hash: str | None) -> bool:
    c = (citation or "").strip()
    if not c:
        return False
    if _is_url_like(c):
        return True
    if not artifact_hash:
        return False
    p = Path(c)
    if not p.is_file():
        return False
    try:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        return h.lower() == artifact_hash.lower().strip()
    except Exception:
        return False


def audit_hypothesis(h_id: str, store: Any) -> Dict[str, Any]:
    """Audit single hypothesis. Returns {"passed":bool,"violations":list,"gates":dict}."""
    violations: List[str] = []
    gates: Dict[str, bool] = {}

    h = store.get_hypothesis(h_id) if hasattr(store, "get_hypothesis") else None
    if not h:
        return {"passed": False, "violations": [f"hypothesis not found: {h_id}"], "gates": {}}

    # tolerate both signatures: list_experiments(h_id) positional or keyword
    try:
        evs = store.get_evidence_for_hypothesis(h_id) if hasattr(store, "get_evidence_for_hypothesis") else []
    except Exception:
        evs = []
    try:
        if hasattr(store, "list_experiments"):
            try:
                exps = store.list_experiments(h_id)  # type: ignore
            except TypeError:
                exps = store.list_experiments(hypothesis_id=h_id)  # type: ignore
        else:
            exps = []
    except Exception:
        exps = []

    try:
        traces = store.list_traces() if hasattr(store, "list_traces") else []
    except Exception:
        traces = []

    from .gates import check_g1, check_g2, check_g3

    # G1: seed variance — at least three distinct registered run seeds.
    g1 = check_g1(evs, h, experiments=exps, traces=traces)
    gates["G1"] = g1
    if not g1:
        violations.append("G1: insufficient distinct experiment seeds (need >=3)")

    # G2: a hash-bound held-out split registered before the quantitative result.
    g2 = check_g2(evs, h, experiments=exps, traces=traces)
    gates["G2"] = g2
    if not g2:
        violations.append("G2: missing or late hash-bound held-out experiment")

    # G3: hash-bound preregistration or an explicit prediction before results.
    g3 = check_g3(evs, h, experiments=exps, traces=traces)
    gates["G3"] = g3
    if not g3:
        violations.append("G3: no valid preregistration or pre-result prediction")

    # citation + artifact hash per evidence
    for e in evs:
        cit = getattr(e, "citation_or_path", "") or ""
        ah = getattr(e, "artifact_hash", None)
        evid = getattr(e, "id", "?")
        if cit and not _citation_resolves(cit):
            violations.append(f"citation unresolved: {evid} -> {cit}")
        elif not cit:
            violations.append(f"citation missing: {evid}")
        if not _hash_matches(cit, ah):
            violations.append(f"artifact_hash mismatch: {evid}")

    passed = len(violations) == 0
    return {"passed": passed, "violations": violations, "gates": gates}


def posiwid_report(store: Any) -> Dict[str, Any]:
    """POSIWID: integrity_gap = violated_confirmed / total_confirmed."""
    hyps = store.list_hypotheses() if hasattr(store, "list_hypotheses") else []
    status_distribution: Dict[str, int] = {}
    total_confirmed = 0
    violated_confirmed = 0
    for h in hyps:
        st = getattr(getattr(h, "status", ""), "value", str(getattr(h, "status", ""))) or "UNKNOWN"
        status_distribution[st] = status_distribution.get(st, 0) + 1
        is_confirmed = st == "CONFIRMED"
        if is_confirmed:
            total_confirmed += 1
            audit = audit_hypothesis(getattr(h, "id", ""), store)
            if not audit["passed"]:
                violated_confirmed += 1
    integrity_gap = (violated_confirmed / total_confirmed) if total_confirmed else 0.0
    return {
        "integrity_gap": float(integrity_gap),
        "violated_confirmed": violated_confirmed,
        "total_confirmed": total_confirmed,
        "status_distribution": status_distribution,
        "total_hypotheses": len(hyps),
    }
