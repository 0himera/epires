"""Auxiliary noise attribution vs uncalibrated cascading invalidation."""

from typing import Any, Dict
from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode

DESCRIPTION = (
    "Chain H1 -> H2 -> H3. An anomaly occurs on H1 on a single seed run. "
    "Suspect auxiliary assumption AUX_EVAL_NOISE is present. "
    "Correct: attribute anomaly to AUX_EVAL_NOISE (H1 BLOCKED, no false cascade). "
    "Wrong: uncalibrated direct falsification (cascades to falsely block H2 and H3)."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Root feature transform",
            a_priori_mechanism="normalizes variance across domains",
            falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
            created_at=T0,
        )
    )
    store.register_hypothesis(
        HypothesisNode(
            id="H2",
            title="Downstream classifier",
            a_priori_mechanism="uses normalized inputs from H1",
            falsification_criteria="delta < 0",
            parent_ids=["H1"],
            target_evidence_level=EvidenceLevel.E3,
            created_at=T0,
        )
    )
    store.register_hypothesis(
        HypothesisNode(
            id="H3",
            title="Downstream ensemble",
            a_priori_mechanism="aggregates predictions from H2",
            falsification_criteria="delta < 0",
            parent_ids=["H2"],
            target_evidence_level=EvidenceLevel.E3,
            created_at=T0,
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {
        "kind": "anomaly",
        "hypothesis": "H1",
        "finding": "negative delta on single seed run",
        "suspects": ["AUX_EVAL_NOISE"],
        "n_seeds": 1,
    }
    act = agent.respond(obs)
    assumptions = act.get("assumption_ids", []) if act.get("action") == "attribute" else []

    ev = EvidenceClaim(
        id="anom_noise",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E2,
        claim="negative delta on single seed run",
        falsification_triggered=True,
        assumption_ids=assumptions,
        timestamp=T1,
    )
    _, blocked = store.log_evidence(ev)

    h1 = store.get_hypothesis("H1")
    h2 = store.get_hypothesis("H2")
    h3 = store.get_hypothesis("H3")

    return {
        "h1_status": h1.status.value if h1 else "UNKNOWN",
        "h2_status": h2.status.value if h2 else "UNKNOWN",
        "h3_status": h3.status.value if h3 else "UNKNOWN",
        "downstream_blocked": sorted(blocked),
        "attributed": bool(assumptions),
    }


def success(result: Dict[str, Any]) -> bool:
    return not result.get("downstream_blocked") and result.get("attributed") is True
