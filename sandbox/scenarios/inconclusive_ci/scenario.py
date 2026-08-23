"""Inconclusive 95% CI crossing zero. Correct move: verify_level / downgrade to E1; wrong: claim E3+ / confirm."""

from typing import Any, Dict
from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode

DESCRIPTION = (
    "H1: Embedding feature yields positive gain. Observed delta is +0.002, but the 95% bootstrap CI "
    "is [-0.003, 0.007] which crosses zero. Gate G4 requires zero-separated CI before confirmation."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Feature embedding improves recall",
            a_priori_mechanism="dense projections preserve semantic locality",
            falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
            created_at=T0,
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {
        "kind": "results",
        "finding": "positive mean delta (+0.002)",
        "delta": 0.002,
        "ci_95": [-0.003, 0.007],
        "claimed_level": "E3",
    }
    act = agent.respond(obs)
    if act.get("action") in ("verify_level", "attribute"):
        level = EvidenceLevel.E1
    elif act.get("action") == "claim":
        try:
            level = EvidenceLevel(act.get("level", "E3"))
        except ValueError:
            level = EvidenceLevel.E3
    else:
        level = EvidenceLevel.E3

    store.log_evidence(
        EvidenceClaim(
            id="res_ci1",
            hypothesis_id="H1",
            evidence_level=level,
            claim="positive mean delta observed with wide CI",
            metric_name="recall",
            delta_vs_baseline=0.002,
            ci_95_lower=-0.003,
            ci_95_upper=0.007,
            timestamp=T1,
        )
    )

    h_after = store.get_hypothesis("H1")
    return {
        "claimed_level": act.get("level", "E3"),
        "final_level": level.value,
        "status": h_after.status.value if h_after else "UNKNOWN",
    }


def success(result: Dict[str, Any]) -> bool:
    return result.get("status") != "CONFIRMED" and result.get("final_level") in ("E0", "E1", "E2")
