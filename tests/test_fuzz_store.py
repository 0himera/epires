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
        store = EpiresStore(db_path=db_path, vsa_dim=1000)

        h = HypothesisNode(
            id=h_id,
            title=title,
            a_priori_mechanism=mechanism,
            falsification_criteria=falsification,
            entities=[Entity(type="TestType", value="TestVal")],
            tags=["fuzz", "test"],
        )
        store.register_hypothesis(h)

        fetched = store.get_hypothesis(h_id)
        assert fetched is not None
        assert fetched.id == h_id
        assert fetched.title == title

        claim = EvidenceClaim(
            id=f"ev_{hash(h_id)}",
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

        # Search should not crash
        results = store.search(SearchQuery(query="TestVal", limit=5))
        assert isinstance(results, list)
