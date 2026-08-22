"""Single anomaly on H1 in a H1->H2->H3 chain. Correct move: blame the auxiliary assumption (tool X), no downstream cascade."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode

DESCRIPTION = (
    "A rerun violated the prediction of hypothesis H1, which H2 and H3 depend on. "
    "Candidate auxiliary assumption AUX_TOOL_X (measurement tool calibration) may be at fault."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H_AUX",
            title="Tool X calibration holds",
            a_priori_mechanism="tool X stays within tolerance across runs",
            falsification_criteria="drift > 0.1",
        )
    )
    store.log_evidence(
        EvidenceClaim(
            id="cal1",
            hypothesis_id="H_AUX",
            evidence_level=EvidenceLevel.E1,
            claim="tool X within tolerance in 5 spot checks",
            citation_or_path="http://lab/cal1",
            assumption_ids=["AUX_TOOL_X"],
            timestamp=T0,
        )
    )
    for hid, title, parents in [
        ("H1", "Pipeline output is correct", []),
        ("H2", "Downstream analysis A", ["H1"]),
        ("H3", "Downstream analysis B", ["H2"]),
    ]:
        store.register_hypothesis(
            HypothesisNode(
                id=hid,
                title=title,
                a_priori_mechanism="m",
                falsification_criteria="metric < 0.5",
                parent_ids=parents,
            )
        )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {
        "kind": "anomaly",
        "hypothesis": "H1",
        "finding": "prediction violated on rerun",
        "suspects": ["AUX_TOOL_X"],
    }
    act = agent.respond(obs)
    ev = EvidenceClaim(
        id="anom1",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E2,
        claim="prediction violated",
        citation_or_path="http://lab/anom1",
        falsification_triggered=True,
        assumption_ids=act.get("assumption_ids", []) if act.get("action") == "attribute" else [],
        timestamp=T1,
    )
    _, blocked = store.log_evidence(ev)
    return {"downstream_blocked": sorted(blocked)}


def success(result: Dict[str, Any]) -> bool:
    return not result.get("downstream_blocked")
