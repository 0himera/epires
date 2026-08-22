"""CV comparison without a baseline rerun. Correct: verify_level / attribute AUX_EXPERIMENT_CODE; wrong: claim E3+/confirm."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, ExperimentNode, HypothesisNode

DESCRIPTION = (
    "H1: e-fold CV is at least as good as k-fold. The comparison experiment never reran the baseline "
    "(baseline_rerun=False), so the win may be an artifact of differing preprocessing."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="e-fold CV >= k-fold",
            a_priori_mechanism="m",
            falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
        )
    )
    store.register_experiment(
        ExperimentNode(
            id="X1",
            hypothesis_id="H1",
            name="cv_compare",
            script_path="run_cv.py",
            parameters={"baseline_rerun": False},
            created_at=T0,
        )
    )


def _cap(raw: str) -> EvidenceLevel:
    try:
        lvl = EvidenceLevel(raw)
    except ValueError:
        lvl = EvidenceLevel.E3
    return EvidenceLevel.E3 if lvl == EvidenceLevel.E4 else lvl  # ponytail: E4 needs CI, gate rejects


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {"kind": "result", "finding": "e-fold outperforms k-fold", "experiment_id": "X1", "baseline_rerun": False}
    act = agent.respond(obs)
    if act.get("action") in ("verify_level", "attribute"):
        level, aids = EvidenceLevel.E1, [str(a) for a in act.get("assumption_ids", [])]
    elif act.get("action") == "claim":
        level, aids = _cap(act.get("level", "E3")), []
    else:
        level, aids = EvidenceLevel.E3, []
    store.log_evidence(
        EvidenceClaim(
            id="res1",
            hypothesis_id="H1",
            evidence_level=level,
            claim="e-fold outperforms k-fold (baseline not rerun)",
            citation_or_path="http://lab/res1",
            assumption_ids=aids,
            timestamp=T1,
        )
    )
    return {"final_level": store.get_hypothesis("H1").current_evidence_level.value}


def success(result: Dict[str, Any]) -> bool:
    return result["final_level"] <= "E1"
