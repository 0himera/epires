"""Feature F: train_acc 0.99 vs holdout 0.54, derived from user_id. Correct: falsify on holdout; trap: trust train."""

from typing import Any, Dict

from epires_core.models import EvidenceClaim, EvidenceLevel, ExperimentNode, HypothesisNode

DESCRIPTION = (
    "H1: feature F is informative. Experiment metrics: train_acc=0.99 but holdout_acc=0.54 (chance level). "
    "F is derived from user_id — leakage. The trap is confirming on the inflated train score."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Feature F is informative",
            a_priori_mechanism="m",
            falsification_criteria="holdout ~ chance",
            target_evidence_level=EvidenceLevel.E3,
        )
    )
    store.register_experiment(
        ExperimentNode(
            id="X1",
            hypothesis_id="H1",
            name="feature_probe",
            script_path="probe.py",
            parameters={"feature_derived_from": "user_id"},
            metrics={"train_acc": 0.99, "holdout_acc": 0.54},
            created_at=T0,
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    obs = {
        "kind": "result",
        "train_acc": 0.99,
        "holdout_acc": 0.54,
        "provenance": {"feature_derived_from": "user_id"},
    }
    act = agent.respond(obs)
    if act.get("action") == "falsify":
        store.log_evidence(
            EvidenceClaim(
                id="res1",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E2,
                claim="holdout_acc=0.54 ~ chance; feature derived from user_id leaks targets",
                citation_or_path="http://lab/res1",
                metric_name="holdout_acc",
                metric_value=0.54,
                falsification_triggered=True,
                timestamp=T1,
            )
        )
    elif act.get("action") == "verify_level":
        store.log_evidence(
            EvidenceClaim(
                id="res1",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E1,
                claim="train/holdout gap unexplained",
                citation_or_path="http://lab/res1",
                timestamp=T1,
            )
        )
    else:
        # naive path: confirm on the inflated train score
        store.log_evidence(
            EvidenceClaim(
                id="res1",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E3,
                claim="train_acc=0.99, feature highly informative",
                citation_or_path="http://lab/res1",
                metric_name="train_acc",
                metric_value=0.99,
                timestamp=T1,
            )
        )
    return {"status": store.get_hypothesis("H1").status.value}


def success(result: Dict[str, Any]) -> bool:
    return result["status"] == "FALSIFIED"
