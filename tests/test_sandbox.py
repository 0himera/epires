"""Smoke: eval harness must be prompt-sensitive — governed passes, baseline fails on all scenarios."""

import os

import pytest

from sandbox.run_eval import load_variant, run_one
from sandbox.agents import MockAgent

SCENARIOS = ["conflicting", "planted_bug", "reward_hack"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_governed_beats_baseline(name, tmp_path):
    base = run_one(name, "baseline", "mock", results_dir=tmp_path)
    gov = run_one(name, "governed", "mock", results_dir=tmp_path)
    assert not base["success"], base
    assert gov["success"], gov


def test_planted_bug_auxiliary_blame(tmp_path):
    r = run_one("planted_bug", "governed", "mock", results_dir=tmp_path)
    assert r["false_cascade_count"] == 0
    assert r["attribution_verdicts"] == ["attributed:auxiliary:AUX_TOOL_X"]
    b = run_one("planted_bug", "baseline", "mock", results_dir=tmp_path)
    assert b["false_cascade_count"] == 2


def test_reward_hack_gate(tmp_path):
    b = run_one("reward_hack", "baseline", "mock", results_dir=tmp_path)
    assert b["claimed_level"] == "E4" and b["final_level"] == "E3"
    assert b["gate_rejected"]


def test_mock_agent_markers():
    assert MockAgent(load_variant("governed")).verify_first
    assert not MockAgent(load_variant("baseline")).verify_first


@pytest.mark.skipif(not os.environ.get("EPIRES_EVAL_MODEL"), reason="no EPIRES_EVAL_MODEL configured")
def test_llm_agent_smoke():
    from sandbox.agents import LLMAgent

    a = LLMAgent(load_variant("governed"), "test scenario")
    assert isinstance(a.respond({"kind": "anomaly", "suspects": ["A1"]}), dict)
