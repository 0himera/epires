"""Automated Gates & Criteria Verifier for Experiment Artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from .models import EvidenceClaim, EvidenceLevel, SourceConfidence, HypothesisStatus
from .criteria import evaluate_falsification_condition, parse_falsification_criteria


def verify_experiment_artifact(
    artifact_path: str | Path,
    store: Any,
    hypothesis_id: Optional[str] = None,
    apply: bool = False,
    evidence_level: str = "E3",
    source_confidence: str = "V",
) -> Dict[str, Any]:
    """Evaluates an experiment JSON artifact against falsification criteria and G0-G8 gates.

    If apply=True, records the verified EvidenceClaim into the database.
    """
    path = Path(artifact_path)
    if not path.exists():
        raise FileNotFoundError(f"Artifact file '{path}' not found.")

    raw = json.loads(path.read_text(encoding="utf-8"))
    hid = hypothesis_id or raw.get("hypothesis_id")
    if not hid:
        raise ValueError("Hypothesis ID must be specified in artifact JSON or passed via arguments.")

    h = store.get_hypothesis(hid)
    if not h:
        raise ValueError(f"Hypothesis '{hid}' not found in research graph.")

    delta = raw.get("delta_vs_baseline")
    ci_lower = raw.get("ci_95_lower")
    ci_upper = raw.get("ci_95_upper")
    metric_name = raw.get("metric_name", getattr(h, "primary_metric", "Metric"))

    # Gate G0: Schema & Finite Metrics
    g0_pass = delta is not None and (ci_lower is None or (ci_lower is not None and ci_upper is not None))

    # Gate G1: Finite and Non-NaN metrics
    g1_pass = True
    for v in (delta, ci_lower, ci_upper):
        if v is not None:
            try:
                fv = float(v)
                if fv != fv or fv == float("inf") or fv == float("-inf"):
                    g1_pass = False
            except Exception:
                g1_pass = False

    # Falsification criteria evaluation
    criteria_str = getattr(h, "falsification_criteria", "")
    falsification_triggered = False
    falsification_reason = ""

    if criteria_str:
        conditions = parse_falsification_criteria(criteria_str)
        for cond in conditions:
            eval_res = evaluate_falsification_condition(
                cond=cond,
                metric_name=metric_name,
                delta_vs_baseline=float(delta) if delta is not None else None,
                ci_lower=float(ci_lower) if ci_lower is not None else None,
                ci_upper=float(ci_upper) if ci_upper is not None else None,
            )
            if eval_res is True:
                falsification_triggered = True
                falsification_reason = f"Triggered criteria clause: '{cond.raw_text}'"
                break

    # Gate G4: Non-negative CI bounds if delta is supposed to be positive
    g4_pass = True
    if not falsification_triggered and ci_lower is not None:
        if delta is not None and delta > 0 and ci_lower <= 0:
            # CI crosses zero - inconclusive evidence
            g4_pass = False

    passed_all_gates = g0_pass and g1_pass and not falsification_triggered and g4_pass

    verdict_status = (
        HypothesisStatus.CONFIRMED.value
        if passed_all_gates
        else HypothesisStatus.FALSIFIED.value
        if falsification_triggered
        else HypothesisStatus.IN_PROGRESS.value
    )

    result: Dict[str, Any] = {
        "hypothesis_id": hid,
        "artifact_file": str(path),
        "passed_all_gates": passed_all_gates,
        "falsification_triggered": falsification_triggered,
        "falsification_reason": falsification_reason,
        "verdict_status": verdict_status,
        "gates": {
            "G0_schema": g0_pass,
            "G1_finite": g1_pass,
            "G4_ci_separated": g4_pass,
        },
        "metrics": {
            "metric_name": metric_name,
            "delta_vs_baseline": delta,
            "ci_95_lower": ci_lower,
            "ci_95_upper": ci_upper,
        },
    }

    if apply:
        claim_msg = f"Automated verification of {path.name}: delta={delta:+g}"
        if ci_lower is not None and ci_upper is not None:
            claim_msg += f" (95% CI: [{ci_lower:.6f}, {ci_upper:.6f}])"

        ev = EvidenceClaim(
            hypothesis_id=hid,
            evidence_level=EvidenceLevel(evidence_level),
            source_confidence=SourceConfidence(source_confidence),
            claim=claim_msg,
            metric_name=metric_name,
            delta_vs_baseline=delta,
            ci_95_lower=ci_lower,
            ci_95_upper=ci_upper,
            falsification_triggered=falsification_triggered,
            citation_or_path=str(path),
        )
        logged_ev, blocked_children = store.log_evidence(ev)
        result["applied"] = True
        result["evidence_id"] = logged_ev.id
        result["blocked_children"] = blocked_children

    return result
