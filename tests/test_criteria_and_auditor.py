"""Unit tests for structured falsification criteria parsing and auditor structured outputs."""

from epires_core.models import (
    AuditVerdict,
    EvidenceClaim,
    EvidenceLevel,
    FalsificationCondition,
    HypothesisNode,
    SourceConfidence,
)
from epires_core.criteria import parse_falsification_criteria, evaluate_falsification_condition
from epires_core.gates import _thr, check_g4
from epires_core.auditor import parse_audit_verdict, _parse_json


class TestFalsificationCriteriaParsing:
    def test_parse_empty(self):
        assert parse_falsification_criteria("") == []
        assert parse_falsification_criteria(None) == []

    def test_parse_single_comparisons(self):
        c1 = parse_falsification_criteria("delta < 0")
        assert len(c1) == 1
        assert c1[0].operator == "<"
        assert c1[0].threshold == 0.0
        assert c1[0].metric == "delta"

        c2 = parse_falsification_criteria("Validation loss delta > 0.05")
        assert len(c2) == 1
        assert c2[0].operator == ">"
        assert c2[0].threshold == 0.05
        assert "Validation loss delta" in (c2[0].metric or "")

        c3 = parse_falsification_criteria("accuracy >= 0.95")
        assert len(c3) == 1
        assert c3[0].operator == ">="
        assert c3[0].threshold == 0.95

    def test_parse_units(self):
        c_ms = parse_falsification_criteria("measured latency_ms >= 100ms")
        assert len(c_ms) >= 1
        assert c_ms[0].operator == ">="
        assert c_ms[0].threshold == 100.0
        assert c_ms[0].unit == "ms"

        c_pp = parse_falsification_criteria("delta < -2pp")
        assert len(c_pp) >= 1
        assert c_pp[0].operator == "<"
        assert c_pp[0].threshold == -2.0
        assert c_pp[0].unit == "pp"

        c_pct = parse_falsification_criteria("energy_cost increase > 5%")
        assert len(c_pct) >= 1
        assert c_pct[0].operator == ">"
        assert c_pct[0].threshold == 5.0
        assert c_pct[0].unit == "%"

    def test_parse_compound_criteria(self):
        text = "Validation loss delta > 0.05 or RMSLE degradation"
        conds = parse_falsification_criteria(text)
        assert len(conds) == 2
        assert conds[0].operator == ">"
        assert conds[0].threshold == 0.05
        assert conds[1].operator == "degradation"

    def test_parse_qualitative_criteria(self):
        conds = parse_falsification_criteria("drift > 0.1 or performance regression")
        assert len(conds) == 2
        assert conds[0].threshold == 0.1
        assert conds[1].operator == "degradation"


class TestConditionEvaluation:
    def test_evaluate_greater_than(self):
        cond = FalsificationCondition(metric="val_loss", operator=">", threshold=0.05)
        # Triggered (val_loss = 0.08 > 0.05)
        assert evaluate_falsification_condition(cond, metric_name="val_loss", metric_value=0.08) is True
        # Not triggered (val_loss = 0.02 <= 0.05)
        assert evaluate_falsification_condition(cond, metric_name="val_loss", metric_value=0.02) is False
        # Mismatched metric
        assert evaluate_falsification_condition(cond, metric_name="accuracy", metric_value=0.9) is None

    def test_evaluate_less_than_delta(self):
        cond = FalsificationCondition(metric="delta", operator="<", threshold=-0.01)
        assert evaluate_falsification_condition(cond, delta_vs_baseline=-0.05) is True
        assert evaluate_falsification_condition(cond, delta_vs_baseline=0.02) is False

    def test_evaluate_degradation(self):
        cond = FalsificationCondition(operator="degradation", threshold=0.0)
        assert evaluate_falsification_condition(cond, delta_vs_baseline=-0.02) is True
        assert evaluate_falsification_condition(cond, delta_vs_baseline=0.05) is False
        assert evaluate_falsification_condition(cond, delta_vs_baseline=None) is None


class TestGatesWithStructuredCriteria:
    def test_thr_extraction(self):
        assert _thr("Validation loss delta > 0.05") == 0.05
        assert _thr("sigma > 5pp") == 5.0
        assert _thr("delta < -2pp") == -2.0
        assert _thr("") is None

    def test_check_g4_precision(self):
        h = HypothesisNode(
            id="H1",
            title="Test",
            a_priori_mechanism="m",
            falsification_criteria="loss > 0.10",
        )
        ev_pass = EvidenceClaim(
            id="ev1",
            hypothesis_id="H1",
            evidence_level=EvidenceLevel.E3,
            source_confidence=SourceConfidence.V,
            claim="Significant pass",
            ci_95_lower=0.15,
            ci_95_upper=0.25,
        )
        ev_fail = EvidenceClaim(
            id="ev2",
            hypothesis_id="H1",
            evidence_level=EvidenceLevel.E3,
            source_confidence=SourceConfidence.V,
            claim="Borderline pass",
            ci_95_lower=0.05,
            ci_95_upper=0.25,
        )
        assert check_g4([ev_pass], hypothesis=h) is True
        assert check_g4([ev_fail], hypothesis=h) is False


class TestAuditorStructuredOutputs:
    def test_parse_clean_json(self):
        raw = '{"verdict": "pass", "reason": "All checks passed", "violations": []}'
        verdict = parse_audit_verdict(raw)
        assert isinstance(verdict, AuditVerdict)
        assert verdict.verdict == "pass"
        assert verdict.reason == "All checks passed"
        assert verdict.violations == []

    def test_parse_markdown_code_block(self):
        raw = """```json
{
  "verdict": "fail",
  "reason": "Missing holdout set",
  "violations": ["G2 violation", "Leakage suspected"]
}
```"""
        verdict = parse_audit_verdict(raw)
        assert verdict.verdict == "fail"
        assert verdict.reason == "Missing holdout set"
        assert len(verdict.violations) == 2
        assert "G2 violation" in verdict.violations

    def test_parse_noisy_output(self):
        raw = """Here is my review as S3* auditor:
{
  "verdict": "flag",
  "reason": "Single seed used",
  "violations": ["G1: seed variance < 3"]
}
Hope this helps!"""
        verdict = parse_audit_verdict(raw)
        assert verdict.verdict == "flag"
        assert "Single seed" in (verdict.reason or "")
        assert len(verdict.violations) == 1

    def test_parse_invalid_falls_back_to_inconclusive(self):
        raw = "Sorry, I cannot review this request."
        verdict = parse_audit_verdict(raw)
        assert verdict.verdict == "inconclusive"
        assert "Failed to parse" in (verdict.reason or "")

    def test_backwards_compatible_dict_helper(self):
        raw = '{"verdict": "pass", "reason": "OK", "violations": []}'
        res = _parse_json(raw)
        assert isinstance(res, dict)
        assert res["verdict"] == "pass"
        assert res["reason"] == "OK"
