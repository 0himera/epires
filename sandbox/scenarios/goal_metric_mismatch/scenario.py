"""Primary metric regressed (+18% energy cost) while a secondary metric improved. Correct: falsify; wrong: claim/confirm."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode

DESCRIPTION = (
    "H1: method X reduces energy cost. Result: primary metric energy_cost regressed +18%, "
    "while secondary accuracy improved +0.5pp. The goal metric regressed — the trap is the shiny secondary."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Method X reduces energy cost",
            a_priori_mechanism="m",
            falsification_criteria="energy_cost increase > 5%",
            target_evidence_level=EvidenceLevel.E3,
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {
        "kind": "result",
        "primary_metric": {"energy_cost": "+18%"},
        "secondary_metric": {"accuracy": "+0.5pp"},
    }
    act = agent.respond(obs)
    if act.get("action") == "falsify":
        store.log_evidence(
            EvidenceClaim(
                id="res1",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E2,
                claim="primary metric regressed: energy_cost +18% (accuracy gain is out of scope)",
                citation_or_path="http://lab/res1",
                falsification_triggered=True,
                timestamp=T1,
            )
        )
    else:
        # naive path: cherry-pick the positive secondary metric
        store.log_evidence(
            EvidenceClaim(
                id="res1",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E2,
                claim="accuracy +0.5pp, looks good",
                citation_or_path="http://lab/res1",
                timestamp=T1,
            )
        )
    return {"status": store.get_hypothesis("H1").status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["status"] == "FALSIFIED"
