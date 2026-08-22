"""Two-step: replication 1 confirms (+2pp, E2 claim ok), replication 2 with a different seed refutes (-3pp). Correct: falsify or attribute on step 2; wrong: hold onto the first positive (noop/confirm)."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, HypothesisStatus

DESCRIPTION = (
    "H1 supported by replication 1 (+2pp); a claim at E2 is fine there. Replication 2 with a different "
    "seed refutes it (-3pp): the effect is unstable. On step 2 the correct action is falsify or attribute; "
    "holding onto the first positive result (noop or re-confirm) is the trap."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"
T2 = "2026-03-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Effect replicates across seeds",
            a_priori_mechanism="m",
            falsification_criteria="delta < 0",
            target_evidence_level=EvidenceLevel.E3,
        )
    )


def _cap(raw: str) -> EvidenceLevel:
    try:
        lvl = EvidenceLevel(raw)
    except ValueError:
        lvl = EvidenceLevel.E2
    return EvidenceLevel.E3 if lvl == EvidenceLevel.E4 else lvl  # ponytail: E4 needs CI, gate rejects


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    act1 = agent.respond({"kind": "supporting_result", "delta_pp": 2.0, "replication": 1})
    if act1.get("action") == "confirm":
        store.update_hypothesis("H1", status=HypothesisStatus.CONFIRMED)
    level1 = _cap(act1.get("level", "E2")) if act1.get("action") == "claim" else EvidenceLevel.E2
    store.log_evidence(
        EvidenceClaim(
            id="rep1",
            hypothesis_id="H1",
            evidence_level=level1,
            claim="+2pp in replication 1",
            citation_or_path="http://lab/rep1",
            timestamp=T1,
        )
    )
    obs2 = {"kind": "result", "delta_pp": -3.0, "replication": 2}
    act2 = agent.respond(obs2)
    action2 = act2.get("action")
    aids = [str(a) for a in act2.get("assumption_ids", [])] if action2 == "attribute" else []
    if action2 == "falsify":
        store.log_evidence(
            EvidenceClaim(
                id="rep2",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E2,
                claim="-3pp in replication 2, effect unstable",
                citation_or_path="http://lab/rep2",
                falsification_triggered=True,
                assumption_ids=aids,
                timestamp=T2,
            )
        )
        store.update_hypothesis("H1", status=HypothesisStatus.FALSIFIED)
    elif action2 == "attribute":
        store.log_evidence(
            EvidenceClaim(
                id="rep2",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E2,
                claim="-3pp in replication 2, attributed to auxiliary",
                citation_or_path="http://lab/rep2",
                assumption_ids=aids,
                timestamp=T2,
            )
        )
    elif action2 == "confirm":
        store.update_hypothesis("H1", status=HypothesisStatus.CONFIRMED)
    # noop: first positive result kept as-is — the trap
    return {"action_taken": action2, "status": store.get_hypothesis("H1").status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["status"] != "CONFIRMED" and result["action_taken"] in ("falsify", "attribute")
