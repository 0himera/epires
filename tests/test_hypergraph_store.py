"""Tests for Hypergraph encoding, SQLite storage, and Cascading Falsification DAG."""

import tempfile
from pathlib import Path
import pytest

from epires_core.models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    SearchQuery,
    SourceConfidence,
)
from epires_core.store import EpiresStore


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_hypotheses.db"
        store = EpiresStore(db_path=db_path, vsa_dim=2000)
        yield store


def test_register_and_get_hypothesis(temp_store: EpiresStore):
    h1 = HypothesisNode(
        id="H1",
        title="Direct Log-LightGBM baseline performs robustly under RMSLE",
        a_priori_mechanism="Log1p transform stabilizes exponential demand variance in GMV",
        falsification_criteria="OOT fold RMSLE exceeds 1.90 on clean validation",
        target_evidence_level=EvidenceLevel.E3,
        current_evidence_level=EvidenceLevel.E0,
        status=HypothesisStatus.PROPOSED,
        entities=[
            Entity(type="Model", value="LightGBM"),
            Entity(type="Metric", value="RMSLE"),
        ],
        tags=["baseline", "tabular"]
    )
    temp_store.register_hypothesis(h1)

    fetched = temp_store.get_hypothesis("H1")
    assert fetched is not None
    assert fetched.id == "H1"
    assert fetched.title == h1.title
    assert fetched.status == HypothesisStatus.PROPOSED
    assert len(fetched.entities) == 2


def test_evidence_promotion(temp_store: EpiresStore):
    h1 = HypothesisNode(
        id="H1",
        title="Direct Log-LightGBM",
        a_priori_mechanism="Theoretical variance stabilization",
        falsification_criteria="RMSLE > 1.90",
        target_evidence_level=EvidenceLevel.E3,
    )
    temp_store.register_hypothesis(h1)

    # Log positive evidence
    claim = EvidenceClaim(
        id="ev_h1_1",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        claim="Validation RMSLE measured 1.6915 on 250k holdout users",
        metric_name="RMSLE",
        metric_value=1.6915,
        delta_vs_baseline=-0.1424,
        falsification_triggered=False,
    )
    ev, blocked = temp_store.log_evidence(claim)
    assert len(blocked) == 0

    updated_h1 = temp_store.get_hypothesis("H1")
    assert updated_h1.current_evidence_level == EvidenceLevel.E3
    assert updated_h1.status == HypothesisStatus.CONFIRMED


def test_cascading_falsification_dag(temp_store: EpiresStore):
    # Parent hypothesis H1
    h1 = HypothesisNode(
        id="H1",
        title="Kanerva SDM Prototype Memory",
        a_priori_mechanism="Prototype averaging denoises recurrent market states",
        falsification_criteria="Exact binary kNN outperforms SDM hit@1 by >5%",
        target_evidence_level=EvidenceLevel.E3,
    )
    temp_store.register_hypothesis(h1)

    # Child hypothesis H2 depending on H1
    h2 = HypothesisNode(
        id="H2",
        title="Adaptive SDM Read/Write policy",
        a_priori_mechanism="Online weight updates in SDM memory accelerate regime adaptation",
        falsification_criteria="Sharpe drops below zero",
        parent_ids=["H1"],
        target_evidence_level=EvidenceLevel.E3,
    )
    temp_store.register_hypothesis(h2)

    # Grandchild hypothesis H3 depending on H2
    h3 = HypothesisNode(
        id="H3",
        title="SDM-guided execution router",
        a_priori_mechanism="Route maker orders based on SDM state recall",
        falsification_criteria="Fee drag > 20 bps",
        parent_ids=["H2"],
        target_evidence_level=EvidenceLevel.E3,
    )
    temp_store.register_hypothesis(h3)

    assert temp_store.get_hypothesis("H2").status == HypothesisStatus.PROPOSED
    assert temp_store.get_hypothesis("H3").status == HypothesisStatus.PROPOSED

    # Now FALSIFY H1!
    falsifying_claim = EvidenceClaim(
        id="ev_h1_fail",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        claim="SDM recall hit@1 = 0.000 vs exact kNN hit@1 = 1.000 across all epsilon sweeps",
        falsification_triggered=True,
    )
    _, blocked = temp_store.log_evidence(falsifying_claim)

    # Verify H1 is FALSIFIED
    assert temp_store.get_hypothesis("H1").status == HypothesisStatus.FALSIFIED
    
    # Verify H2 and H3 are automatically BLOCKED
    assert "H2" in blocked
    assert "H3" in blocked
    assert temp_store.get_hypothesis("H2").status == HypothesisStatus.BLOCKED
    assert temp_store.get_hypothesis("H3").status == HypothesisStatus.BLOCKED


def test_vsa_associative_search(temp_store: EpiresStore):
    h_catboost = HypothesisNode(
        id="H10",
        title="CatBoost GPU optimization with Haar Wavelet features",
        a_priori_mechanism="Wavelets capture multiscale periodicity",
        falsification_criteria="Delta > 0",
        entities=[Entity(type="Model", value="CatBoost"), Entity(type="Feature", value="Wavelet")],
        tags=["wavelet", "catboost"]
    )
    h_lgbm = HypothesisNode(
        id="H11",
        title="LightGBM CPU with lag aggregations",
        a_priori_mechanism="Lags capture temporal momentum",
        falsification_criteria="Delta > 0",
        entities=[Entity(type="Model", value="LightGBM"), Entity(type="Feature", value="Lags")],
        tags=["lags", "lightgbm"]
    )
    temp_store.register_hypothesis(h_catboost)
    temp_store.register_hypothesis(h_lgbm)

    # Search for Wavelet
    results = temp_store.search(SearchQuery(query="wavelet", limit=2))
    assert len(results) > 0
    top_h, score = results[0]
    assert top_h.id == "H10"


def test_gap_analysis(temp_store: EpiresStore):
    h1 = HypothesisNode(
        id="H1",
        title="CatBoost + Lags",
        a_priori_mechanism="...",
        falsification_criteria="...",
        entities=[Entity(type="Model", value="CatBoost"), Entity(type="Feature", value="Lags")]
    )
    h2 = HypothesisNode(
        id="H2",
        title="LightGBM + Wavelets",
        a_priori_mechanism="...",
        falsification_criteria="...",
        entities=[Entity(type="Model", value="LightGBM"), Entity(type="Feature", value="Wavelets")]
    )
    temp_store.register_hypothesis(h1)
    temp_store.register_hypothesis(h2)

    # Query gaps across Model and Feature
    gaps = temp_store.find_gaps(GapQuery(dimensions=["Model", "Feature"], min_tested=1))
    
    # Should identify untested combinations: (CatBoost, Wavelets) and (LightGBM, Lags)
    untested = [g["combination"] for g in gaps if g["status"] == "UNTESTED"]
    assert {"Model": "CatBoost", "Feature": "Wavelets"} in untested or {"Model": "LightGBM", "Feature": "Lags"} in untested
