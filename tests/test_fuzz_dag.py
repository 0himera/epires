"""Property-based Fuzz testing for Random Hypothesis DAGs and Cascading Falsification."""

import tempfile
from pathlib import Path
from typing import Dict, List, Set
from hypothesis import given, settings, strategies as st

from epires_core.models import (
    EvidenceClaim,
    EvidenceLevel,
    HypothesisNode,
    HypothesisStatus,
    SourceConfidence,
)
from epires_core.store import EpiresStore


def get_expected_descendants(dag_adj: Dict[str, List[str]], root_id: str) -> Set[str]:
    """Computes all reachable downstream children using BFS."""
    visited: Set[str] = set()
    queue = [root_id]
    while queue:
        curr = queue.pop(0)
        for child in dag_adj.get(curr, []):
            if child not in visited:
                visited.add(child)
                queue.append(child)
    return visited


@settings(max_examples=50)
@given(
    num_nodes=st.integers(min_value=3, max_value=20),
    edge_density=st.floats(min_value=0.1, max_value=0.5),
    falsify_index=st.integers(min_value=0, max_value=19),
)
def test_fuzz_dag_cascading_falsification(num_nodes: int, edge_density: float, falsify_index: int):
    """Property: Falsifying any node in an arbitrary DAG blocks ALL and ONLY its downstream descendants."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "fuzz_dag.db"
        store = EpiresStore(db_path=db_path, vsa_dim=1000)

        # Build random DAG: node i can have parents from 0..i-1 (guarantees DAG without cycles)
        node_ids = [f"H{i}" for i in range(num_nodes)]
        dag_children: Dict[str, List[str]] = {nid: [] for nid in node_ids}

        for i in range(num_nodes):
            parents = []
            if i > 0:
                for j in range(i):
                    # Deterministic pseudo-random edge creation based on index and density
                    if ((i * 7 + j * 13) % 100) / 100.0 < edge_density:
                        parents.append(node_ids[j])
                        dag_children[node_ids[j]].append(node_ids[i])

            h = HypothesisNode(
                id=node_ids[i],
                title=f"Hypothesis {node_ids[i]}",
                a_priori_mechanism="Theoretical mechanism",
                falsification_criteria="Numerical failure",
                parent_ids=parents,
                status=HypothesisStatus.PROPOSED,
            )
            store.register_hypothesis(h)

        target_node = node_ids[falsify_index % num_nodes]
        expected_blocked = get_expected_descendants(dag_children, target_node)

        # Trigger falsification on target_node
        claim = EvidenceClaim(
            id=f"ev_fuzz_{target_node}",
            hypothesis_id=target_node,
            evidence_level=EvidenceLevel.E3,
            source_confidence=SourceConfidence.V,
            claim=f"Falsification triggered for {target_node}",
            falsification_triggered=True,
        )
        _, returned_blocked = store.log_evidence(claim)

        # Assertions
        assert set(returned_blocked) == expected_blocked

        # Check statuses in database
        target_h = store.get_hypothesis(target_node)
        assert target_h.status == HypothesisStatus.FALSIFIED

        for nid in node_ids:
            if nid == target_node:
                continue
            h_obj = store.get_hypothesis(nid)
            if nid in expected_blocked:
                assert h_obj.status == HypothesisStatus.BLOCKED, f"Expected {nid} to be BLOCKED"
            else:
                assert h_obj.status == HypothesisStatus.PROPOSED, f"Expected {nid} to remain PROPOSED"
