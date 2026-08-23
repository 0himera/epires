"""Tests for Agent Ergonomics & Context Hygiene features.

Covers:
1. Flexible Pydantic input validation (tags, parent_ids, entities as strings or lists).
2. EvidenceClaim auto-fallback for missing claim string.
3. Lightweight aggregated summary (epires_summary / store.get_summary).
4. Automated bootstrap gate evaluation (epires_compute_gate / evaluate_result_gate).
5. Subtree extraction and status filtering in export_mermaid_dag.
6. Compact mode in query_graph.
"""

from __future__ import annotations

import json
from pathlib import Path

from epires_core import (
    EpiresStore,
    EvidenceClaim,
    EvidenceLevel,
    HypothesisNode,
    HypothesisStatus,
)
from epires_core.gates import evaluate_result_gate
from server.mcp_server import create_mcp_server


def test_flexible_hypothesis_and_evidence_validation():
    """HypothesisNode and EvidenceClaim accept strings, lists, or dicts without validation errors."""
    # 1. String tags, parent_ids, and entities
    h = HypothesisNode(
        id="H_FLEX",
        title="Flexible Model",
        a_priori_mechanism="math",
        falsification_criteria="loss > 0.10",
        parent_ids="H1, H2",
        tags="vsa, hypervector, cuda",
        entities="Model:CatBoost, Feature:Wavelet",
    )
    assert h.parent_ids == ["H1", "H2"]
    assert h.tags == ["vsa", "hypervector", "cuda"]
    assert len(h.entities) == 2
    assert h.entities[0].type == "Model" and h.entities[0].value == "CatBoost"
    assert h.entities[1].type == "Feature" and h.entities[1].value == "Wavelet"

    # 2. EvidenceClaim auto-fallback for missing claim
    ev_auto = EvidenceClaim(
        hypothesis_id="H_FLEX",
        evidence_level=EvidenceLevel.E2,
        metric_name="accuracy",
        metric_value=0.92,
        delta_vs_baseline=0.05,
        assumption_ids="AUX_SEED, AUX_TOOL",
    )
    assert ev_auto.claim == "Observed accuracy=0.92 (delta=0.05)"
    assert ev_auto.assumption_ids == ["AUX_SEED", "AUX_TOOL"]

    # 3. EvidenceClaim without metrics gets default claim text
    ev_default = EvidenceClaim(
        hypothesis_id="H_FLEX",
    )
    assert ev_default.claim == "Evidence record for H_FLEX"


def test_store_get_summary(tmp_path: Path):
    """get_summary provides lightweight status overview without loading full mechanisms."""
    store = EpiresStore(db_path=tmp_path / "summary.db", trace_md_path=None)

    h1 = HypothesisNode(
        id="H1",
        title="Root",
        a_priori_mechanism="m",
        falsification_criteria="c",
        status=HypothesisStatus.CONFIRMED,
        current_evidence_level=EvidenceLevel.E3,
    )
    h2 = HypothesisNode(
        id="H2",
        title="Active Child",
        a_priori_mechanism="m",
        falsification_criteria="c",
        parent_ids=["H1"],
        status=HypothesisStatus.IN_PROGRESS,
        current_evidence_level=EvidenceLevel.E1,
    )
    h3 = HypothesisNode(
        id="H3",
        title="Blocked Child",
        a_priori_mechanism="m",
        falsification_criteria="c",
        parent_ids=["H1"],
        status=HypothesisStatus.BLOCKED,
        current_evidence_level=EvidenceLevel.E0,
    )
    store.register_hypothesis(h1)
    store.register_hypothesis(h2)
    store.register_hypothesis(h3)

    summary = store.get_summary()

    assert summary["total_hypotheses"] == 3
    assert summary["by_status"]["CONFIRMED"] == 1
    assert summary["by_status"]["IN_PROGRESS"] == 1
    assert summary["by_status"]["BLOCKED"] == 1
    assert summary["by_evidence_level"]["E3"] == 1
    assert summary["by_evidence_level"]["E1"] == 1
    assert len(summary["active_frontier"]) == 1
    assert summary["active_frontier"][0]["id"] == "H2"
    assert "H3" in summary["blocked_branches"]


def test_evaluate_result_gate_scenarios(tmp_path: Path):
    """evaluate_result_gate correctly evaluates pass, falsification, noise, and file paths."""
    h = HypothesisNode(
        id="H_TEST",
        title="Testing Criteria",
        a_priori_mechanism="math",
        falsification_criteria="loss > 0.10",
    )

    # 1. Clean PASS
    pass_res = evaluate_result_gate(
        h,
        {
            "metric_name": "loss",
            "metric_value": 0.05,
            "ci_95_lower": 0.03,
            "ci_95_upper": 0.08,
            "delta_vs_baseline": -0.04,
        },
    )
    assert pass_res["verdict"] == "PASS"
    assert pass_res["gate_passed"] is True
    assert pass_res["falsification_triggered"] is False
    assert pass_res["recommended_action"] == "CLAIM_CONFIRMATION"

    # 2. Direct FALSIFICATION
    fail_res = evaluate_result_gate(
        h,
        {
            "metric_name": "loss",
            "metric_value": 0.15,
        },
    )
    assert fail_res["verdict"] == "FALSIFY"
    assert fail_res["gate_passed"] is False
    assert fail_res["falsification_triggered"] is True

    # 3. INCONCLUSIVE_NOISE (CI overlaps the 0.10 threshold)
    noise_res = evaluate_result_gate(
        h,
        {
            "metric_name": "loss",
            "metric_value": 0.08,
            "ci_95_lower": 0.06,
            "ci_95_upper": 0.14,
        },
    )
    assert noise_res["verdict"] == "INCONCLUSIVE_NOISE"
    assert noise_res["gate_passed"] is False
    assert noise_res["recommended_action"] == "INCREASE_SEEDS_OR_DE_NOISE"

    # 4. From results.json on disk
    results_json_file = tmp_path / "run_metrics.json"
    results_json_file.write_text(
        json.dumps(
            {
                "metric_name": "loss",
                "metric_value": 0.04,
                "ci_95_lower": 0.02,
                "ci_95_upper": 0.06,
            }
        ),
        encoding="utf-8",
    )
    file_res = evaluate_result_gate(h, results_json_file)
    assert file_res["verdict"] == "PASS"
    assert file_res["gate_passed"] is True


def test_export_mermaid_dag_subtree_filtering(tmp_path: Path):
    """export_mermaid_dag supports root_id subtree extraction and depth limiting."""
    store = EpiresStore(db_path=tmp_path / "dag_filter.db", trace_md_path=None)

    # Subtree 1: A -> B -> C
    ha = HypothesisNode(id="HA", title="Alpha", a_priori_mechanism="m", falsification_criteria="c")
    hb = HypothesisNode(id="HB", title="Beta", a_priori_mechanism="m", falsification_criteria="c", parent_ids=["HA"])
    hc = HypothesisNode(id="HC", title="Gamma", a_priori_mechanism="m", falsification_criteria="c", parent_ids=["HB"])

    # Disconnected Subtree 2: X -> Y
    hx = HypothesisNode(id="HX", title="X", a_priori_mechanism="m", falsification_criteria="c")
    hy = HypothesisNode(id="HY", title="Y", a_priori_mechanism="m", falsification_criteria="c", parent_ids=["HX"])

    for h in (ha, hb, hc, hx, hy):
        store.register_hypothesis(h)

    # Subtree export centered on HB with depth=1
    mermaid_sub = store.export_mermaid_dag(root_id="HB", depth=1)
    assert "HB" in mermaid_sub
    assert "HA" in mermaid_sub
    assert "HC" in mermaid_sub
    assert "HX" not in mermaid_sub
    assert "HY" not in mermaid_sub


def test_mcp_tools_agent_ergonomics(tmp_path: Path):
    """FastMCP server exposes summary, compute_gate, compact query_graph, and flexible params."""
    db_file = str(tmp_path / "mcp_ergo.db")
    mcp = create_mcp_server(db_path=db_file)

    # 1. Register hypothesis with string tags and entities
    reg_tool = mcp._tool_manager.get_tool("epires_register_hypothesis")
    reg_res = reg_tool.fn(
        id="H_MCP",
        title="MCP Ergonomics Test",
        a_priori_mechanism="Theoretical foundation",
        falsification_criteria="acc < 0.85",
        parent_ids="H0",
        tags="mcp, fastmcp, test",
        entities="Tool:FastMCP, Feature:Summary",
    )
    assert "Successfully registered hypothesis 'H_MCP'" in reg_res

    # 2. Log evidence without explicit claim
    log_tool = mcp._tool_manager.get_tool("epires_log_evidence")
    log_res = log_tool.fn(
        hypothesis_id="H_MCP",
        metric_name="acc",
        metric_value=0.91,
        delta_vs_baseline=0.06,
        ci_95_lower=0.88,
        ci_95_upper=0.94,
    )
    assert "Evidence" in log_res

    # 3. Call epires_summary
    sum_tool = mcp._tool_manager.get_tool("epires_summary")
    sum_res = json.loads(sum_tool.fn())
    assert sum_res["total_hypotheses"] == 1
    assert sum_res["evidence_count"] == 1

    # 4. Call epires_compute_gate
    gate_tool = mcp._tool_manager.get_tool("epires_compute_gate")
    gate_res = json.loads(
        gate_tool.fn(
            hypothesis_id="H_MCP",
            metric_name="acc",
            metric_value=0.91,
            ci_95_lower=0.88,
            ci_95_upper=0.94,
        )
    )
    assert gate_res["verdict"] == "PASS"
    assert gate_res["gate_passed"] is True

    # 5. Call epires_query_graph in compact mode
    query_tool = mcp._tool_manager.get_tool("epires_query_graph")
    query_res = json.loads(query_tool.fn(compact=True))
    assert len(query_res) == 1
    assert "a_priori_mechanism" not in query_res[0]
    assert "title" in query_res[0]
    assert query_res[0]["tags"] == ["mcp", "fastmcp", "test"]
