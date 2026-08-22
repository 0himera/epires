"""Unit tests for SRMU novelty-gated stigmergy, synthesis report generator, and CLI suite."""

import tempfile
from pathlib import Path
import numpy as np
from epires_core.models import (
    EvidenceClaim,
    EvidenceLevel,
    HypothesisNode,
    HypothesisStatus,
    SourceConfidence,
    TraceEntry,
)
from epires_core.store import EpiresStore
from epires_core.stigmergy import srmu_novelty_gate, pheromone_weight
from epires_core.synthesis import generate_synthesis_report


class TestSRMUNoveltyAndStigmergy:
    def test_srmu_novelty_gate(self):
        # Identical vectors -> cosine similarity = 1.0 -> novelty = 0.0
        v1 = np.ones(100, dtype=np.int8)
        v2 = np.ones(100, dtype=np.int8)
        assert srmu_novelty_gate(v1, v2, dim=100) == 0.0

        # Orthogonal vectors -> cosine similarity = 0.0 -> novelty = 1.0
        v3 = np.array([1, 1, -1, -1], dtype=np.int8)
        v4 = np.array([1, -1, 1, -1], dtype=np.int8)
        assert abs(srmu_novelty_gate(v3, v4, dim=4) - 1.0) < 1e-6

        # None inputs gracefully return 1.0
        assert srmu_novelty_gate(None, v1) == 1.0

    def test_event_based_pheromone_decay(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EpiresStore(db_path=Path(tmpdir) / "test.db")
            h1 = HypothesisNode(
                id="H-OLD",
                title="Old Hypothesis",
                a_priori_mechanism="mech",
                falsification_criteria="crit",
                status=HypothesisStatus.CONFIRMED,
            )
            h2 = HypothesisNode(
                id="H-NEW",
                title="New Hypothesis",
                a_priori_mechanism="mech",
                falsification_criteria="crit",
                status=HypothesisStatus.CONFIRMED,
            )
            store.register_hypothesis(h1, emit_trace=False)
            store.register_hypothesis(h2, emit_trace=False)

            ev1 = EvidenceClaim(
                id="ev1",
                hypothesis_id="H-OLD",
                evidence_level=EvidenceLevel.E3,
                source_confidence=SourceConfidence.V,
                claim="H-OLD confirmed",
            )
            ev2 = EvidenceClaim(
                id="ev2",
                hypothesis_id="H-NEW",
                evidence_level=EvidenceLevel.E3,
                source_confidence=SourceConfidence.V,
                claim="H-NEW confirmed",
            )
            store.log_evidence(ev1, emit_trace=False)
            store.log_evidence(ev2, emit_trace=False)

            # Add traces where H-NEW is recent (index 0) and H-OLD is older (index 15)
            store.log_trace(TraceEntry(timestamp=store._now(), action="LOG", h_tag="H-NEW", summary="Recent"))
            for i in range(14):
                store.log_trace(TraceEntry(timestamp=store._now(), action="LOG", h_tag="H-OTHER", summary=f"Other {i}"))
            store.log_trace(TraceEntry(timestamp=store._now(), action="LOG", h_tag="H-OLD", summary="Old trace"))

            w_new = pheromone_weight("H-NEW", store, mode="srmu", half_life_events=5)
            w_old = pheromone_weight("H-OLD", store, mode="srmu", half_life_events=5)

            # H-NEW should have significantly higher pheromone weight than H-OLD
            assert w_new > w_old
            assert w_new > 1.0  # confirmed + freshness


class TestSynthesisReportGenerator:
    def test_generate_synthesis_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = EpiresStore(db_path=Path(tmpdir) / "test.db")
            h_conf = HypothesisNode(
                id="H-CONF",
                title="Confirmed Theory",
                a_priori_mechanism="Sound physics",
                falsification_criteria="delta < 0",
                status=HypothesisStatus.CONFIRMED,
                current_evidence_level=EvidenceLevel.E3,
            )
            h_fals = HypothesisNode(
                id="H-FALS",
                title="Falsified Theory",
                a_priori_mechanism="Naive idea",
                falsification_criteria="loss > 0.05",
                status=HypothesisStatus.FALSIFIED,
            )
            store.register_hypothesis(h_conf, emit_trace=False)
            store.register_hypothesis(h_fals, emit_trace=False)

            ev_conf = EvidenceClaim(
                id="ev_c",
                hypothesis_id="H-CONF",
                evidence_level=EvidenceLevel.E3,
                source_confidence=SourceConfidence.V,
                claim="Strong experimental verification",
                ci_95_lower=0.10,
                ci_95_upper=0.20,
            )
            ev_fals = EvidenceClaim(
                id="ev_f",
                hypothesis_id="H-FALS",
                evidence_level=EvidenceLevel.E3,
                source_confidence=SourceConfidence.V,
                claim="Refuted by OOT split",
                falsification_triggered=True,
                assumption_ids=["AUX_SEED_NOISE"],
            )
            store.log_evidence(ev_conf, emit_trace=False)
            store.log_evidence(ev_fals, emit_trace=False)

            report = generate_synthesis_report(store, project_name="Quantum Alpha")
            assert "# Epistemic Synthesis Report — Quantum Alpha" in report
            assert "POSIWID Integrity Gap" in report
            assert "Lakatos Hard Core" in report
            assert "H-CONF" in report
            assert "Duhem-Quine Falsifications" in report
            assert "H-FALS" in report
            assert "AUX_SEED_NOISE" in report
