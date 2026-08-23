"""Real Agent Scenario: Multi-Hop Causal Graph Dependency Reasoning.

The agent is asked to investigate whether hypothesis H3 (Continuous Batching Pipeline)
is blocked by upstream kernel constraints originating from H1 (Sparse Attention Kernel).
Graph structure:
  H1 -BLOCKS-> H2 -GATED_BY-> H3
plus 10 distractor hypotheses.

The agent must discover this 2-hop causal dependency using Epires MCP tools
(such as `epires_vsa_multihop_query` or graph inspection) and mark H3 as BLOCKED
or log a causal trace linking H1 -> H2 -> H3.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from epires_core.models import (
    EvidenceLevel,
    HypothesisNode,
    HypothesisStatus,
    RelationEdge,
    RelationType,
    TraceEntry,
)
from epires_core.store import EpiresStore

DESCRIPTION = (
    "H3 (Continuous Batching Pipeline) appears ready, but is transitively gated by H2 which is blocked by H1. "
    "The agent must navigate the 2-hop dependency graph and correctly flag the upstream blocker."
)
TASK = (
    "You are the Lead Principal Investigator. Investigate hypothesis H3 ('Continuous Batching Pipeline') in Epires. "
    "Check whether H3 is transitively blocked or gated by any upstream hypothesis starting from H1 ('Sparse Attention Kernel'). "
    "Use Epires MCP tools (such as `epires_vsa_multihop_query`, `epires_query_graph`, `epires_list_relations`, or `epires_summary`). "
    "If H3 is blocked/gated by H1 via an intermediate hypothesis (H2), update H3's status to BLOCKED "
    "or record an evidence/trace with action 'CAUSAL_GATE_DISCOVERED' mentioning H1, H2, and H3. "
    'Return JSON {"action": "attribute", "blocker": "H1", "intermediate": "H2", "target": "H3"}.'
)


def _seed(store: Any) -> None:
    store.register_hypothesis(
        HypothesisNode(
            id="H1",
            title="Sparse Attention Kernel Layout",
            a_priori_mechanism="Memory tile partitioning",
            falsification_criteria="throughput < 1.0",
            target_evidence_level=EvidenceLevel.E3,
            status=HypothesisStatus.IN_PROGRESS,
        )
    )
    store.register_hypothesis(
        HypothesisNode(
            id="H2",
            title="Dynamic Shared Memory Tiler",
            a_priori_mechanism="Synchronous warp scheduling",
            falsification_criteria="latency > 15ms",
            target_evidence_level=EvidenceLevel.E3,
            status=HypothesisStatus.PROPOSED,
        )
    )
    store.register_hypothesis(
        HypothesisNode(
            id="H3",
            title="Continuous Batching Pipeline",
            a_priori_mechanism="Dynamic request packing",
            falsification_criteria="p99_latency > 50ms",
            target_evidence_level=EvidenceLevel.E3,
            status=HypothesisStatus.PROPOSED,
        )
    )

    # 10 Distractors
    for i in range(4, 14):
        store.register_hypothesis(
            HypothesisNode(
                id=f"H{i}",
                title=f"Auxiliary Optimization Component {i}",
                a_priori_mechanism="Auxiliary heuristic",
                falsification_criteria="metric < 0.1",
                target_evidence_level=EvidenceLevel.E2,
                status=HypothesisStatus.PROPOSED,
            )
        )
        store.add_relation(RelationEdge(source_id=f"H{i}", target_id="H3", relation_type=RelationType.REFINES))

    # Real 2-hop causal chain: H1 BLOCKS H2, H2 GATED_BY H3 (or H2 BLOCKS H3)
    store.add_relation(RelationEdge(source_id="H1", target_id="H2", relation_type=RelationType.BLOCKS))
    store.add_relation(RelationEdge(source_id="H2", target_id="H3", relation_type=RelationType.BLOCKS))


def _blocker_discovered(store: Any) -> bool:
    h3 = store.get_hypothesis("H3")
    if h3 and h3.status == HypothesisStatus.BLOCKED:
        return True

    traces = store.list_traces(limit=20)
    for t in traces:
        blob = f"{t.action} {t.summary} {str(t.details)}".lower()
        if "h1" in blob and ("h2" in blob or "block" in blob):
            return True

    evidence = store.list_evidence()
    for ev in evidence:
        blob = f"{ev.claim} {ev.hypothesis_id}".lower()
        if "h1" in blob or "blocked" in blob:
            return True

    return False


def run(agent: Any, store: Any, workspace: Optional[Any] = None) -> Dict[str, Any]:
    _seed(store)
    discovered = False

    if workspace is not None and hasattr(agent, "seed"):
        ws_store = EpiresStore(db_path=workspace / ".epires" / "hypotheses.db", trace_md_path=None)
        _seed(ws_store)
        agent.seed(workspace, TASK)
        agent.run(TASK, workspace)
        discovered = _blocker_discovered(ws_store)
    else:
        # Mock / Direct agent fallback
        obs = {
            "kind": "query",
            "task": "Find 2-hop blocker from H1 to H3",
            "head": "H1",
            "target": "H3",
        }
        act = agent.respond(obs)
        if act.get("action") in ("attribute", "falsify", "verify_level") or act.get("blocker") == "H1":
            store.log_trace(
                TraceEntry(
                    action="CAUSAL_GATE_DISCOVERED",
                    summary="Identified H1 blocks H2 which blocks H3",
                    details={"blocker": "H1", "intermediate": "H2", "target": "H3"},
                )
            )
            discovered = True

    return {"multihop_discovered": discovered}


def success(result: Dict[str, Any]) -> bool:
    return bool(result.get("multihop_discovered"))
