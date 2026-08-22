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


def test_cli_dag_frontier_filter(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        init_workspace(target_dir=tmp_path)
        store = EpiresStore(db_path=tmp_path / ".epires" / "hypotheses.db")

        # Register confirmed parent, in_progress child, and distant archived node
        h_parent = store.register_hypothesis(
            store._row_to_hypothesis(
                {
                    "id": "H-PARENT",
                    "title": "Parent",
                    "a_priori_mechanism": "m",
                    "falsification_criteria": "c",
                    "target_evidence_level": "E3",
                    "current_evidence_level": "E3",
                    "status": "CONFIRMED",
                    "parent_ids_json": "[]",
                    "entities_json": "[]",
                    "tags_json": "[]",
                    "criteria_version": "v1",
                    "observation_context": "",
                    "created_at": "",
                    "updated_at": "",
                }
            ),
            allow_status_override=True,
            emit_trace=False,
        )
        h_active = store.register_hypothesis(
            store._row_to_hypothesis(
                {
                    "id": "H-ACTIVE",
                    "title": "Active frontier",
                    "a_priori_mechanism": "m",
                    "falsification_criteria": "c",
                    "target_evidence_level": "E3",
                    "current_evidence_level": "E1",
                    "status": "IN_PROGRESS",
                    "parent_ids_json": '["H-PARENT"]',
                    "entities_json": "[]",
                    "tags_json": "[]",
                    "criteria_version": "v1",
                    "observation_context": "",
                    "created_at": "",
                    "updated_at": "",
                }
            ),
            allow_status_override=True,
            emit_trace=False,
        )
        h_archived = store.register_hypothesis(
            store._row_to_hypothesis(
                {
                    "id": "H-ARCHIVED",
                    "title": "Archived Falsified",
                    "a_priori_mechanism": "m",
                    "falsification_criteria": "c",
                    "target_evidence_level": "E3",
                    "current_evidence_level": "E3",
                    "status": "FALSIFIED",
                    "parent_ids_json": "[]",
                    "entities_json": "[]",
                    "tags_json": "[]",
                    "criteria_version": "v1",
                    "observation_context": "",
                    "created_at": "",
                    "updated_at": "",
                }
            ),
            allow_status_override=True,
            emit_trace=False,
        )

        frontier_dag = store.export_mermaid_dag(frontier_only=True)
        assert "H-ACTIVE" in frontier_dag
        assert "H-PARENT" in frontier_dag
        assert "H-ARCHIVED" not in frontier_dag


def test_doctor_redundancy_check():
    from epires_core.doctor import run_epires_doctor

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        init_workspace(target_dir=tmp_path)

        # Create obsolete research.db
        (tmp_path / ".epires" / "research.db").write_text("", encoding="utf-8")

        checks = run_epires_doctor(project_dir=tmp_path)
        redundancy_check = next((c for c in checks if c.name == "Database Architecture Cleanliness"), None)
        assert redundancy_check is not None
        assert redundancy_check.warning is True
        assert "research.db" in redundancy_check.message


def test_cli_scaffold_and_verify_gates(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        init_workspace(target_dir=tmp_path)
        store = EpiresStore(db_path=tmp_path / ".epires" / "hypotheses.db")

        # 1. Register hypothesis
        test_args_reg = [
            "epires",
            "register",
            "--id",
            "H-SCAFFOLD-1",
            "--title",
            "Scaffold Evaluation Test",
            "--mechanism",
            "Bootstrap verification of candidate",
            "--criteria",
            "delta < 0",
            "--target-level",
            "E3",
        ]
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", test_args_reg)
        main()

        # 2. Scaffold experiment runner
        script_out = tmp_path / "scripts" / "eval_h_scaffold_1.py"
        test_args_scaffold = ["epires", "scaffold", "H-SCAFFOLD-1", "--out", str(script_out)]
        monkeypatch.setattr(sys, "argv", test_args_scaffold)
        main()

        assert script_out.exists()
        code = script_out.read_text(encoding="utf-8")
        assert "paired_bootstrap_ci" in code
        assert "H-SCAFFOLD-1" in code

        # 3. Create simulated experiment artifact
        artifact_path = tmp_path / "artifacts" / "metrics" / "h_scaffold_1.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        import json

        artifact_data = {
            "hypothesis_id": "H-SCAFFOLD-1",
            "metric_name": "RMSLE",
            "baseline_metric": 1.6885,
            "candidate_metric": 1.6845,
            "delta_vs_baseline": 0.0040,
            "ci_95_lower": 0.0015,
            "ci_95_upper": 0.0065,
            "n_samples": 1000,
        }
        artifact_path.write_text(json.dumps(artifact_data), encoding="utf-8")

        # 4. Verify gates with --apply
        test_args_verify = ["epires", "verify-gates", str(artifact_path), "--apply"]
        monkeypatch.setattr(sys, "argv", test_args_verify)
        main()

        h_verified = store.get_hypothesis("H-SCAFFOLD-1")
        assert h_verified.status == HypothesisStatus.CONFIRMED
        evs = store.get_evidence_for_hypothesis("H-SCAFFOLD-1")
        assert len(evs) == 1
        assert evs[0].delta_vs_baseline == 0.0040
        assert evs[0].ci_95_lower == 0.0015
