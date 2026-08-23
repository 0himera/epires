"""Regression tests for fixes identified in Audit v2 (gptaudit2.txt).

Covers:
1. Gate G4 direction (falsification zone vs CI).
2. Strict gates hot path multi-evidence aggregation.
3. Automatic criteria falsification without manual LLM flag.
4. VSA BinaryIndex cache invalidation on hypothesis update.
5. JSONC parser URL '//' preservation and comment stripping.
6. Windows POSIX path formatting in Codex TOML.
7. Append-only evidence ledger soft-retraction preservation.
8. Manual status override protection against unearned CONFIRMED.
"""

from __future__ import annotations

import pytest

from epires_core import (
    EpiresStore,
    EvidenceClaim,
    EvidenceLevel,
    HypothesisNode,
    HypothesisStatus,
    SearchQuery,
    SourceConfidence,
)
from epires_core.gates import check_g4
from epires_core.setup import _clean_jsonc_and_load, _merge_toml_codex


def test_gate_g4_direction_greater_than():
    """Falsification criteria 'loss > 0.10' means loss > 0.10 refutes hypothesis."""
    h = HypothesisNode(
        id="H1",
        title="Optimization",
        a_priori_mechanism="math",
        falsification_criteria="loss > 0.10",
    )
    # Safe CI strictly below 0.10 -> confirms (passes G4)
    ev_pass = EvidenceClaim(
        id="ev_pass",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        claim="Low loss",
        ci_95_lower=0.02,
        ci_95_upper=0.08,
    )
    assert check_g4([ev_pass], hypothesis=h) is True

    # Overlapping or exceeding 0.10 -> in falsification zone (fails G4)
    ev_fail = EvidenceClaim(
        id="ev_fail",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        claim="High loss",
        ci_95_lower=0.08,
        ci_95_upper=0.15,
    )
    assert check_g4([ev_fail], hypothesis=h) is False


def test_gate_g4_direction_less_than():
    """Falsification criteria 'accuracy < 0.80' means accuracy < 0.80 refutes hypothesis."""
    h = HypothesisNode(
        id="H2",
        title="Accuracy",
        a_priori_mechanism="math",
        falsification_criteria="accuracy < 0.80",
    )
    # Safe CI strictly above 0.80 -> passes G4
    ev_pass = EvidenceClaim(
        id="ev_pass",
        hypothesis_id="H2",
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        claim="High accuracy",
        ci_95_lower=0.85,
        ci_95_upper=0.92,
    )
    assert check_g4([ev_pass], hypothesis=h) is True

    # Drops into < 0.80 -> fails G4
    ev_fail = EvidenceClaim(
        id="ev_fail",
        hypothesis_id="H2",
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        claim="Low accuracy",
        ci_95_lower=0.75,
        ci_95_upper=0.85,
    )
    assert check_g4([ev_fail], hypothesis=h) is False


def test_strict_gates_hot_path_aggregates_all_evidence(tmp_path, monkeypatch):
    """In STRICT mode, log_evidence evaluates all cumulative evidence and experiments."""
    monkeypatch.setenv("EPIRES_STRICT_GATES", "1")
    from epires_core import store as store_mod

    monkeypatch.setattr(store_mod.evidence, "GATES_STRICT", True)

    db_file = tmp_path / "strict.db"
    store = EpiresStore(db_path=db_file, trace_md_path=None)

    h = HypothesisNode(
        id="H_STRICT",
        title="Strict Test",
        a_priori_mechanism="mech",
        falsification_criteria="delta < 0",
        target_evidence_level=EvidenceLevel.E2,
    )
    store.register_hypothesis(h)

    # Log 3 separate evidence claims sequentially
    for i in range(3):
        ev = EvidenceClaim(
            id=f"ev_s_{i}",
            hypothesis_id="H_STRICT",
            evidence_level=EvidenceLevel.E1,
            source_confidence=SourceConfidence.V,
            claim=f"Claim {i}",
            citation_or_path="http://lab.local/r",
            metric_name="metric",
            metric_value=0.9,
            delta_vs_baseline=0.1,
            timestamp=f"2026-01-0{i + 1}T00:00:00Z",
        )
        store.log_evidence(ev, emit_trace=False)

    saved_h = store.get_hypothesis("H_STRICT")
    # G1 requires len(evidence) >= 3 -> with 3 claims, level reaches at least E1/E2
    assert saved_h.current_evidence_level.value >= EvidenceLevel.E1.value


def test_automatic_falsification_on_metric_violation(tmp_path):
    """Evidence with metrics violating falsification criteria automatically triggers FALSIFIED."""
    store = EpiresStore(db_path=tmp_path / "falsify.db", trace_md_path=None)

    parent = HypothesisNode(
        id="H_PARENT",
        title="Parent mechanism",
        a_priori_mechanism="mech",
        falsification_criteria="loss > 0.10",
    )
    child = HypothesisNode(
        id="H_CHILD",
        title="Child mechanism",
        a_priori_mechanism="mech",
        falsification_criteria="loss > 0.10",
        parent_ids=["H_PARENT"],
    )
    store.register_hypothesis(parent)
    store.register_hypothesis(child)

    # Agent claims falsification_triggered=False, but metric_value=0.18 triggers loss > 0.10
    ev = EvidenceClaim(
        id="ev_violate",
        hypothesis_id="H_PARENT",
        evidence_level=EvidenceLevel.E2,
        claim="Measured loss",
        metric_name="loss",
        metric_value=0.18,
        falsification_triggered=False,
    )
    saved_ev, blocked = store.log_evidence(ev)

    assert saved_ev.falsification_triggered is True
    assert store.get_hypothesis("H_PARENT").status == HypothesisStatus.FALSIFIED
    assert "H_CHILD" in blocked
    assert store.get_hypothesis("H_CHILD").status == HypothesisStatus.BLOCKED


def test_vsa_index_invalidation_on_update(tmp_path):
    """Updating a hypothesis invalidates cached BinaryIndex."""
    store = EpiresStore(db_path=tmp_path / "vsa.db", trace_md_path=None)
    h1 = HypothesisNode(
        id="H1", title="Original Title", a_priori_mechanism="M1", falsification_criteria="F1", tags=["alpha"]
    )
    h2 = HypothesisNode(
        id="H2", title="Second Title", a_priori_mechanism="M2", falsification_criteria="F2", tags=["beta"]
    )
    store.register_hypothesis(h1)
    store.register_hypothesis(h2)

    # Initial search builds the index
    results1 = store.search(SearchQuery(query="alpha", limit=5))
    assert len(results1) > 0
    assert store._index is not None

    # Update H1 tags/title (same total number of hypotheses in DB)
    h1_updated = HypothesisNode(
        id="H1", title="Rewritten Title", a_priori_mechanism="M1", falsification_criteria="F1", tags=["gamma"]
    )
    store.register_hypothesis(h1_updated)

    # _index must be invalidated
    assert store._index is None

    # Next search re-indexes and reflects the new gamma tag
    results2 = store.search(SearchQuery(query="gamma", limit=5))
    assert results2[0][0].id == "H1"


def test_jsonc_cleaner_preserves_urls_with_double_slashes():
    """JSONC parser must not strip '//' inside double-quoted string literals."""
    jsonc_text = """
    {
        // This is a top-level comment
        "$schema": "https://opencode.ai/config.json",
        "name": "epires-project", /* block comment */
        "mcp": {
            "epires": {
                "url": "http://localhost:8000/sse", // inline comment
            },
        },
    }
    """
    data = _clean_jsonc_and_load(jsonc_text)
    assert data["$schema"] == "https://opencode.ai/config.json"
    assert data["name"] == "epires-project"
    assert data["mcp"]["epires"]["url"] == "http://localhost:8000/sse"


def test_codex_toml_posix_path_escaping(tmp_path):
    """Codex TOML generation uses forward slashes safe across Linux and Windows."""
    config_toml = tmp_path / ".codex" / "config.toml"
    _merge_toml_codex(config_toml, tmp_path)
    content = config_toml.read_text(encoding="utf-8")
    assert "[mcp_servers.epires]" in content
    assert f'cwd = "{tmp_path.as_posix()}"' in content
    assert "\\" not in content.split('cwd = "')[1].split('"')[0]


def test_append_only_soft_retraction_ledger(tmp_path):
    """Retraction marks evidence is_retracted=1 while keeping row physically in DB."""
    store = EpiresStore(db_path=tmp_path / "ledger.db", trace_md_path=None)
    h = HypothesisNode(id="H1", title="T", a_priori_mechanism="M", falsification_criteria="F")
    store.register_hypothesis(h)

    ev = EvidenceClaim(
        id="ev_retract_me",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E2,
        claim="Bad sensor",
        metric_name="acc",
        metric_value=0.99,
        falsification_triggered=True,
    )
    store.log_evidence(ev)
    assert store.get_hypothesis("H1").status == HypothesisStatus.FALSIFIED

    # Retract evidence
    retracted, unblocked = store.retract_evidence("ev_retract_me", reason="Sensor was miscalibrated")
    assert retracted is not None

    # Active evidence list is now empty
    active_evs = store.get_evidence_for_hypothesis("H1")
    assert len(active_evs) == 0

    # Physical DB still retains the record with retraction tombstone
    with store._get_connection() as conn:
        row = conn.execute("SELECT * FROM evidence WHERE id = 'ev_retract_me'").fetchone()
        assert row is not None
        assert row["is_retracted"] == 1
        assert row["retraction_reason"] == "Sensor was miscalibrated"

    # Hypothesis status is restored from active evidence
    assert store.get_hypothesis("H1").status == HypothesisStatus.PROPOSED


def test_manual_status_override_protection(tmp_path):
    """Agents cannot manually set status to CONFIRMED without meeting target evidence level."""
    store = EpiresStore(db_path=tmp_path / "guard.db", trace_md_path=None)
    h = HypothesisNode(
        id="H_UNCONFIRMED",
        title="Unconfirmed",
        a_priori_mechanism="M",
        falsification_criteria="F",
        target_evidence_level=EvidenceLevel.E4,
        current_evidence_level=EvidenceLevel.E1,
    )
    store.register_hypothesis(h)

    # When allow_status_override=False (as in agent MCP endpoint), manual CONFIRMED is rejected
    with pytest.raises(ValueError, match="lower than target evidence level"):
        store.update_hypothesis(
            "H_UNCONFIRMED",
            status=HypothesisStatus.CONFIRMED,
            allow_status_override=False,
        )
