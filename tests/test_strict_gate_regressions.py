"""Regression coverage for strict gate provenance and relation semantics."""

from epires_core.gates import check_g2, check_g3, check_g4
from epires_core.models import (
    EvidenceClaim,
    EvidenceLevel,
    ExperimentNode,
    HypothesisNode,
    RelationEdge,
    RelationType,
    TraceEntry,
)
from epires_core.store import EpiresStore
import hashlib


def _hypothesis(hypothesis_id: str = "H1") -> HypothesisNode:
    return HypothesisNode(
        id=hypothesis_id,
        title="Test hypothesis",
        a_priori_mechanism="mechanism",
        falsification_criteria="loss > 0.10",
    )


def test_g2_accepts_preregistered_multiple_holdout_hashes():
    evidence = EvidenceClaim(hypothesis_id="H1", timestamp="2026-01-02T00:00:00+00:00")
    experiment = ExperimentNode(
        id="EXP-1",
        hypothesis_id="H1",
        name="three-holdout run",
        script_path="run.py",
        parameters={"held_out_hashes": ["sha256-a", "sha256-b", "sha256-c"]},
        created_at="2026-01-01T00:00:00+00:00",
    )

    assert check_g2([evidence], hypothesis=_hypothesis(), experiments=[experiment]) is True


def test_g2_anchors_to_first_quantitative_result_not_e0_or_e1():
    prereg = EvidenceClaim(hypothesis_id="H1", evidence_level=EvidenceLevel.E0, timestamp="2026-01-01T00:00:00+00:00")
    implementation = EvidenceClaim(
        hypothesis_id="H1", evidence_level=EvidenceLevel.E1, timestamp="2026-01-02T00:00:00+00:00"
    )
    result = EvidenceClaim(
        hypothesis_id="H1", evidence_level=EvidenceLevel.E4, metric_name="loss", timestamp="2026-01-04T00:00:00+00:00"
    )
    experiment = ExperimentNode(
        id="EXP-1",
        hypothesis_id="H1",
        name="run",
        script_path="run.py",
        parameters={"held_out_hash": "sha256-a"},
        created_at="2026-01-03T00:00:00+00:00",
    )
    assert check_g2([prereg, implementation, result], hypothesis=_hypothesis(), experiments=[experiment]) is True


def test_g2_rejects_experiment_registered_after_quantitative_result():
    result = EvidenceClaim(
        hypothesis_id="H1", evidence_level=EvidenceLevel.E4, metric_name="loss", timestamp="2026-01-02T00:00:00+00:00"
    )
    experiment = ExperimentNode(
        id="EXP-1",
        hypothesis_id="H1",
        name="late",
        script_path="run.py",
        parameters={"held_out_hash": "sha256-a"},
        created_at="2026-01-03T00:00:00+00:00",
    )
    assert check_g2([result], hypothesis=_hypothesis(), experiments=[experiment]) is False


def test_g3_accepts_hashed_e0_preregistration_evidence():
    prereg = EvidenceClaim(
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E0,
        citation_or_path="artifacts/prereg.md",
        artifact_hash="a" * 64,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    result = EvidenceClaim(
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E4,
        metric_name="loss",
        timestamp="2026-01-02T00:00:00+00:00",
    )

    assert check_g3([prereg, result], hypothesis=_hypothesis()) is True


def test_g3_requires_a_hashed_preregistration_trace():
    result = EvidenceClaim(
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E4,
        metric_name="loss",
        timestamp="2026-01-02T00:00:00+00:00",
    )
    trace = TraceEntry(
        action="PREREGISTRATION",
        h_tag="H1",
        timestamp="2026-01-01T00:00:00+00:00",
        summary="Preregistration recorded before the result",
        details={"artifact_hash": "b" * 64},
    )

    assert check_g3([result], hypothesis=_hypothesis(), traces=[trace]) is True


def test_g3_legacy_migration_requires_current_hash_and_original_timestamp(tmp_path):
    artifact = tmp_path / "legacy-prereg.md"
    artifact.write_text("metric=loss; stop_rule=fixed", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    prereg = EvidenceClaim(
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E0,
        citation_or_path=str(artifact),
        timestamp="2026-01-02T00:00:00+00:00",
    )
    result = EvidenceClaim(
        hypothesis_id="H1", evidence_level=EvidenceLevel.E4, metric_name="loss", timestamp="2026-01-04T00:00:00+00:00"
    )
    trace = TraceEntry(
        action="LEGACY_PREREG_MIGRATION",
        h_tag="H1",
        timestamp="2026-01-05T00:00:00+00:00",
        summary="Migrated legacy preregistration",
        details={
            "legacy_prereg_migration": True,
            "artifact_path": str(artifact),
            "artifact_hash": digest,
            "original_evidence_timestamp": "2026-01-02T00:00:00+00:00",
        },
    )
    assert check_g3([prereg, result], hypothesis=_hypothesis(), traces=[trace]) is True


def test_g3_legacy_migration_rejects_late_trace_or_bad_hash(tmp_path):
    artifact = tmp_path / "legacy-prereg.md"
    artifact.write_text("metric=loss", encoding="utf-8")
    prereg = EvidenceClaim(
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E0,
        citation_or_path=str(artifact),
        timestamp="2026-01-02T00:00:00+00:00",
    )
    result = EvidenceClaim(
        hypothesis_id="H1", evidence_level=EvidenceLevel.E4, metric_name="loss", timestamp="2026-01-04T00:00:00+00:00"
    )
    trace = TraceEntry(
        action="LEGACY_PREREG_MIGRATION",
        h_tag="H1",
        timestamp="2026-01-05T00:00:00+00:00",
        summary="Late migration",
        details={
            "legacy_prereg_migration": True,
            "artifact_path": str(artifact),
            "artifact_hash": "0" * 64,
            "original_evidence_timestamp": "2026-01-02T00:00:00+00:00",
        },
    )
    assert check_g3([prereg, result], hypothesis=_hypothesis(), traces=[trace]) is False


def test_g3_legacy_migration_rejects_unmatched_historical_e0(tmp_path):
    artifact = tmp_path / "legacy-prereg.md"
    artifact.write_text("metric=loss", encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    # Caller claims a historical timestamp, but there is no matching active E0.
    result = EvidenceClaim(
        hypothesis_id="H1", evidence_level=EvidenceLevel.E4, metric_name="loss", timestamp="2026-01-04T00:00:00+00:00"
    )
    trace = TraceEntry(
        action="LEGACY_PREREG_MIGRATION",
        h_tag="H1",
        timestamp="2026-01-05T00:00:00+00:00",
        summary="Unanchored migration",
        details={
            "legacy_prereg_migration": True,
            "artifact_path": str(artifact),
            "artifact_hash": digest,
            "original_evidence_timestamp": "2026-01-02T00:00:00+00:00",
        },
    )
    assert check_g3([result], hypothesis=_hypothesis(), traces=[trace]) is False


def test_g4_ignores_nonquantitative_early_evidence_but_requires_ci_for_result():
    prereg = EvidenceClaim(hypothesis_id="H1", evidence_level=EvidenceLevel.E0)
    implementation = EvidenceClaim(hypothesis_id="H1", evidence_level=EvidenceLevel.E1)
    result = EvidenceClaim(
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E4,
        metric_name="loss",
        ci_95_lower=0.02,
        ci_95_upper=0.08,
    )

    assert check_g4([prereg, implementation, result], hypothesis=_hypothesis()) is True


def test_g4_matches_ci_to_its_metric_not_unrelated_criteria():
    hypothesis = HypothesisNode(
        id="H1",
        title="Latency",
        a_priori_mechanism="m",
        falsification_criteria="raw index memory >= 6.0x or p50 latency ratio >= 1.10 or ordered top-10 exact",
    )
    result = EvidenceClaim(
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E4,
        metric_name="p50_latency_ratio",
        ci_95_lower=0.19,
        ci_95_upper=0.21,
    )
    assert check_g4([result], hypothesis=hypothesis) is True


def test_g7_accounts_for_explicit_retraction_tombstone():
    active = [EvidenceClaim(id=f"ev-{i}", hypothesis_id="H1") for i in range(3)]
    traces = [
        TraceEntry(action="LOG_EVIDENCE", h_tag="H1", summary="logged", details={"evidence_id": f"ev-{i}"})
        for i in range(4)
    ]
    traces.append(
        TraceEntry(action="RETRACT_EVIDENCE", h_tag="H1", summary="retracted", details={"evidence_id": "ev-3"})
    )
    from epires_core.gates import check_g7

    assert check_g7(active, hypothesis=_hypothesis(), traces=traces) is True


def test_g7_still_rejects_unaccounted_active_run():
    active = [EvidenceClaim(id=f"ev-{i}", hypothesis_id="H1") for i in range(2)]
    traces = [
        TraceEntry(action="LOG_EVIDENCE", h_tag="H1", summary="logged", details={"evidence_id": f"ev-{i}"})
        for i in range(4)
    ]
    traces.append(
        TraceEntry(action="RETRACT_EVIDENCE", h_tag="H1", summary="retracted", details={"evidence_id": "ev-3"})
    )
    from epires_core.gates import check_g7

    assert check_g7(active, hypothesis=_hypothesis(), traces=traces) is False


def test_preregistration_artifact_is_hashed_and_traced(tmp_path):
    prereg = tmp_path / "prereg.md"
    prereg.write_text("metric=loss; stop_rule=fixed", encoding="utf-8")
    store = EpiresStore(db_path=str(tmp_path / "epires.db"))

    store.register_hypothesis(_hypothesis(), preregistration_artifact=str(prereg))

    trace = next(trace for trace in store.list_traces() if trace.action == "PREREGISTRATION")
    assert trace.h_tag == "H1"
    assert trace.details["hash_algorithm"] == "sha256"
    assert len(trace.details["artifact_hash"]) == 64


def test_replication_relation_does_not_become_a_dependency_or_cascade(tmp_path):
    store = EpiresStore(db_path=str(tmp_path / "epires.db"))
    store.register_hypothesis(_hypothesis("SOURCE"))
    store.register_hypothesis(_hypothesis("REPLICATION"))
    store.add_relation(RelationEdge(source_id="REPLICATION", target_id="SOURCE", relation_type=RelationType.REPLICATES))

    assert store.get_hypothesis("REPLICATION").parent_ids == []
    assert store._cascade_falsification("SOURCE") == []
