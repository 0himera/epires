"""Fuzz testing for Epires SQLite store with arbitrary inputs, unicode, and extreme values."""

import tempfile
from pathlib import Path
from hypothesis import given, settings, strategies as st

from epires_core.models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    HypothesisNode,
    SearchQuery,
    SourceConfidence,
)
from epires_core.store import EpiresStore


@settings(max_examples=50)
@given(
    h_id=st.text(min_size=1, max_size=20, alphabet=st.characters(blacklist_categories=("Cc", "Cs"))),
    title=st.text(min_size=1, max_size=200),
    mechanism=st.text(min_size=1, max_size=300),
    falsification=st.text(min_size=1, max_size=300),
    metric_val=st.floats(allow_nan=False, allow_infinity=False, min_value=-1e8, max_value=1e8),
    delta_val=st.floats(allow_nan=False, allow_infinity=False, min_value=-1e8, max_value=1e8),
)
def test_fuzz_store_arbitrary_hypothesis_and_evidence(
    h_id: str, title: str, mechanism: str, falsification: str, metric_val: float, delta_val: float
):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "fuzz_store.db"
        store = EpiresStore(db_path=db_path, vsa_dim=2000)

        unique_tag = f"tag_{abs(hash(h_id))}"
        h = HypothesisNode(
            id=h_id,
            title=title,
            a_priori_mechanism=mechanism,
            falsification_criteria=falsification,
            entities=[Entity(type="TestType", value="UniqueEntityVal")],
            tags=[unique_tag, "fuzz"],
        )
        store.register_hypothesis(h)

        # 1. Strict persistence and exact field matching
        fetched = store.get_hypothesis(h_id)
        assert fetched is not None
        assert fetched.id == h_id
        assert fetched.title == title
        assert fetched.a_priori_mechanism == mechanism
        assert fetched.falsification_criteria == falsification

        claim_id = f"ev_{abs(hash(h_id))}"
        claim = EvidenceClaim(
            id=claim_id,
            hypothesis_id=h_id,
            evidence_level=EvidenceLevel.E2,
            source_confidence=SourceConfidence.V,
            claim="Fuzz empirical claim",
            metric_name="MetricA",
            metric_value=metric_val,
            delta_vs_baseline=delta_val,
            falsification_triggered=False,
        )
        store.log_evidence(claim)

        # 2. Strict evidence retrieval & metric precision
        ev_list = store.get_evidence_for_hypothesis(h_id)
        assert len(ev_list) == 1
        assert ev_list[0].id == claim_id
        assert abs(ev_list[0].metric_value - metric_val) < 1e-4
        assert abs(ev_list[0].delta_vs_baseline - delta_val) < 1e-4

        # 3. Strict semantic & entity retrieval: target hypothesis must be found at Rank 1
        results = store.search(
            SearchQuery(
                query=unique_tag,
                entities=[Entity(type="TestType", value="UniqueEntityVal")],
                limit=5,
            )
        )
        assert len(results) >= 1
        top_node, score = results[0]
        assert top_node.id == h_id
        assert score > 0.0
