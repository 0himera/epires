from __future__ import annotations

import pytest

from sandbox.perf_ab.analyze import analyze_records


def _record(pair: str, condition: str, score: float, *, status: str = "completed"):
    return {
        "pair_id": pair,
        "task_id": "task",
        "model": "provider/model",
        "condition": condition,
        "status": status,
        "grader": {
            "result": {
                "status": "ok",
                "correctness": {"passed": True},
                "primary_score": score,
            }
        },
    }


def test_analysis_pairs_arms_and_uses_ratio_of_hidden_scores():
    report = analyze_records(
        [
            _record("p1", "bare", 2.0),
            _record("p1", "epires", 3.0),
            _record("p2", "bare", 4.0),
            _record("p2", "epires", 2.0),
            _record("p3", "bare", 1.0),
            _record("p3", "epires", 1.0),
        ]
    )

    summary = report["summary"]
    assert summary["valid_pairs"] == 3
    assert summary["interpretation"] == "pilot_estimate"
    assert (summary["treatment_wins"], summary["ties"], summary["control_wins"]) == (1, 1, 1)
    assert summary["geomean_treatment_over_control"] == pytest.approx((1.5 * 0.5) ** (1 / 3))


def test_analysis_excludes_incomplete_or_failed_pairs_without_imputation():
    report = analyze_records(
        [
            _record("valid", "bare", 1.0),
            _record("valid", "epires", 1.1),
            _record("missing", "bare", 1.0),
            _record("failed", "bare", 1.0),
            _record("failed", "epires", 2.0, status="agent_timeout"),
        ]
    )

    assert report["summary"]["valid_pairs"] == 1
    assert report["summary"]["interpretation"] == "smoke_only"
    assert report["excluded_pairs"] == {"invalid_or_failed_arm": 1, "missing_arm": 1}


def test_analysis_supports_named_component_ablation_conditions():
    report = analyze_records(
        [
            _record("p1", "epires", 1.0),
            _record("p1", "epires_direct", 2.0),
        ],
        control_condition="epires",
        treatment_condition="epires_direct",
    )

    assert report["control_condition"] == "epires"
    assert report["treatment_condition"] == "epires_direct"
    assert report["pairs"][0]["treatment_over_control"] == 2.0
