"""Tests for atomic CLI commands: register-hypothesis and log-evidence."""

import tempfile
from pathlib import Path
from epires_core.cli import init_workspace, main
from epires_core.store import EpiresStore
from epires_core.models import HypothesisStatus, EvidenceLevel
import sys


def test_cli_atomic_register_and_log_evidence(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        init_workspace(target_dir=tmp_path)
        store = EpiresStore(db_path=tmp_path / ".epires" / "hypotheses.db")

        # 1. Test register-hypothesis
        test_args_reg = [
            "epires",
            "register-hypothesis",
            "--id",
            "H-ATOMIC-1",
            "--title",
            "Atomic CLI Registration Test",
            "--mechanism",
            "Command-line ergonomic interface reduces subagent friction",
            "--criteria",
            "delta < 0",
            "--target-level",
            "E3",
        ]
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", test_args_reg)
        main()

        h = store.get_hypothesis("H-ATOMIC-1")
        assert h is not None
        assert h.title == "Atomic CLI Registration Test"
        assert h.status == HypothesisStatus.PROPOSED
        assert h.target_evidence_level == EvidenceLevel.E3

        # 2. Test log-evidence (CONFIRMED)
        test_args_ev1 = [
            "epires",
            "log-evidence",
            "--hypothesis",
            "H-ATOMIC-1",
            "--claim",
            "Subagent successfully executed test suite without SQL overhead",
            "--level",
            "E3",
            "--delta",
            "0.015",
            "--ci",
            "[0.005, 0.025]",
            "--metric",
            "F1_SCORE",
        ]
        monkeypatch.setattr(sys, "argv", test_args_ev1)
        main()

        h_after = store.get_hypothesis("H-ATOMIC-1")
        assert h_after.status == HypothesisStatus.CONFIRMED
        assert h_after.current_evidence_level == EvidenceLevel.E3

        evs = store.get_evidence_for_hypothesis("H-ATOMIC-1")
        assert len(evs) == 1
        assert evs[0].delta_vs_baseline == 0.015
        assert evs[0].ci_95_lower == 0.005
        assert evs[0].ci_95_upper == 0.025

        # 3. Test register child hypothesis and falsification cascade
        test_args_child = [
            "epires",
            "register",
            "--id",
            "H-CHILD-1",
            "--title",
            "Child Hypothesis",
            "--mechanism",
            "Depends on parent",
            "--criteria",
            "delta < 0",
            "--parents",
            "H-ATOMIC-1",
        ]
        monkeypatch.setattr(sys, "argv", test_args_child)
        main()

        child_h = store.get_hypothesis("H-CHILD-1")
        assert child_h is not None
        assert child_h.parent_ids == ["H-ATOMIC-1"]

        # 4. Log anomaly with auxiliary assumptions (Duhem-Quine attribution -> BLOCKED)
        test_args_anomaly = [
            "epires",
            "log-evidence",
            "--hypothesis",
            "H-ATOMIC-1",
            "--claim",
            "Rerun anomaly detected with negative delta",
            "--level",
            "E3",
            "--delta",
            "-0.020",
            "--falsified",
            "--assumptions",
            "AUX_SAMPLING,AUX_SEED",
        ]
        monkeypatch.setattr(sys, "argv", test_args_anomaly)
        main()

        h_anomaly = store.get_hypothesis("H-ATOMIC-1")
        assert h_anomaly.status == HypothesisStatus.BLOCKED

        # 5. Log direct refutation without suspects -> FALSIFIED and cascades to child
        test_args_direct_falsify = [
            "epires",
            "log-evidence",
            "--hypothesis",
            "H-ATOMIC-1",
            "--claim",
            "Decisive out-of-time holdout refutation",
            "--level",
            "E3",
            "--delta",
            "-0.050",
            "--falsified",
        ]
        monkeypatch.setattr(sys, "argv", test_args_direct_falsify)
        main()

        h_fals = store.get_hypothesis("H-ATOMIC-1")
        child_blocked = store.get_hypothesis("H-CHILD-1")
        assert h_fals.status == HypothesisStatus.FALSIFIED
        assert child_blocked.status == HypothesisStatus.BLOCKED
