from __future__ import annotations

import json
from pathlib import Path

import pytest

from sandbox.perf_ab import runner
from sandbox.perf_ab.run import _conditions
from sandbox.perf_ab.runner import Condition, RunConfig, run_trial


def _task(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    project = task / "project"
    hidden = task / "hidden"
    project.mkdir(parents=True)
    hidden.mkdir()
    (project / "TASK.md").write_text("Optimize the kernel.\n", encoding="utf-8")
    (project / "kernel.cpp").write_text("int kernel() { return 1; }\n", encoding="utf-8")
    (hidden / "grader.py").write_text("# replaced by fake executor\n", encoding="utf-8")
    (task / "task.json").write_text(json.dumps({"id": "tiny"}), encoding="utf-8")
    return task


def _fake_execute_factory(calls: list[tuple[tuple[str, ...], Path, dict[str, str]]]):
    revision = "1" * 40

    def fake_execute(command, *, cwd, env, timeout):
        argv = tuple(str(item) for item in command)
        calls.append((argv, Path(cwd), dict(env)))
        stdout = ""
        if argv[:2] == ("epires-test", "init"):
            workspace = Path(cwd)
            (workspace / ".epires").mkdir()
            (workspace / ".epires" / "config.json").write_text("{}", encoding="utf-8")
            skill_text = (
                "- **THE IRON LAW**: The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE. "
                "Scientific leadership, literature research, hypothesis formulation, strict subagent "
                "delegation, artifact verification, epistemic DAG governance only. Coding/testing is "
                "delegated to subagents.\n"
                "[Delegate to Coder]\nDelegation contract (mandatory per task):\n"
            )
            for relative in runner.EPIRES_SKILL_RELATIVE_PATHS:
                skill = workspace / relative
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text(skill_text, encoding="utf-8")
            (workspace / "AGENTS.md").write_text(
                "- **THE IRON LAW**: **The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE**.\n"
                "  - All script development, training loops, feature engineering, and test suites are "
                "strictly delegated to subagents.\n",
                encoding="utf-8",
            )
            (workspace / "opencode.json").write_text(
                json.dumps({"mcp": {"epires": {"enabled": True}}}), encoding="utf-8"
            )
        if "rev-parse" in argv:
            stdout = revision + "\n"
        if "grader.py" in " ".join(argv):
            output = Path(argv[argv.index("--output") + 1])
            output.write_text(json.dumps({"correct": True, "score": 1.25}), encoding="utf-8")
            stdout = json.dumps({"correct": True, "score": 1.25})
        return runner._CommandResult(argv, 0, stdout, "", 0.01)

    return fake_execute


@pytest.mark.parametrize(
    "condition",
    [
        Condition.BARE,
        Condition.EPIRES,
        Condition.EPIRES_DIRECT,
        Condition.EPIRES_MINIMAL,
        Condition.EPIRES_PROBE,
        Condition.EPIRES_MCP_ONLY,
    ],
)
def test_run_trial_isolates_agent_and_invokes_hidden_grader(tmp_path, monkeypatch, condition):
    task = _task(tmp_path)
    calls = []
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(runner, "_execute", _fake_execute_factory(calls))

    record = run_trial(
        RunConfig(
            task_dir=task,
            condition=condition,
            model="provider/model",
            variant="low",
            output_dir=tmp_path / "results",
            workspace_root=tmp_path,
            epires_bin="epires-test",
        )
    )

    assert record["status"] == "completed"
    assert record["grader"]["result"] == {"correct": True, "score": 1.25}
    result_dir = Path(record["result_dir"])
    assert (result_dir / "result.json").is_file()
    assert (result_dir / "agent.stdout.jsonl").is_file()
    assert not Path(record["workspace"]).exists()

    opencode = next(call for call in calls if call[0][:2] == ("opencode", "run"))
    assert "--pure" in opencode[0]
    assert ("--model", "provider/model") == opencode[0][opencode[0].index("--model") :][:2]
    assert ("--variant", "low") == opencode[0][opencode[0].index("--variant") :][:2]
    assert opencode[2]["OPENCODE_CONFIG_CONTENT"] == "{}"
    assert opencode[2]["HOME"].startswith(str(tmp_path))
    assert opencode[2]["XDG_CONFIG_HOME"].startswith(str(tmp_path))
    assert opencode[2]["XDG_DATA_HOME"].startswith(str(tmp_path))
    assert opencode[2]["PWD"] == str(opencode[1])

    grader = next(call for call in calls if "grader.py" in " ".join(call[0]))
    assert grader[0][grader[0].index("--base-revision") + 1] == "1" * 40
    assert not (opencode[1] / "hidden").exists()

    init_calls = [call for call in calls if call[0][:2] == ("epires-test", "init")]
    assert bool(init_calls) is (condition is not Condition.BARE)
    assert record["ablation"]["mandatory_delegation_removed"] is (
        condition
        in {
            Condition.EPIRES_DIRECT,
            Condition.EPIRES_MINIMAL,
            Condition.EPIRES_PROBE,
        }
    )
    if condition is Condition.EPIRES_DIRECT:
        opencode_workspace = opencode[1]
        # The workspace is deleted after the run, but the OpenCode call sees
        # the direct-ablation instructions before cleanup.
        assert any(call[1] == opencode_workspace for call in calls)


def test_agent_timeout_is_graded_and_recorded(tmp_path, monkeypatch):
    task = _task(tmp_path)
    base_fake = _fake_execute_factory([])
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    def fake_execute(command, *, cwd, env, timeout):
        argv = tuple(str(item) for item in command)
        if argv[:2] == ("opencode", "run"):
            return runner._CommandResult(argv, -9, "partial", "", 0.01, timed_out=True)
        return base_fake(command, cwd=cwd, env=env, timeout=timeout)

    monkeypatch.setattr(runner, "_execute", fake_execute)
    record = run_trial(
        RunConfig(
            task_dir=task,
            condition="bare",
            model="provider/model",
            output_dir=tmp_path / "results",
            workspace_root=tmp_path,
        )
    )

    assert record["status"] == "agent_timeout"
    assert record["grader"]["result"]["correct"] is True


def test_run_config_rejects_missing_model(tmp_path):
    with pytest.raises(ValueError, match="model"):
        RunConfig(task_dir=tmp_path, condition="bare", model="")


def test_instrumented_source_project_is_rejected(tmp_path):
    task = _task(tmp_path)
    (task / "project" / "AGENTS.md").write_text("ambient instructions", encoding="utf-8")
    with pytest.raises(ValueError, match="not neutral"):
        run_trial(
            RunConfig(
                task_dir=task,
                condition="bare",
                model="provider/model",
                output_dir=tmp_path / "results",
            )
        )


def test_condition_groups_expose_delegation_and_full_ablation_matrices():
    assert _conditions("delegation_ablation") == [Condition.EPIRES, Condition.EPIRES_DIRECT]
    assert _conditions("ablation") == [
        Condition.EPIRES,
        Condition.EPIRES_DIRECT,
        Condition.EPIRES_MINIMAL,
        Condition.EPIRES_PROBE,
        Condition.EPIRES_MCP_ONLY,
    ]
    assert _conditions("all") == [Condition.BARE, *_conditions("ablation")]
    assert _conditions("web_ablation") == [
        Condition.BARE,
        Condition.EPIRES_PROBE_NO_WEB,
        Condition.EPIRES_WEB_TASK_SKILL,
        Condition.EPIRES_WEB_TASK_AGENTS,
        Condition.EPIRES_WEB_BASELINE_SKILL,
    ]


def test_direct_ablation_requires_epires_protocol_but_forbids_delegation(tmp_path):
    workspace = tmp_path / "workspace"
    skill = workspace / ".opencode" / "skills" / "epires" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "- **THE IRON LAW**: The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE. "
        "Scientific leadership, literature research, hypothesis formulation, strict subagent "
        "delegation, artifact verification, epistemic DAG governance only. Coding/testing is "
        "delegated to subagents.\n"
        "[Delegate to Coder]\nDelegation contract (mandatory per task):\n",
        encoding="utf-8",
    )
    agents = workspace / "AGENTS.md"
    agents.write_text(
        "- **THE IRON LAW**: **The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE**.\n"
        "  - All script development, training loops, feature engineering, and test suites are "
        "strictly delegated to subagents.\n",
        encoding="utf-8",
    )

    runner._apply_direct_implementation_ablation(workspace)

    assert "[Implement Directly]" in skill.read_text()
    instructions = agents.read_text()
    assert "Load the `epires_researcher` skill" in instructions
    assert "Register a hypothesis before experiments" in instructions
    assert "do not call a task/coder subagent" in instructions


def test_direct_ablation_updates_cross_agent_skill_discovered_by_opencode(tmp_path):
    workspace = tmp_path / "workspace"
    canonical = (
        "- **THE IRON LAW**: The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE. "
        "Scientific leadership, literature research, hypothesis formulation, strict subagent "
        "delegation, artifact verification, epistemic DAG governance only. Coding/testing is "
        "delegated to subagents.\n"
        "[Delegate to Coder]\nDelegation contract (mandatory per task):\n"
    )
    for relative in runner.EPIRES_SKILL_RELATIVE_PATHS[:2]:
        skill = workspace / relative
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(canonical, encoding="utf-8")
    (workspace / "AGENTS.md").write_text(
        "- **THE IRON LAW**: **The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE**.\n"
        "  - All script development, training loops, feature engineering, and test suites are "
        "strictly delegated to subagents.\n",
        encoding="utf-8",
    )

    runner._apply_direct_implementation_ablation(workspace)

    for relative in runner.EPIRES_SKILL_RELATIVE_PATHS[:2]:
        assert "DIRECT IMPLEMENTATION ABLATION" in (workspace / relative).read_text()


@pytest.mark.parametrize(
    ("condition", "expected", "unexpected"),
    [
        (
            Condition.EPIRES_MINIMAL,
            "Register exactly one obvious, reversible hypothesis",
            "query Epires associative",
        ),
        (
            Condition.EPIRES_PROBE,
            "Effect plausibly within timing noise",
            "Do not use web research",
        ),
    ],
)
def test_compact_policies_are_distinct(condition, expected, unexpected, tmp_path):
    workspace = tmp_path / condition.value
    skill_paths = [workspace / relative for relative in runner.EPIRES_SKILL_RELATIVE_PATHS[:2]]
    for skill in skill_paths:
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("full policy", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("full agents", encoding="utf-8")

    runner._apply_epires_condition_policy(workspace, condition)

    for skill in skill_paths:
        skill_text = skill.read_text(encoding="utf-8")
        assert expected in skill_text
        assert unexpected not in skill_text
    assert "Implement the initial probe directly" in (workspace / "AGENTS.md").read_text()


def test_mcp_only_removes_policy_files_but_keeps_tool_configuration(tmp_path):
    workspace = tmp_path / "mcp-only"
    skill_paths = [workspace / relative for relative in runner.EPIRES_SKILL_RELATIVE_PATHS]
    for skill in skill_paths:
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("full policy", encoding="utf-8")
    agents = workspace / "AGENTS.md"
    agents.write_text("full agents", encoding="utf-8")
    config = workspace / "opencode.json"
    config.write_text('{"mcp":{"epires":{"enabled":true}}}', encoding="utf-8")
    store = workspace / ".epires" / "config.json"
    store.parent.mkdir()
    store.write_text("{}", encoding="utf-8")

    runner._apply_epires_condition_policy(workspace, Condition.EPIRES_MCP_ONLY)

    assert all(not skill.exists() for skill in skill_paths)
    assert not agents.exists()
    assert config.is_file()
    assert store.is_file()


@pytest.mark.parametrize(
    ("condition", "must_contain", "must_not_contain"),
    [
        (
            Condition.EPIRES_PROBE_NO_WEB,
            "Do not use web research in this condition",
            "epires_parallel_web_search",
        ),
        (
            Condition.EPIRES_WEB_TASK_SKILL,
            "Before running the baseline, call `epires_parallel_web_search` exactly once",
            "After observing the baseline",
        ),
        (
            Condition.EPIRES_WEB_BASELINE_SKILL,
            "After observing the baseline, call `epires_parallel_web_search` exactly once",
            "Before running the baseline",
        ),
    ],
)
def test_web_ablation_skill_policies_change_only_the_registered_factor(
    tmp_path, condition, must_contain, must_not_contain
):
    workspace = tmp_path / condition.value
    for relative in runner.EPIRES_SKILL_RELATIVE_PATHS[:2]:
        skill = workspace / relative
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("generated full policy", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("generated agents", encoding="utf-8")

    runner._apply_epires_condition_policy(workspace, condition)

    policies = [
        (workspace / relative).read_text(encoding="utf-8") for relative in runner.EPIRES_SKILL_RELATIVE_PATHS[:2]
    ]
    assert len(set(policies)) == 1
    assert must_contain in policies[0]
    assert must_not_contain not in policies[0]
    assert "Register exactly one hypothesis" in policies[0]
    assert "Do not delegate to a subagent" in policies[0]


def test_agents_placement_ablation_removes_skill_and_embeds_same_policy(tmp_path):
    workspace = tmp_path / "agents-placement"
    skill_paths = [workspace / relative for relative in runner.EPIRES_SKILL_RELATIVE_PATHS]
    for skill in skill_paths:
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text("generated full policy", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("generated agents", encoding="utf-8")

    runner._apply_epires_condition_policy(workspace, Condition.EPIRES_WEB_TASK_AGENTS)

    assert all(not skill.exists() for skill in skill_paths)
    agents = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "epires_parallel_web_search" in agents
    assert "Register exactly one hypothesis" in agents
    assert "name: epires_researcher" not in agents


def test_web_auth_is_opt_in_and_copied_without_leaking_value(tmp_path, monkeypatch):
    original_home = tmp_path / "original-home"
    credentials = original_home / ".epires" / "credentials.json"
    credentials.parent.mkdir(parents=True)
    credentials.write_text('{"parallel_api_key":"secret-test-value"}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(original_home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)

    disabled = RunConfig(task_dir=tmp_path, condition="bare", model="provider/model")
    disabled_env, _, disabled_web = runner._isolated_env(disabled, "epires", tmp_path / "disabled-env")
    assert disabled_web is False
    assert "PARALLEL_API_KEY" not in disabled_env
    assert not (Path(disabled_env["HOME"]) / ".epires" / "credentials.json").exists()

    enabled = RunConfig(
        task_dir=tmp_path,
        condition="bare",
        model="provider/model",
        enable_web_auth=True,
    )
    enabled_env, _, enabled_web = runner._isolated_env(enabled, "epires", tmp_path / "enabled-env")
    copied = Path(enabled_env["HOME"]) / ".epires" / "credentials.json"
    assert enabled_web is True
    assert copied.read_text(encoding="utf-8") == credentials.read_text(encoding="utf-8")
    assert copied.stat().st_mode & 0o777 == 0o600


def test_web_condition_refuses_to_run_without_explicit_web_auth(tmp_path, monkeypatch):
    task = _task(tmp_path)
    calls = []
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    monkeypatch.setattr(runner, "_execute", _fake_execute_factory(calls))

    with pytest.raises(RuntimeError, match="requires web credentials"):
        run_trial(
            RunConfig(
                task_dir=task,
                condition=Condition.EPIRES_WEB_TASK_SKILL,
                model="provider/model",
                output_dir=tmp_path / "results",
                workspace_root=tmp_path,
                epires_bin="epires-test",
            )
        )

    assert not calls
