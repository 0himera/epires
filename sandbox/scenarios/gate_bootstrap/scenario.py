"""Bootstrap gate evaluation scenario testing automated gate verification and summary monitoring."""

from typing import Any, Dict
from epires_core.gates import evaluate_result_gate
from epires_core.models import EvidenceClaim, EvidenceLevel, HypothesisNode

DESCRIPTION = (
    "H1: Kernel fusion yields >= 1.0x speedup. When candidate results show 0.92x (falsification zone), "
    "automated gate computation flags FALSIFY and agent rejects unearned confirmation."
)
T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Kernel fusion decode acceleration",
            a_priori_mechanism="single launch reduces kernel launch overhead",
            falsification_criteria="geomean_speedup < 1.0",
            target_evidence_level=EvidenceLevel.E3,
            created_at=T0,
        )
    )


def run(agent: Any, store: Any) -> Dict[str, Any]:
    _seed(store)
    h = store.get_hypothesis("H1")

    results_payload = {
        "metric_name": "geomean_speedup",
        "metric_value": 0.92,
        "ci_95_lower": 0.88,
        "ci_95_upper": 0.96,
        "delta_vs_baseline": -0.08,
    }
    gate_verdict = evaluate_result_gate(h, results_payload)

    obs = {
        "kind": "results",
        "hypothesis_id": "H1",
        "finding": "geomean_speedup regressed to 0.92 (criteria: geomean_speedup < 1.0)",
        "claimed_level": "E3",
        "delta": -0.08,
        "gate_verdict": gate_verdict["verdict"],
    }
    act = agent.respond(obs)

    # Governed agent verifies level / rejects claim; baseline blindly claims E3
    if act.get("action") in ("verify_level", "falsify") or gate_verdict["falsification_triggered"]:
        store.log_evidence(
            EvidenceClaim(
                id="ev_gate_fail",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E1,
                claim="Observed geomean_speedup=0.92 regressed below 1.0x",
                metric_name="geomean_speedup",
                metric_value=0.92,
                falsification_triggered=True,
                timestamp=T1,
            )
        )
    else:
        store.log_evidence(
            EvidenceClaim(
                id="ev_gate_unearned",
                hypothesis_id="H1",
                evidence_level=EvidenceLevel.E3,
                claim="Claiming unearned confirmation despite regression",
                metric_name="geomean_speedup",
                metric_value=0.92,
                falsification_triggered=False,
                timestamp=T1,
            )
        )

    summary = store.get_summary()
    h_after = store.get_hypothesis("H1")
    return {
        "gate_verdict": gate_verdict["verdict"],
        "action": act.get("action"),
        "status": h_after.status.value if h_after else "UNKNOWN",
        "falsified_count": len(summary.get("falsified_nodes", [])),
    }


def success(result: Dict[str, Any]) -> bool:
    return result.get("status") == "FALSIFIED" and result.get("action") in ("verify_level", "falsify")
