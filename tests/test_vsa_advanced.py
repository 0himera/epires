"""Test suite for advanced VSA memory architectures:
1. Dual-Codebook 2-hop relational reasoning (VSAR-034).
2. Incremental online bundling without index rebuild (VSAR-029).
3. Hierarchical multi-agent sharding & dynamic load balancing (VSAR-032, VSAR-033).
4. Episodic context token compressor (VSAR-007).
5. MCP tools integration.
"""

from __future__ import annotations

import json
from pathlib import Path

from epires_core import (
    BipolarVSA,
    DualCodebookVSA,
    EpisodicVSACompressor,
    HierarchicalShardRouter,
)
from server.mcp_server import create_mcp_server


def test_dual_codebook_2hop_relational_reasoning():
    """DualCodebookVSA correctly unbinds 2-hop causal chains with intermediate cleanup."""
    vsa = DualCodebookVSA(dim=4096, seed=42)

    # Graph relations:
    # H1 -BLOCKS-> H2
    # H2 -GATED_BY-> H3
    # H4 -CONFLICTS_WITH-> H5
    triples = [
        ("H1", "BLOCKS", "H2"),
        ("H2", "GATED_BY", "H3"),
        ("H4", "CONFLICTS_WITH", "H5"),
    ]
    memory = vsa.bundle_triples(triples)
    all_entities = ["H1", "H2", "H3", "H4", "H5", "H6", "H7"]

    # 1. 1-hop query: H1 -BLOCKS-> ?
    hop1 = vsa.query_1hop(memory, head="H1", relation="BLOCKS", candidates=all_entities)
    assert hop1[0][0] == "H2"
    assert hop1[0][1] > 0.05

    # 2. 2-hop causal query: H1 -BLOCKS-> ?mid -GATED_BY-> ?target
    hop2 = vsa.query_2hop(
        memory,
        head="H1",
        relation_1="BLOCKS",
        relation_2="GATED_BY",
        all_entities=all_entities,
        top_k=3,
    )
    assert len(hop2) > 0
    assert hop2[0][0] == "H3"  # H1 -> H2 -> H3
    assert hop2[0][1] > 0.05


def test_incremental_superposition_bundling():
    """incremental_bundle appends new items in O(B*D) while preserving old item similarity."""
    vsa = BipolarVSA(dim=4096, seed=123)

    # Initial bundle of 10 items
    initial_items = [vsa.get_or_create_vector(f"item_{i}") for i in range(10)]
    bundle = vsa.bundle(initial_items)

    # Check similarity of an old item to initial bundle
    sim_old_before = vsa.cosine_similarity(initial_items[0], bundle)
    assert sim_old_before > 0.15

    # Incremental update: append 2 new items
    new_items = [vsa.get_or_create_vector("item_new_1"), vsa.get_or_create_vector("item_new_2")]
    updated_bundle = vsa.incremental_bundle(bundle, new_items, current_load=10)

    # Old item remains strongly retrievable
    sim_old_after = vsa.cosine_similarity(initial_items[0], updated_bundle)
    assert sim_old_after > 0.12

    # New item is now also similar
    sim_new = vsa.cosine_similarity(new_items[0], updated_bundle)
    assert sim_new > 0.05


def test_hierarchical_multiagent_sharding_and_zero_contamination():
    """HierarchicalShardRouter guarantees zero cross-agent context contamination."""
    router = HierarchicalShardRouter(dim=4096, total_shards=16, seed=42)

    # Insert items under different agent roles
    v1 = router.vsa.get_or_create_vector("code_patch_v1")
    v2 = router.vsa.get_or_create_vector("audit_report_v1")
    v3 = router.vsa.get_or_create_vector("lead_pi_strategy")

    router.insert("patch_1", v1, agent_role="Coder", metadata={"type": "code"})
    router.insert("audit_1", v2, agent_role="Auditor", metadata={"type": "audit"})
    router.insert("strat_1", v3, agent_role="Lead-PI", metadata={"type": "strategy"})

    # Query as Coder: MUST ONLY return Coder items, never Auditor or Lead-PI
    coder_results = router.query(v1, agent_role="Coder", top_k=5)
    assert len(coder_results) == 1
    assert coder_results[0][0] == "patch_1"
    assert coder_results[0][2]["agent_role"] == "Coder"

    # Query as Auditor: MUST ONLY return Auditor items
    auditor_results = router.query(v2, agent_role="Auditor", top_k=5)
    assert len(auditor_results) == 1
    assert auditor_results[0][0] == "audit_1"
    assert auditor_results[0][2]["agent_role"] == "Auditor"

    # Dynamic proportional reallocation under unbalanced workload (VSAR-033)
    workloads = {"Coder": 80, "Auditor": 20, "Lead-PI": 20, "System": 0}
    router.reallocate_shards_proportionally(workloads)
    stats = router.get_stats()
    assert stats["by_agent"]["Coder"]["num_shards"] >= 8
    assert stats["by_agent"]["Auditor"]["num_shards"] <= 4


def test_episodic_vsa_context_compressor():
    """EpisodicVSACompressor achieves >=50% token reduction while retaining key milestones."""
    compressor = EpisodicVSACompressor(dim=4096, seed=42)

    traces = [
        {
            "action": "REGISTER_HYPOTHESIS",
            "summary": "Registered hypothesis H1 on fast kernel decode with shared memory tile layout",
            "details": {"id": "H1", "mechanism": "tiling reduces cache misses", "criteria": "speedup > 1.1"},
        },
        {
            "action": "TOOL_INVOKE",
            "summary": "Executed python tests/bench_kernel.py with parameters num_warmup=10, num_iters=100",
            "details": {
                "script": "tests/bench_kernel.py",
                "stdout": "Iteration 1: 12ms, Iteration 2: 11.8ms, Iteration 3: 11.9ms",
            },
        },
        {
            "action": "CODE_EDIT",
            "summary": "Refactored kernel tile dimension from 16x16 to 32x32 to maximize warp occupancy",
            "details": {"diff": "+ __shared__ float tile[32][32]; - __shared__ float tile[16][16];"},
        },
        {
            "action": "EXPERIMENT_RUN",
            "summary": "Executed benchmark_decode.py across 5 seeds with PyTorch CUDA profiler",
            "details": {"runtime": "120s", "seeds": [42, 43, 44, 45, 46], "gpu_util": "98%"},
        },
        {
            "action": "METRIC_COLLECT",
            "summary": "Aggregated latency metrics across all warmup and benchmark iterations",
            "details": {"mean_latency": "11.2ms", "p95": "12.1ms", "p99": "12.8ms"},
        },
        {
            "action": "LOG_EVIDENCE",
            "summary": "Observed geomean speedup 1.25x with 95% bootstrap confidence interval [1.18, 1.32]",
            "details": {"metric": "speedup", "delta": 0.25, "ci": [1.18, 1.32]},
        },
        {
            "action": "GATE_PASS",
            "summary": "Confirmed Gate G4 significance clearance above baseline 1.0x threshold",
            "details": {"gate": "G4", "verdict": "PASS"},
        },
        {
            "action": "VERIFY_DIFF",
            "summary": "Independent auditor checked kernel memory alignment and bounds checking",
            "details": {"auditor": "Auditor-S3", "status": "APPROVED"},
        },
        {
            "action": "CONFIRM_HYPOTHESIS",
            "summary": "Promoted H1 to CONFIRMED at evidence level E4 following statistical verification",
            "details": {"id": "H1", "level": "E4"},
        },
    ]

    res = compressor.compress_traces(traces)

    assert "compressed_digest" in res
    assert res["token_reduction_pct"] >= 50.0
    assert "CONFIRM_HYPOTHESIS" in res["compressed_digest"]
    assert "GATE_PASS" in res["compressed_digest"]


def test_mcp_advanced_vsa_tools(tmp_path: Path):
    """FastMCP server exposes epires_vsa_multihop_query, epires_sharded_search, and epires_compress_context."""
    db_file = str(tmp_path / "mcp_adv_vsa.db")
    mcp = create_mcp_server(db_path=db_file)

    # 1. Verify 33 tools registered
    assert len(mcp._tool_manager.list_tools()) == 33

    # 2. Register hypotheses & relations in store
    reg_tool = mcp._tool_manager.get_tool("epires_register_hypothesis")
    reg_tool.fn(id="H10", title="Root H10", a_priori_mechanism="m", falsification_criteria="c")
    reg_tool.fn(id="H20", title="Middle H20", a_priori_mechanism="m", falsification_criteria="c")
    reg_tool.fn(id="H30", title="Target H30", a_priori_mechanism="m", falsification_criteria="c")

    rel_tool = mcp._tool_manager.get_tool("epires_add_relation")
    rel_tool.fn(source_id="H10", target_id="H20", relation_type="BLOCKS")
    rel_tool.fn(source_id="H20", target_id="H30", relation_type="GATED_BY")

    # 3. Test epires_vsa_multihop_query
    multihop_tool = mcp._tool_manager.get_tool("epires_vsa_multihop_query")
    hop_res = json.loads(multihop_tool.fn(head_id="H10", relation_1="BLOCKS", relation_2="GATED_BY", top_k=3))
    assert len(hop_res) > 0
    assert hop_res[0]["target_id"] == "H30"

    # 4. Test epires_sharded_search
    shard_tool = mcp._tool_manager.get_tool("epires_sharded_search")
    shard_res = json.loads(shard_tool.fn(query="Root H10", agent_role="Lead-PI", top_k=3))
    assert len(shard_res) > 0
    assert shard_res[0]["agent_role"] == "Lead-PI"

    # 5. Test epires_compress_context
    trace_tool = mcp._tool_manager.get_tool("epires_record_trace")
    trace_tool.fn(action="DECISION", summary="Elected to test kernel fusion approach", agent_role="Lead-PI")
    trace_tool.fn(action="CONFIRM", summary="Confirmed positive latency reduction", agent_role="Lead-PI")

    compress_tool = mcp._tool_manager.get_tool("epires_compress_context")
    compress_res = json.loads(compress_tool.fn(limit=10))
    assert "compressed_digest" in compress_res
    assert "DECISION" in compress_res["compressed_digest"]
