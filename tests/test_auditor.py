"""Tests for S3* independent auditor. No real LLM calls."""

from unittest import mock

from epires_core.auditor import audit_prompt, independent_audit
from epires_core.models import EvidenceClaim, EvidenceLevel, ExperimentNode, HypothesisNode, HypothesisStatus, SourceConfidence
from epires_core.store import EpiresStore


def _store(tmp_path):
    return EpiresStore(db_path=tmp_path / "t.db", vsa_dim=1000)


def _confirmed_h(store, h_id="H_AUD"):
    store.register_hypothesis(HypothesisNode(
        id=h_id, title="T", a_priori_mechanism="M", falsification_criteria="F",
    ))
    store.update_hypothesis(h_id, status=HypothesisStatus.CONFIRMED)
    for i, lvl in enumerate(["E2", "E2", "E3"], 1):
        store.log_evidence(EvidenceClaim(
            id=f"ev{i}", hypothesis_id=h_id, evidence_level=EvidenceLevel(lvl),
            source_confidence=SourceConfidence.V, claim=f"c{i}",
            citation_or_path=f"https://x.example/{i}",
        ))
    store.register_experiment(ExperimentNode(
        id="X1", hypothesis_id=h_id, name="X1", script_path="x.py",
        metrics={"rmsle": 1.5},
    ))


def test_audit_prompt_contains_criteria_and_evidence(tmp_path):
    store = _store(tmp_path)
    _confirmed_h(store)
    h = store.get_hypothesis("H_AUD")
    p = audit_prompt(h, store.get_evidence_for_hypothesis("H_AUD"), store.list_experiments("H_AUD"))
    assert "T" in p and "F" in p  # title + falsification criteria
    assert "c1" in p and "c3" in p
    assert "verdict" in p and "violations" in p
    assert "X1" in p and "rmsle" in p


def test_inconclusive_on_unreachable_url(tmp_path):
    store = _store(tmp_path)
    _confirmed_h(store)
    res = independent_audit("H_AUD", store, model="m", base_url="http://127.0.0.1:1/v1", api_key="k")
    assert res["verdict"] == "inconclusive"
    assert "error" in res
    assert [t for t in store.list_traces() if t.action == "S3_AUDIT"]


def test_deterministic_fail_without_llm(tmp_path):
    # broken provenance: no evidence/experiment -> G-gate violation; LLM must never be called
    store = _store(tmp_path)
    store.register_hypothesis(HypothesisNode(
        id="H_BAD", title="T", a_priori_mechanism="M", falsification_criteria="F",
    ))
    store.update_hypothesis("H_BAD", status=HypothesisStatus.CONFIRMED)

    def boom(*a, **kw):  # any LLM attempt explodes the test
        raise AssertionError("LLM called despite deterministic failure")

    import httpx

    with mock.patch.object(httpx, "post", boom):
        res = independent_audit("H_BAD", store, model="m", base_url="http://127.0.0.1:1/v1")
    assert res["verdict"] == "fail"
    assert res["source"] == "deterministic"
    assert res["violations"]
    traces = [t for t in store.list_traces() if t.action == "S3_AUDIT"]
    assert len(traces) == 1
