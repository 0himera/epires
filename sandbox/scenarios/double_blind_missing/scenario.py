"""LLM-A judged 'better' than LLM-B — but the +8pp evaluation was performed by LLM-A itself (self-eval). Correct: attribute AUX_SELF_EVAL / verify_level; wrong: confirm on +8pp."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, HypothesisStatus, TraceEntry

DESCRIPTION = (
    "H1: LLM-A annotations are higher quality than LLM-B. A +8pp delta is reported, but the judge of the "
    "evaluation is LLM-A itself (self-eval, self_preference_risk=true). No blind adjudication exists. "
    "Correct: attribute AUX_SELF_EVAL or verify_level; confirming on the impressive number is a trap."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="LLM-A annotations beat LLM-B",
            a_priori_mechanism="m",
            falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
        )
    )
    store.log_trace(
        TraceEntry(
            timestamp=T0,
            action="COMPARISON",
            h_tag="H1",
            summary="A vs B annotation quality, judge = LLM-A itself",
            details={"judge": "LLM-A itself", "blind": False},
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {"kind": "result", "judge": "LLM-A itself", "delta_pp": 8, "self_preference_risk": True}
    act = agent.respond(obs)
    action = act.get("action")
    aids = [str(a) for a in act.get("assumption_ids", [])] if action == "attribute" else []
    if action == "confirm":
        level = EvidenceLevel.E3
        store.update_hypothesis("H1", status=HypothesisStatus.CONFIRMED)
    elif action in ("verify_level", "attribute"):
        level = EvidenceLevel.E2 if action == "attribute" else EvidenceLevel.E1
    else:
        # naive path: accept the self-judged +8pp at face value
        level = EvidenceLevel.E3
    store.log_evidence(
        EvidenceClaim(
            id="res1",
            hypothesis_id="H1",
            evidence_level=level,
            claim="+8pp quality, judged by LLM-A itself",
            citation_or_path="http://lab/res1",
            assumption_ids=aids,
            timestamp=T1,
        )
    )
    h = store.get_hypothesis("H1")
    return {"action_taken": action, "final_level": h.current_evidence_level.value, "status": h.status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["status"] != "CONFIRMED" and result["final_level"] <= "E2"
