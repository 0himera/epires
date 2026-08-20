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
    RelationEdge,
    RelationType,
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


def test_reregister_preserves_progress_and_replaces_only_dependency_edges(temp_store: EpiresStore):
    parent_a = HypothesisNode(id="HA", title="A", a_priori_mechanism="a", falsification_criteria="a")
    parent_b = HypothesisNode(id="HB", title="B", a_priori_mechanism="b", falsification_criteria="b")
    child = HypothesisNode(
        id="HC", title="Child", a_priori_mechanism="c", falsification_criteria="c", parent_ids=["HA"]
    )
    for hypothesis in (parent_a, parent_b, child):
        temp_store.register_hypothesis(hypothesis)
    with temp_store._get_connection() as conn:
        conn.execute(
            "INSERT INTO relations (source_id, target_id, relation_type, metadata_json) VALUES (?, ?, ?, ?)",
            ("HC", "HA", RelationType.REFINES.value, "{}"),
        )
    temp_store.log_evidence(EvidenceClaim(
        id="ev-progress", hypothesis_id="HC", evidence_level=EvidenceLevel.E3,
        claim="target achieved",
    ))

    temp_store.register_hypothesis(HypothesisNode(
        id="HC", title="Edited child", a_priori_mechanism="edited", falsification_criteria="edited",
        parent_ids=["HB"],
    ))
    saved = temp_store.get_hypothesis("HC")
    assert saved.current_evidence_level == EvidenceLevel.E3
    assert saved.status == HypothesisStatus.CONFIRMED

    # Even an explicitly stale active status must not reopen a confirmed row.
    temp_store.register_hypothesis(HypothesisNode(
        id="HC", title="Edited again", a_priori_mechanism="edited", falsification_criteria="edited",
        parent_ids=["HB"], current_evidence_level=EvidenceLevel.E1,
        status=HypothesisStatus.IN_PROGRESS,
    ))
    saved = temp_store.get_hypothesis("HC")
    assert saved.current_evidence_level == EvidenceLevel.E3
    assert saved.status == HypothesisStatus.CONFIRMED

    relations = temp_store.list_relations()
    assert RelationEdge(source_id="HC", target_id="HB", relation_type=RelationType.DEPENDS_ON) in relations
    assert not any(edge.source_id == "HC" and edge.target_id == "HA" and edge.relation_type == RelationType.DEPENDS_ON for edge in relations)
    assert RelationEdge(source_id="HC", target_id="HA", relation_type=RelationType.REFINES) in relations


def test_non_falsifying_evidence_does_not_reopen_blocked_or_falsified(temp_store: EpiresStore):
    for identifier in ("HF", "HB"):
        temp_store.register_hypothesis(HypothesisNode(
            id=identifier, title=identifier, a_priori_mechanism="m", falsification_criteria="f",
        ))
    with temp_store._get_connection() as conn:
        conn.execute("UPDATE hypotheses SET status = ? WHERE id = ?", (HypothesisStatus.FALSIFIED.value, "HF"))
        conn.execute("UPDATE hypotheses SET status = ? WHERE id = ?", (HypothesisStatus.BLOCKED.value, "HB"))
    for identifier in ("HF", "HB"):
        temp_store.log_evidence(EvidenceClaim(
            id=f"ev-{identifier}", hypothesis_id=identifier, evidence_level=EvidenceLevel.E3,
            claim="a non-falsifying result",
        ))
    assert temp_store.get_hypothesis("HF").status == HypothesisStatus.FALSIFIED
    assert temp_store.get_hypothesis("HB").status == HypothesisStatus.BLOCKED


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

    # Verify H1 is FALSIFIED and promoted to E3 (evidence rigor level reached)
    h1_after = temp_store.get_hypothesis("H1")
    assert h1_after.status == HypothesisStatus.FALSIFIED
    assert h1_after.current_evidence_level == EvidenceLevel.E3

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


def test_retract_evidence_and_cascade_unblock(temp_store: EpiresStore):
    # Setup H1 -> H2 -> H3
    h1 = HypothesisNode(id="H100", title="Root mechanism", a_priori_mechanism="math", falsification_criteria="loss > 1.0")
    h2 = HypothesisNode(id="H101", title="Child 1", a_priori_mechanism="math", falsification_criteria="loss > 1.0", parent_ids=["H100"])
    h3 = HypothesisNode(id="H102", title="Child 2", a_priori_mechanism="math", falsification_criteria="loss > 1.0", parent_ids=["H101"])
    temp_store.register_hypothesis(h1)
    temp_store.register_hypothesis(h2)
    temp_store.register_hypothesis(h3)

    # Log an initial positive E2 observation for H100
    ev_ok = EvidenceClaim(id="ev_ok", hypothesis_id="H100", evidence_level=EvidenceLevel.E2, source_confidence=SourceConfidence.V, claim="Passed local smoke test")
    temp_store.log_evidence(ev_ok)
    assert temp_store.get_hypothesis("H100").status == HypothesisStatus.IN_PROGRESS
    assert temp_store.get_hypothesis("H100").current_evidence_level == EvidenceLevel.E2

    # Log an erroneous falsifying E4 evidence for H100 (e.g. data leak / bug in test)
    ev_bug = EvidenceClaim(
        id="ev_bug",
        hypothesis_id="H100",
        evidence_level=EvidenceLevel.E4,
        source_confidence=SourceConfidence.V,
        claim="Data leak caused false regression",
        falsification_triggered=True
    )
    _, blocked = temp_store.log_evidence(ev_bug)
    assert temp_store.get_hypothesis("H100").status == HypothesisStatus.FALSIFIED
    assert temp_store.get_hypothesis("H100").current_evidence_level == EvidenceLevel.E4
    assert temp_store.get_hypothesis("H101").status == HypothesisStatus.BLOCKED
    assert temp_store.get_hypothesis("H102").status == HypothesisStatus.BLOCKED
    assert "H101" in blocked and "H102" in blocked

    # Now RETRACT the erroneous ev_bug!
    retracted, unblocked = temp_store.retract_evidence("ev_bug", reason="Bug discovered in validation pipeline split")
    assert retracted is not None
    assert retracted.id == "ev_bug"

    # Verify H100 is no longer FALSIFIED, and its level demotes back to E2 (the remaining valid claim)
    h100_after = temp_store.get_hypothesis("H100")
    assert h100_after.status == HypothesisStatus.IN_PROGRESS
    assert h100_after.current_evidence_level == EvidenceLevel.E2

    # Verify H101 and H102 are automatically UNBLOCKED back to PROPOSED
    assert "H101" in unblocked
    assert "H102" in unblocked
    assert temp_store.get_hypothesis("H101").status == HypothesisStatus.PROPOSED
    assert temp_store.get_hypothesis("H102").status == HypothesisStatus.PROPOSED

