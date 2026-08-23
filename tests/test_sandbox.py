"""Smoke: eval harness must be prompt-sensitive — governed passes, baseline fails on all scenarios."""

import os
from pathlib import Path

import pytest

from sandbox.run_eval import load_variant, run_one
from sandbox.agents import MockAgent

SCENARIOS = [
    "conflicting",
    "planted_bug",
    "reward_hack",
    "inconclusive_ci",
    "cascade_quarantine",
]

NEW_SCENARIOS = [
    "seed_luck",
    "selection_bias",
    "goal_metric_mismatch",
    "vacuous_confirm",
    "hidden_confound",
    "commitment_trap",
    "leakage_gap",
    "open_leak_hunt",
    "open_web_prior",
    "baseline_stale",
    "metric_drift",
    "survivor_bias",
    "double_blind_missing",
    "repro_flip",
    "planted_manipulation",
    "inconclusive_ci",
    "cascade_quarantine",
]


@pytest.mark.parametrize("name", NEW_SCENARIOS)
def test_new_scenario_smoke(name, tmp_path):
    r = run_one(name, "governed", "mock", results_dir=tmp_path)
    assert isinstance(r["success"], bool)


@pytest.mark.parametrize("name", SCENARIOS)
def test_governed_beats_baseline(name, tmp_path):
    base = run_one(name, "baseline", "mock", results_dir=tmp_path)
    gov = run_one(name, "governed", "mock", results_dir=tmp_path)
    assert not base["success"], base
    assert gov["success"], gov


def test_cascade_quarantine_auxiliary_isolation(tmp_path):
    gov = run_one("cascade_quarantine", "governed", "mock", results_dir=tmp_path)
    assert gov["success"]
    assert gov["false_cascade_count"] == 0
    assert gov["h1_status"] == "BLOCKED"
    assert gov["h2_status"] != "BLOCKED"
    assert gov["h3_status"] != "BLOCKED"

    base = run_one("cascade_quarantine", "baseline", "mock", results_dir=tmp_path)
    assert not base["success"]
    assert base["false_cascade_count"] > 0
    assert "H2" in base["downstream_blocked"]
    assert "H3" in base["downstream_blocked"]


def test_inconclusive_ci_rejection(tmp_path):
    gov = run_one("inconclusive_ci", "governed", "mock", results_dir=tmp_path)
    assert gov["success"]
    assert gov["status"] != "CONFIRMED"
    assert gov["final_level"] == "E1"

    base = run_one("inconclusive_ci", "baseline", "mock", results_dir=tmp_path)
    assert not base["success"]
    assert base["status"] == "CONFIRMED"


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


def test_opencode_agent_seeds_workspace(tmp_path):
    import json as jsonlib

    from sandbox.agents import OpencodeAgent

    a = OpencodeAgent("verify assumptions first")
    a.seed(tmp_path, "task text")
    cfg = jsonlib.loads((tmp_path / ".opencode" / "opencode.json").read_text())
    cmd = cfg["mcp"]["epires"]["command"]
    assert Path(cmd[0]).stem.lower() == "epires" and cmd[1] == "mcp"
    agents_md = (tmp_path / "AGENTS.md").read_text()
    assert "verify assumptions first" in agents_md and "task text" in agents_md


@pytest.mark.skipif(not os.environ.get("EPIRES_EVAL_MODEL"), reason="no EPIRES_EVAL_MODEL configured")
def test_opencode_agent_cli_smoke(tmp_path):
    from sandbox.agents import OpencodeAgent

    out = OpencodeAgent("test prompt").run("Reply with the word ok.", tmp_path)
    assert isinstance(out, str) and out
