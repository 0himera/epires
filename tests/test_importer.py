"""Tests for Ingestion, Markdown Parsing, and Export/Import Bundling."""

import json
import tempfile
from pathlib import Path

from epires_core.importer import (
    export_graph_bundle,
    import_graph_bundle,
    ingest_file,
    parse_markdown_findings,
)
from epires_core.models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    HypothesisNode,
    HypothesisStatus,
    SourceConfidence,
)
from epires_core.store import EpiresStore


SAMPLE_FINDINGS_MD = """# Research Findings: Signal Decomposition

## [CONFIRMED] H-01: Discrete Wavelet Transform (DWT)
- **Mechanism**: Multiresolution decomposition isolates non-stationary high frequency noise.
- **Falsification Criteria**: RMSLE > 0.45 on out-of-time test fold.
- **Level**: E3
- **Model**: LightGBM
- **Feature**: HaarWavelets
- **Tags**: wavelets, signal, lightgbm
- **Evidence**: RMSLE = 0.38 achieved on fold 2 validation

## [FALSIFIED] H-02: Moving Average Smoothing
- **Theoretical Basis**: Low-pass filter reduces variance.
- **Falsify**: RMSLE regression > 0.05 vs baseline.
- **Depends On**: H-01
- **Evidence**: Regressed metric RMSLE = 0.58 (falsification triggered)

### H-03: Fourier Spectral Residuals
- **Rationale**: FFT residual reveals seasonal cyclic harmonics.
- **Falsification**: delta >= 0.0
- **Parents**: H-01
- **Tags**: fft, spectral
"""


def test_markdown_parser():
    hypos, evidence = parse_markdown_findings(SAMPLE_FINDINGS_MD)
    assert len(hypos) == 3
    assert len(evidence) >= 2

    h1 = next(h for h in hypos if h.id == "H-01")
    assert h1.status == HypothesisStatus.CONFIRMED
    assert "Wavelet" in h1.title
    assert "Multiresolution" in h1.a_priori_mechanism
    assert any(e.value == "HaarWavelets" for e in h1.entities)

    h2 = next(h for h in hypos if h.id == "H-02")
    assert h2.status == HypothesisStatus.FALSIFIED
    assert "H-01" in h2.parent_ids

    h3 = next(h for h in hypos if h.id == "H-03")
    assert h3.status == HypothesisStatus.PROPOSED
    assert "H-01" in h3.parent_ids


def test_ingest_file_dry_run_and_upsert():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_ingest.db")
        store = EpiresStore(db_path=db_path)

        md_file = Path(tmpdir) / "findings.md"
        md_file.write_text(SAMPLE_FINDINGS_MD, encoding="utf-8")

        # 1. Dry run
        dry_res = ingest_file(store=store, file_path=md_file, dry_run=True)
        assert dry_res["dry_run"] is True
        assert dry_res["hypotheses_count"] == 3
        assert len(store.list_hypotheses()) == 0  # Nothing committed

        # 2. Real ingest
        real_res = ingest_file(store=store, file_path=md_file, dry_run=False)
        assert real_res["hypotheses_ingested"] == 3
        assert len(store.list_hypotheses()) == 3

        # Verify DAG relations
        h2 = store.get_hypothesis("H-02")
        assert "H-01" in h2.parent_ids


def test_export_import_bundle_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        db1_path = str(Path(tmpdir) / "db1.db")
        store1 = EpiresStore(db_path=db1_path)

        # Register sample nodes and evidence in store1
        h1 = HypothesisNode(
            id="H10",
            title="Root model",
            a_priori_mechanism="Theoretical convergence",
            falsification_criteria="Loss > 1.0",
            target_evidence_level=EvidenceLevel.E3,
            status=HypothesisStatus.CONFIRMED,
            entities=[Entity(type="Model", value="XGBoost")]
        )
        store1.register_hypothesis(h1)
        store1.log_evidence(EvidenceClaim(
            id="ev10",
            hypothesis_id="H10",
            evidence_level=EvidenceLevel.E3,
            source_confidence=SourceConfidence.V,
            claim="Loss = 0.62 validated"
        ))

        # Export bundle
        bundle = export_graph_bundle(store=store1, project_name="roundtrip-test")
        assert bundle["schema_version"] == "epires.v1"
        assert bundle["checksum_sha256"]
        assert bundle["counts"]["hypotheses"] == 1
        assert bundle["counts"]["evidence"] == 1

        # Import into fresh store2
        db2_path = str(Path(tmpdir) / "db2.db")
        store2 = EpiresStore(db_path=db2_path)
        import_res = import_graph_bundle(store=store2, bundle=bundle, upsert=True)

        assert import_res["hypotheses_ingested"] == 1
        assert import_res["evidence_ingested"] == 1

        h10_restored = store2.get_hypothesis("H10")
        assert h10_restored is not None
        assert h10_restored.title == "Root model"
        assert h10_restored.status == HypothesisStatus.CONFIRMED
        assert len(store2.list_evidence()) == 1
