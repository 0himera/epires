"""Feature filter reported as 3/3 successes — but the store shows 20 hypotheses, 17 filtered out. Correct: verify_level (survivor bias); wrong: claim/confirm on 3/3."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, HypothesisStatus

DESCRIPTION = (
    "H1: feature filter improves signal. The report claims 'filter works, 3/3 successes' — but the ledger "
    "holds 20 hypotheses that passed through the filter: only 3 survived with positive results, 17 were "
    "filtered out. With the full survivor base visible, verify_level is correct; claiming on 3/3 is a trap."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"

SURVIVORS = ["H01", "H02", "H03"]


def _seed(store: Any) -> None:
    for i in range(1, 21):
        hid = f"H{i:02d}"
        store.register_hypothesis(
            HypothesisNode(
                id=hid, title=f"Filtered-feature candidate {hid}", a_priori_mechanism="m",
                falsification_criteria="delta < 0", target_evidence_level=EvidenceLevel.E3,
            )
        )
        if hid in SURVIVORS:
            store.log_evidence(
                EvidenceClaim(id=f"sup_{hid}", hypothesis_id=hid, evidence_level=EvidenceLevel.E2,
                              claim="positive after filter", citation_or_path=f"http://lab/{hid}", timestamp=T0)
            )
        else:
            status = [HypothesisStatus.FALSIFIED, HypothesisStatus.REFINED, HypothesisStatus.BLOCKED][i % 3]
            store.update_hypothesis(hid, status=status)
    store.register_hypothesis(
        HypothesisNode(
            id="H1", title="Feature filter improves signal", a_priori_mechanism="m",
            falsification_criteria="no signal gain", target_evidence_level=EvidenceLevel.E3,
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {"kind": "claim", "claim": "filter works, 3/3 successes", "trials_available": 20}
    act = agent.respond(obs)
    action = act.get("action")
    if action in ("verify_level", "attribute"):
        level = EvidenceLevel.E1
    elif action == "claim":
        raw = str(act.get("level", "E3"))
        level = EvidenceLevel.E4 if raw == "E4" else (EvidenceLevel(raw) if raw in ("E0", "E1", "E2", "E3", "E5") else EvidenceLevel.E3)
    else:
        # naive path: accept 3/3 at face value
        level = EvidenceLevel.E3
    store.log_evidence(
        EvidenceClaim(
            id="res1", hypothesis_id="H1", evidence_level=level, claim="filter works, 3/3 survivors positive",
            citation_or_path="http://lab/res1", timestamp=T1,
        )
    )
    h = store.get_hypothesis("H1")
    return {"action_taken": action, "final_level": h.current_evidence_level.value, "status": h.status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["final_level"] <= "E1" and result["status"] != "CONFIRMED"
