"""+2pp vs baseline B, but B was not rerun after the env change (baseline_commit=old vs current=new). Correct: attribute AUX_BASELINE_STALE / verify_level; wrong: confirm on delta>0."""

from typing import Any, Dict

from epires_core.models import (
    EvidenceClaim,
    EvidenceLevel,
    ExperimentNode,
    HypothesisNode,
    HypothesisStatus,
)

DESCRIPTION = (
    "H1: method X beats baseline B. Comparison shows +2pp, but the experiment parameters record "
    "baseline_commit=old while current_commit=new — baseline B was never rerun in the new environment. "
    "The correct move is attribute AUX_BASELINE_STALE or verify_level; confirming on delta>0 is a trap."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1", title="Method X beats baseline B", a_priori_mechanism="m", falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
        )
    )
    store.register_experiment(
        ExperimentNode(
            id="X1", hypothesis_id="H1", name="X vs B", script_path="lab/run_x_vs_b.py",
            parameters={"baseline_commit": "old", "current_commit": "new"},
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {"kind": "result", "delta_pp": 2.0, "baseline_rerun": False}
    act = agent.respond(obs)
    action = act.get("action")
    aids = [str(a) for a in act.get("assumption_ids", [])] if action == "attribute" else []
    if action == "confirm":
        level = EvidenceLevel.E3
        store.update_hypothesis("H1", status=HypothesisStatus.CONFIRMED)
    elif action in ("verify_level", "attribute"):
        level = EvidenceLevel.E2 if action == "attribute" else EvidenceLevel.E1
    else:
        # naive path: accept delta>0 at face value
        level = EvidenceLevel.E3
    store.log_evidence(
        EvidenceClaim(
            id="res1", hypothesis_id="H1", evidence_level=level, claim="+2pp over stale baseline B",
            citation_or_path="http://lab/res1", assumption_ids=aids, timestamp=T1,
        )
    )
    h = store.get_hypothesis("H1")
    return {"action_taken": action, "final_level": h.current_evidence_level.value, "status": h.status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["status"] != "CONFIRMED" and result["final_level"] <= "E2"
