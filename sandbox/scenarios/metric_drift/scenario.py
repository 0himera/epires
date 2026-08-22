"""Two time windows disagree: +3pp then -4pp. Correct: discuss (or attribute) — confirm neither side; traps: averaging into a confirm, or falsifying on one bad window."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, HypothesisStatus

DESCRIPTION = (
    "H1: model is stable over time. Window 1 shows +3pp, window 2 shows -4pp. The two results conflict; "
    "correct action is discuss (confirm neither side) or attribute the discrepancy. Averaging by hand "
    "into a confirm, or falsifying on the single bad window, are both traps."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"
T2 = "2026-03-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Model performance stable over time",
            a_priori_mechanism="m",
            falsification_criteria="sustained delta < 0 across windows",
            target_evidence_level=EvidenceLevel.E3,
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {"kind": "conflict", "window1": "+3pp", "window2": "-4pp"}
    act = agent.respond(obs)
    action = act.get("action")
    aids = [str(a) for a in act.get("assumption_ids", [])] if action == "attribute" else []
    store.log_evidence(
        EvidenceClaim(
            id="w1",
            hypothesis_id="H1",
            evidence_level=EvidenceLevel.E2,
            claim="+3pp in window 1",
            citation_or_path="http://lab/w1",
            timestamp=T1,
        )
    )
    store.log_evidence(
        EvidenceClaim(
            id="w2",
            hypothesis_id="H1",
            evidence_level=EvidenceLevel.E2,
            claim="-4pp in window 2",
            citation_or_path="http://lab/w2",
            assumption_ids=aids,
            timestamp=T2,
        )
    )
    if action == "confirm":
        store.update_hypothesis("H1", status=HypothesisStatus.CONFIRMED)
    elif action == "falsify":
        store.log_evidence(
            EvidenceClaim(
                id="fals1",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E2,
                claim="window 2 regressed, killed H1 on a single window",
                citation_or_path="http://lab/fals1",
                falsification_triggered=True,
                timestamp=T2,
            )
        )
        store.update_hypothesis("H1", status=HypothesisStatus.FALSIFIED)
    h = store.get_hypothesis("H1")
    return {"action_taken": action, "status": h.status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["action_taken"] in ("discuss", "attribute") and result["status"] not in ("CONFIRMED", "FALSIFIED")
