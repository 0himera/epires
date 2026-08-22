"""Single-seed result inside known noise band. Correct: attribute to eval noise or verify level; wrong: claim E3+."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode

DESCRIPTION = (
    "H1 claims variant B beats baseline. Calibration shows seed-to-seed dispersion sigma=2pp. "
    "A single-seed result of +3.1pp arrives — within one sigma of zero."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H_AUX", title="Eval noise calibration", a_priori_mechanism="m", falsification_criteria="sigma > 5pp"
        )
    )
    store.log_evidence(
        EvidenceClaim(
            id="cal1",
            hypothesis_id="H_AUX",
            evidence_level=EvidenceLevel.E2,
            claim="seed dispersion measured: sigma=2pp over 20 reruns",
            citation_or_path="http://lab/cal1",
            assumption_ids=["AUX_EVAL_NOISE"],
            timestamp=T0,
        )
    )
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Variant B beats baseline",
            a_priori_mechanism="m",
            falsification_criteria="delta < -2pp",
            target_evidence_level=EvidenceLevel.E3,
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
    obs = {"kind": "result", "delta_pp": 3.1, "n_seeds": 1}
    act = agent.respond(obs)
    if act.get("action") in ("attribute", "verify_level"):
        level, aids = EvidenceLevel.E1, [str(a) for a in act.get("assumption_ids", [])]
    elif act.get("action") == "claim":
        level, aids = _cap(act.get("level", "E3")), []
    else:
        level, aids = EvidenceLevel.E2, []
    store.log_evidence(
        EvidenceClaim(
            id="res1",
            hypothesis_id="H1",
            evidence_level=level,
            claim="+3.1pp on a single seed (sigma=2pp)",
            citation_or_path="http://lab/res1",
            assumption_ids=aids,
            timestamp=T1,
        )
    )
    return {"final_level": store.get_hypothesis("H1").current_evidence_level.value}


def success(result: Dict[str, Any]) -> bool:
    return result["final_level"] <= "E2"
