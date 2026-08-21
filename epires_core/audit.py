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
    if not artifact_hash:
        return True
    c = (citation or "").strip()
    if not c or _is_url_like(c):
        return True
    p = Path(c)
    if not p.is_file():
        return True  # skip if file absent — not a mismatch, just unresolved citation
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

    # G1: seed variance — ≥3 evidence claims
    g1 = len(evs) >= 3
    gates["G1"] = g1
    if not g1:
        violations.append(f"G1: insufficient evidence (need >=3, have {len(evs)})")

    # G2: held-out — ≥1 experiment registered
    g2 = len(exps) >= 1
    gates["G2"] = g2
    if not g2:
        violations.append(f"G2: missing experiment (need >=1, have {len(exps)})")

    # G3: prereg — hypothesis created before first evidence
    if evs and getattr(h, "created_at", ""):
        first_ts = evs[0].timestamp if hasattr(evs[0], "timestamp") else ""
        # ponytail: string compare of ISO timestamps, cheap and monotone
        g3 = h.created_at <= first_ts if first_ts else True
    else:
        g3 = True  # no evidence yet -> prereg trivially ok
    gates["G3"] = g3
    if not g3:
        violations.append("G3: hypothesis not preregistered (created_at after evidence)")

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
