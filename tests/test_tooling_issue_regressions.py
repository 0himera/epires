"""Regressions for the tooling defects recorded as EP-001 through EP-013."""

from __future__ import annotations

import hashlib
import sqlite3
import sys

import pytest
from pydantic import ValidationError

from epires_core.cli import main
from epires_core.config import EpiresProjectConfig
from epires_core.criteria import parse_falsification_criteria
from epires_core.gates import check_g1
from epires_core.models import EvidenceClaim, EvidenceLevel, ExperimentNode, HypothesisNode, HypothesisStatus
from epires_core.store import EpiresStore


def _hypothesis(h_id: str, *, criteria: str = "score < 0.1", target: EvidenceLevel = EvidenceLevel.E2):
    return HypothesisNode(
        id=h_id,
        title=h_id,
        a_priori_mechanism="mechanism",
        falsification_criteria=criteria,
        target_evidence_level=target,
    )


def _project(tmp_path):
    EpiresProjectConfig(project_name="regression").save(tmp_path)
    return EpiresStore(db_path=tmp_path / ".epires" / "hypotheses.db", trace_md_path=None)


def test_log_evidence_help_renders(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["epires", "log-evidence", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "--ci" in capsys.readouterr().out


def test_cli_status_override_preserves_promoted_level(monkeypatch, tmp_path):
    store = _project(tmp_path)
    store.register_hypothesis(_hypothesis("H-STATUS"), emit_trace=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "epires",
            "log-evidence",
            "-H",
            "H-STATUS",
            "-c",
            "descriptive result",
            "-l",
            "E2",
            "--status",
            "IN_PROGRESS",
        ],
    )
    main()
    saved = store.get_hypothesis("H-STATUS")
    assert saved.current_evidence_level == EvidenceLevel.E2
    assert saved.status == HypothesisStatus.IN_PROGRESS


def test_cli_hash_binds_artifact_and_persists_commit(monkeypatch, tmp_path):
    store = _project(tmp_path)
    store.register_hypothesis(_hypothesis("H-PROV"), emit_trace=False)
    artifact = tmp_path / "result.json"
    artifact.write_text('{"score": 1}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "epires",
            "log-evidence",
            "-H",
            "H-PROV",
            "-c",
            "bound result",
            "--artifact",
            "result.json",
            "--commit",
            "abc123",
        ],
    )
    main()
    evidence = store.get_evidence_for_hypothesis("H-PROV")[0]
    assert evidence.artifact_hash == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert evidence.commit_hash == "abc123"


def test_low_level_evidence_cannot_trigger_quantitative_falsifier(tmp_path):
    store = EpiresStore(db_path=tmp_path / "criteria.db", trace_md_path=None)
    store.register_hypothesis(_hypothesis("H-LEVEL", criteria="score < 0.10"), emit_trace=False)
    evidence, _ = store.log_evidence(
        EvidenceClaim(
            id="EV-LEVEL",
            hypothesis_id="H-LEVEL",
            evidence_level=EvidenceLevel.E1,
            metric_name="score",
            metric_value=0.05,
        ),
        emit_trace=False,
    )
    assert evidence.falsification_triggered is False
    assert store.get_hypothesis("H-LEVEL").status != HypothesisStatus.FALSIFIED
    assert parse_falsification_criteria("ordered top-10 exact")[0].operator == "text_match"
    assert parse_falsification_criteria("Recall@10 < 0.95")[0].metric == "Recall@10"


def test_auto_falsification_can_be_disabled_for_numeric_provenance(tmp_path):
    store = EpiresStore(db_path=tmp_path / "no-auto.db", trace_md_path=None)
    store.register_hypothesis(_hypothesis("H-NO-AUTO", criteria="score < 0.10"), emit_trace=False)
    evidence, _ = store.log_evidence(
        EvidenceClaim(
            id="EV-NO-AUTO",
            hypothesis_id="H-NO-AUTO",
            evidence_level=EvidenceLevel.E3,
            metric_name="score",
            metric_value=0.05,
        ),
        emit_trace=False,
        auto_falsification=False,
    )
    assert evidence.falsification_triggered is False


def test_evidence_model_rejects_unknown_provenance_fields():
    with pytest.raises(ValidationError):
        EvidenceClaim(hypothesis_id="H", undeclared_provenance="silently lost")


def test_g1_requires_three_distinct_registered_seeds():
    hypothesis = _hypothesis("H-SEEDS")
    evidence = [EvidenceClaim(id=f"EV-{i}", hypothesis_id="H-SEEDS") for i in range(5)]
    no_runs = []
    duplicate_runs = [
        ExperimentNode(id=f"X-{i}", hypothesis_id="H-SEEDS", name="run", script_path="run.py", parameters={"seed": 7})
        for i in range(3)
    ]
    distinct_runs = [
        ExperimentNode(id=f"Y-{i}", hypothesis_id="H-SEEDS", name="run", script_path="run.py", parameters={"seed": i})
        for i in range(3)
    ]
    assert check_g1(evidence, hypothesis, experiments=no_runs) is False
    assert check_g1(evidence, hypothesis, experiments=duplicate_runs) is False
    assert check_g1(evidence, hypothesis, experiments=distinct_runs) is True


def test_child_registered_after_parent_falsification_is_blocked(tmp_path):
    store = EpiresStore(db_path=tmp_path / "dag.db", trace_md_path=None)
    store.register_hypothesis(_hypothesis("PARENT", target=EvidenceLevel.E1), emit_trace=False)
    store.log_evidence(
        EvidenceClaim(id="EV-PARENT", hypothesis_id="PARENT", falsification_triggered=True),
        emit_trace=False,
    )
    child = _hypothesis("CHILD")
    child.parent_ids = ["PARENT"]
    store.register_hypothesis(child, emit_trace=False)
    assert store.get_hypothesis("CHILD").status == HypothesisStatus.BLOCKED
    store.log_evidence(
        EvidenceClaim(id="EV-CHILD", hypothesis_id="CHILD", evidence_level=EvidenceLevel.E2),
        emit_trace=False,
    )
    assert store.get_hypothesis("CHILD").status == HypothesisStatus.BLOCKED


def test_row_only_append_changes_only_evidence_table(tmp_path):
    db = tmp_path / "row-only.db"
    store = EpiresStore(db_path=db, trace_md_path=None)
    store.register_hypothesis(_hypothesis("H-ROW"), emit_trace=False)

    def snapshot():
        with sqlite3.connect(db) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
                if row[0] != "evidence"
            ]
            return {table: sorted(map(repr, conn.execute(f'SELECT * FROM "{table}"').fetchall())) for table in tables}

    before = snapshot()
    _, report = store.append_evidence_row_only(EvidenceClaim(id="EV-ROW", hypothesis_id="H-ROW", claim="authorization"))
    assert snapshot() == before
    assert report == {
        "changed_tables": ["evidence"],
        "inserted_evidence_ids": ["EV-ROW"],
        "graph_updated": False,
        "trace_emitted": False,
    }


def test_failed_cli_audit_exits_nonzero(monkeypatch, tmp_path):
    store = _project(tmp_path)
    store.register_hypothesis(_hypothesis("H-AUDIT"), emit_trace=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["epires", "audit", "-H", "H-AUDIT"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
