"""Tests for epistemic machinery: gates, argumentation, TMS, calibration, scoring, stigmergy, audit."""

import sqlite3

import pytest

from epires_core.algedonic import check_triggers
from epires_core.argumentation import (
    bipolar_to_attacks,
    grounded_labeling,
    level_to_standard,
    proof_standard_check,
    weights_from_evidence,
)
from epires_core.audit import audit_hypothesis
from epires_core.calibration import brier_score, calibrated_weight, fit_platt, platt_scale
from epires_core.conversation import add_turn, init_conversation_tables, open_conversation, resolve_conversation
from epires_core.gates import compute_level
from epires_core.models import EvidenceClaim, EvidenceLevel, ExperimentNode, HypothesisNode, TraceEntry
from epires_core.scoring import gupta_test, score_candidates
from epires_core.stigmergy import bateson_filter
from epires_core.store import EpiresStore, RelationEdge, RelationType
from epires_core.tms import add_justification, add_premise, init_tms_tables, propagate_status


def make_h(hid: str = "H1", criteria: str = "metric > 0.5") -> HypothesisNode:
    return HypothesisNode(
        id=hid, title=f"hyp {hid}", a_priori_mechanism="m", falsification_criteria=criteria
    )


def make_ev(hid: str, eid: str, **kw) -> EvidenceClaim:
    return EvidenceClaim(
        id=eid,
        hypothesis_id=hid,
        evidence_level=EvidenceLevel.E1,
        claim="claim",
        citation_or_path="http://example.org/src",
        metric_name="acc",
        metric_value=0.9,
        **kw,
    )


@pytest.fixture()
def store(tmp_path):
    return EpiresStore(db_path=tmp_path / "t.db", trace_md_path=None)


# --- gates ---


def test_gates_full_evidence_reaches_e2():
    h = make_h()
    evs = [make_ev("H1", f"ev{i}") for i in range(3)]
    assert compute_level(evs, h) == EvidenceLevel.E2


def test_gates_no_evidence_is_e0():
    assert compute_level([], make_h()) == EvidenceLevel.E0


def test_gates_ci95_above_threshold_reaches_e4():
    h = make_h(criteria="metric > 0.5")
    evs = [
        make_ev("H1", f"ev{i}", ci_95_lower=0.7, ci_95_upper=0.9, prediction="acc > 0.5", assumption_ids=["a1"], timestamp="2026-01-01T00:00:00Z")
        for i in range(3)
    ]
    exp = ExperimentNode(
        id="X1", hypothesis_id="H1", name="n", script_path="s.py",
        parameters={"held_out_hash": "abc"}, created_at="",
    )
    assert compute_level(evs, h, experiments=[exp]) == EvidenceLevel.E4


def test_gates_ci95_below_threshold_caps_at_e3():
    h = make_h(criteria="metric > 0.5")
    evs = [
        make_ev("H1", f"ev{i}", ci_95_lower=0.3, ci_95_upper=0.4, prediction="acc > 0.5", timestamp="2026-01-01T00:00:00Z")
        for i in range(3)
    ]
    exp = ExperimentNode(
        id="X1", hypothesis_id="H1", name="n", script_path="s.py",
        parameters={"held_out_hash": "abc"}, created_at="",
    )
    assert compute_level(evs, h, experiments=[exp]) == EvidenceLevel.E3


# --- argumentation ---


def test_grounded_labeling_single_attack():
    label = grounded_labeling([("a", "b")])
    assert label["a"] == "IN"
    assert label["b"] == "OUT"


def test_grounded_labeling_mutual_attack_undec():
    label = grounded_labeling([("a", "b"), ("b", "a")])
    assert label["a"] == "UNDEC"
    assert label["b"] == "UNDEC"


def test_bipolar_conflict_propagates_through_support():
    attacks = bipolar_to_attacks(supports=[("b", "c")], conflicts=[("a", "b")])
    assert ("a", "c") in attacks
    assert ("a", "b") in attacks


def test_proof_standards_carneades():
    e2 = make_ev("claim", "e1")
    e3 = make_ev("claim", "e2")
    e2.evidence_level = EvidenceLevel.E2
    e3.evidence_level = EvidenceLevel.E3
    weights = weights_from_evidence([e2, e3])
    assert weights["claim"] == pytest.approx(1.5)
    attacks = [("attacker", "claim")]
    assert proof_standard_check("claim", {"claim": 1.5, "attacker": 0.6}, attacks, "preponderance") is True
    assert proof_standard_check("claim", {"claim": 1.1, "attacker": 0.6}, attacks, "preponderance") is True
    assert proof_standard_check("claim", {"claim": 1.5, "attacker": 0.8}, attacks, "clear_and_convincing") is False
    assert proof_standard_check("claim", {"claim": 1.5}, [], "beyond_reasonable_doubt") is True
    with pytest.raises(ValueError):
        proof_standard_check("claim", {"claim": 1.5}, [], "scintilla")
    assert level_to_standard("E2") == "preponderance"
    assert level_to_standard("E4") == "clear_and_convincing"
    assert level_to_standard("E5") == "beyond_reasonable_doubt"


# --- tms ---


def test_tms_propagate_and_retract():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_tms_tables(conn)
    add_premise("A", conn)
    add_justification("B", ["A"], conn)
    status = propagate_status(conn)
    assert status["A"] == "IN"
    assert status["B"] == "IN"
    conn.execute("DELETE FROM justifications WHERE id='p_A'")
    conn.commit()
    status = propagate_status(conn)
    assert status["A"] == "OUT"
    assert status["B"] == "OUT"


# --- calibration ---


def test_brier_score_perfect_case():
    assert brier_score(0.8, 1) == pytest.approx(0.04)


def test_fit_platt_reduces_error():
    records = [(0.6, 1)] * 20 + [(0.4, 0)] * 20
    a, b = fit_platt(records)
    before = sum((p - y) ** 2 for p, y in records) / len(records)
    after = sum((platt_scale(p, a, b) - y) ** 2 for p, y in records) / len(records)
    assert after < before


def test_calibrated_weight_skeptical_prior_without_ledger():
    assert calibrated_weight("agent-x", 0.9, {}) == 0.5


# --- scoring ---


def test_score_candidates_sorted_descending():
    candidates = [
        {"id": "low", "eig": 0.1},
        {"id": "high", "eig": 0.9},
        {"id": "mid", "eig": 0.5},
    ]
    scored = score_candidates(candidates, {"H1": 1.0})
    scores = [s for _, s in scored]
    assert scores == sorted(scores, reverse=True)
    assert scored[0][0] == "high"


def test_gupta_test_sensitive_ranking():
    candidates = [
        {"id": "c1", "eig": 0.9},
        {"id": "c2", "eig": 0.5},
        {"id": "c3", "eig": 0.1},
    ]
    assert gupta_test(candidates, {"H1": 1.0}) is True


# --- stigmergy / conversation ---


def test_bateson_filter_keeps_falsification_only():
    hot = make_ev("H1", "ev_hot", falsification_triggered=True)
    cold = TraceEntry(timestamp="2026-01-01T00:00:00Z", action="NOTE", summary="routine note")
    assert bateson_filter(hot) is True
    assert bateson_filter(cold) is False


def test_conversation_lifecycle_in_memory():
    conn = sqlite3.connect(":memory:")
    init_conversation_tables(conn)
    cid = open_conversation("H1", "H2", conn)
    assert conn.execute("SELECT status FROM conversations WHERE id=?", (cid,)).fetchone()[0] == "asserted"
    add_turn(cid, "agent-a", "my mechanism is right", conn)
    assert conn.execute("SELECT status FROM conversations WHERE id=?", (cid,)).fetchone()[0] == "in_conversation"
    resolve_conversation(cid, "merge", "H9", conn)
    assert conn.execute("SELECT status FROM conversations WHERE id=?", (cid,)).fetchone()[0] == "resolved"


# --- store integration ---


def test_store_registers_tms_and_conversation(store):
    store.register_hypothesis(make_h("H1"))
    h2 = make_h("H2")
    h2.parent_ids = ["H1"]
    store.register_hypothesis(h2)
    store.add_relation(RelationEdge(source_id="H1", target_id="H2", relation_type=RelationType.CONFLICTS_WITH))

    with store._get_connection() as conn:
        conv = conn.execute(
            "SELECT a_id, b_id FROM conversations WHERE a_id='H1' AND b_id='H2'"
        ).fetchone()
        assert conv is not None
        just = conn.execute(
            "SELECT id FROM justifications WHERE consequent='H2' AND id LIKE 'j_%'"
        ).fetchone()
        assert just is not None
        premise = conn.execute(
            "SELECT id FROM justifications WHERE consequent='H1' AND id='p_H1'"
        ).fetchone()
        assert premise is not None


# --- audit / algedonic ---


def test_audit_passes_on_clean_hypothesis(store):
    store.register_hypothesis(make_h("H1"))
    for i in range(3):
        store.log_evidence(make_ev("H1", f"ev{i}"))
    store.register_experiment(
        ExperimentNode(id="X1", hypothesis_id="H1", name="n", script_path="s.py")
    )
    report = audit_hypothesis("H1", store)
    assert report["passed"] is True
    assert report["violations"] == []


def test_algedonic_contradiction_trigger(store):
    store.register_hypothesis(make_h("H1"))
    store.log_evidence(make_ev("H1", "ev_pro"))
    store.log_evidence(make_ev("H1", "ev_con", falsification_triggered=True))
    triggers = check_triggers(store)
    assert any(t["trigger"] == "contradiction" and t["node_id"] == "H1" for t in triggers)


# --- Duhem-Quine anomaly attribution ---


def test_single_falsification_auxiliary_blame_vs_inconclusive(tmp_path):
    # auxiliary blame: assumption present, no independent repeats -> BLOCKED, child spared
    store = EpiresStore(db_path=tmp_path / "t.db", trace_md_path=None)
    store.register_hypothesis(make_h("H1"))
    store.register_hypothesis(make_h("H2"))
    store.add_relation(RelationEdge(source_id="H2", target_id="H1", relation_type=RelationType.DEPENDS_ON))
    store.log_evidence(make_ev("H1", "ev_a", falsification_triggered=True, assumption_ids=["A1"]))
    assert store.get_hypothesis("H1").status.value == "BLOCKED"
    assert store.get_hypothesis("H2").status.value == "PROPOSED"

    # inconclusive: no assumptions -> old strict path FALSIFIED + cascade
    store.register_hypothesis(make_h("H3"))
    store.register_hypothesis(make_h("H4"))
    store.add_relation(RelationEdge(source_id="H4", target_id="H3", relation_type=RelationType.DEPENDS_ON))
    store.log_evidence(make_ev("H3", "ev_none", falsification_triggered=True))
    assert store.get_hypothesis("H3").status.value == "FALSIFIED"
    assert store.get_hypothesis("H4").status.value == "BLOCKED"


def test_independent_falsifications_implicate_hypothesis(tmp_path):
    from epires_core.attribution import attribute_anomaly

    store = EpiresStore(db_path=tmp_path / "t.db", trace_md_path=None)
    store.register_hypothesis(make_h("H5"))
    store.register_hypothesis(make_h("H6"))
    store.add_relation(RelationEdge(source_id="H6", target_id="H5", relation_type=RelationType.DEPENDS_ON))
    ev1 = make_ev("H5", "ev_x", falsification_triggered=True, assumption_ids=["A1"])
    ev2 = make_ev("H5", "ev_y", falsification_triggered=True, assumption_ids=["A2"])
    store.log_evidence(ev1)  # first hit -> auxiliary blame, BLOCKED
    store.log_evidence(ev2)
    assert attribute_anomaly(store.get_evidence("ev_y"), store) == "attributed:hypothesis"
    assert store.get_hypothesis("H5").status.value == "FALSIFIED"
    assert store.get_hypothesis("H6").status.value == "BLOCKED"
