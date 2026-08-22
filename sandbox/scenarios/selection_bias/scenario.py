"""Best-of-12 config sweep reported as a clean win. Correct: verify_level / attribute AUX_SELECTION_BIAS; wrong: claim E3+."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, TraceEntry

DESCRIPTION = (
    "H1 is supported by a sweep of 12 configurations where the best one (#7) is reported: +4pp on test. "
    "With 12 trials the max statistic is inflated — selection bias must be acknowledged."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Tuned config beats default",
            a_priori_mechanism="m",
            falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
        )
    )
    store.log_trace(
        TraceEntry(
            timestamp=T0,
            action="TRIAL_LOG",
            h_tag="H1",
            summary="swept 12 configs, selected #7 by test score",
            details={"configs": 12, "selection": "max(test_score)"},
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
    obs = {"kind": "claim", "claim": "config #7 best, +4pp on test", "trials_available": 12}
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
            claim="+4pp, best of 12 configs",
            citation_or_path="http://lab/res1",
            assumption_ids=aids,
            timestamp=T1,
        )
    )
    h = store.get_hypothesis("H1")
    return {"final_level": h.current_evidence_level.value, "status": h.status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["final_level"] <= "E1" and result["status"] != "CONFIRMED"
