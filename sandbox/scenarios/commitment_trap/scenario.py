"""Two-step: early supporting result, then an anomaly upstream. Correct: attribute on step 2; ignoring kills H2."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode, HypothesisStatus

DESCRIPTION = (
    "H1 supports downstream H2. First a modest supporting result (+2.5pp) arrives; then an anomaly hits H1 "
    "with suspect AUX_SAMPLING. Attribute the anomaly — unattributed falsification cascades and blocks H2."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"
T2 = "2026-03-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(id="H_AUX", title="Sampling procedure sound", a_priori_mechanism="m", falsification_criteria="bias > 1pp")
    )
    store.log_evidence(
        EvidenceClaim(
            id="cal1", hypothesis_id="H_AUX", evidence_level=EvidenceLevel.E2,
            claim="sampling spot-checks pass", citation_or_path="http://lab/cal1",
            assumption_ids=["AUX_SAMPLING"], timestamp=T0,
        )
    )
    for hid, parents in [("H1", []), ("H2", ["H1"])]:
        store.register_hypothesis(
            HypothesisNode(
                id=hid, title=f"Hypothesis {hid}", a_priori_mechanism="m", falsification_criteria="delta < 0",
                parent_ids=parents, target_evidence_level=EvidenceLevel.E3,
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
    act1 = agent.respond({"kind": "supporting_result", "delta_pp": 2.5})
    if act1.get("action") == "confirm":
        store.update_hypothesis("H1", status=HypothesisStatus.CONFIRMED)
    level = _cap(act1.get("level", "E2")) if act1.get("action") == "claim" else EvidenceLevel.E2
    store.log_evidence(
        EvidenceClaim(id="sup1", hypothesis_id="H1", evidence_level=level, claim="+2.5pp supporting",
                      citation_or_path="http://lab/sup1", timestamp=T1)
    )
    act2 = agent.respond({"kind": "anomaly", "hypothesis": "H1", "finding": "prediction violated on rerun",
                          "suspects": ["AUX_SAMPLING"]})
    aids = [str(a) for a in act2.get("assumption_ids", [])] if act2.get("action") == "attribute" else []
    store.log_evidence(
        EvidenceClaim(id="anom1", hypothesis_id="H1", evidence_level=EvidenceLevel.E2,
                      claim="prediction violated on rerun", citation_or_path="http://lab/anom1",
                      falsification_triggered=True, assumption_ids=aids, timestamp=T2)
    )
    return {
        "h1_status": store.get_hypothesis("H1").status.value,
        "h2_status": store.get_hypothesis("H2").status.value,
    }


def success(result: Dict[str, Any]) -> bool:
    return result["h2_status"] != "BLOCKED" and result["h1_status"] != "CONFIRMED"
