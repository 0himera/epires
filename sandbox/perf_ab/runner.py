"""Isolated OpenCode A/B trial runner.

The runner deliberately keeps the task prompt and agent invocation identical
between conditions. Treatments vary only the project-local Epires policy and
tool setup. Hidden grading happens after OpenCode exits and the grader is never
copied into the agent workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = "Read TASK.md and complete the task. Work only in this repository."
EPIRES_SKILL_RELATIVE_PATHS = (
    Path(".agents/skills/epires/SKILL.md"),
    Path(".opencode/skills/epires/SKILL.md"),
    Path(".claude/skills/epires/SKILL.md"),
    Path(".cursor/skills/epires/SKILL.md"),
    Path(".gemini/skills/epires/SKILL.md"),
)


class Condition(str, Enum):
    """A benchmark treatment."""

    BARE = "bare"
    EPIRES = "epires"
    EPIRES_DIRECT = "epires_direct"
    EPIRES_MINIMAL = "epires_minimal"
    EPIRES_PROBE = "epires_probe"
    EPIRES_MCP_ONLY = "epires_mcp_only"
    EPIRES_PROBE_NO_WEB = "epires_probe_no_web"
    EPIRES_WEB_TASK_SKILL = "epires_web_task_skill"
    EPIRES_WEB_TASK_AGENTS = "epires_web_task_agents"
    EPIRES_WEB_BASELINE_SKILL = "epires_web_baseline_skill"


WEB_REQUIRED_CONDITIONS = frozenset(
    {
        Condition.EPIRES_WEB_TASK_SKILL,
        Condition.EPIRES_WEB_TASK_AGENTS,
        Condition.EPIRES_WEB_BASELINE_SKILL,
    }
)


@dataclass(frozen=True)
class RunConfig:
    """Configuration shared by one OpenCode trial.

    ``task_dir`` must contain ``project/``, ``hidden/grader.py`` and normally
    ``task.json``.  Results are durable, while the copied agent workspace is a
    throwaway directory below ``workspace_root`` (``/tmp`` by default).
    """

    task_dir: Path | str
    condition: Condition | str
    model: str
    variant: str | None = None
    timeout_seconds: float = 600.0
    grader_timeout_seconds: float = 180.0
    output_dir: Path | str | None = None
    workspace_root: Path | str = Path("/tmp")
    opencode_bin: str = "opencode"
    epires_bin: str | None = None
    prompt: str = DEFAULT_PROMPT
    trial_id: str | None = None
    pair_id: str | None = None
    replicate: int | None = None
    keep_workspace: bool = False
    enable_web_auth: bool = False
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_dir", Path(self.task_dir).resolve())
        object.__setattr__(self, "condition", Condition(self.condition))
        object.__setattr__(self, "workspace_root", Path(self.workspace_root).resolve())
        if self.output_dir is not None:
            object.__setattr__(self, "output_dir", Path(self.output_dir).resolve())
        if not self.model.strip():
            raise ValueError("model must be a non-empty OpenCode provider/model identifier")
        if self.variant is not None and not self.variant.strip():
            raise ValueError("variant must be non-empty when provided")
        if self.timeout_seconds <= 0 or self.grader_timeout_seconds <= 0:
            raise ValueError("timeouts must be positive")


@dataclass(frozen=True)
class _CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _execute(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> _CommandResult:
    """Execute a command and kill its whole process group on timeout."""

    argv = tuple(str(part) for part in command)
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return _CommandResult(argv, 127, "", str(exc), time.monotonic() - started)

    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()

    return _CommandResult(
        command=argv,
        returncode=process.returncode if process.returncode is not None else -signal.SIGKILL,
        stdout=stdout or "",
        stderr=stderr or "",
        duration_seconds=time.monotonic() - started,
        timed_out=timed_out,
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _command_dict(result: _CommandResult) -> dict[str, object]:
    return {
        "command": list(result.command),
        "returncode": result.returncode,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
    }


def _resolve_epires_bin(explicit: str | None) -> str:
    if explicit:
        return str(Path(explicit).expanduser().resolve()) if os.sep in explicit else explicit
    local = PROJECT_ROOT / ".venv" / "bin" / "epires"
    if local.is_file():
        return str(local.resolve())
    return shutil.which("epires") or "epires"


def _isolated_env(
    config: RunConfig,
    epires_bin: str,
    isolation_root: Path,
) -> tuple[dict[str, str], bool, bool]:
    env = dict(os.environ)
    env.update({str(key): str(value) for key, value in config.env.items()})

    # Isolate every location used by OpenCode.  Keep provider access by copying
    # only auth.json, never global config, plugins, skills, sessions, or state.
    original_home = Path(env.get("HOME", str(Path.home()))).expanduser()
    original_data = Path(env.get("XDG_DATA_HOME", str(original_home / ".local" / "share"))).expanduser()
    private_home = isolation_root / "home"
    private_config = isolation_root / "config"
    private_data = isolation_root / "data"
    private_cache = isolation_root / "cache"
    private_state = isolation_root / "state"
    for directory in (private_home, private_config, private_data, private_cache, private_state):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    source_auth = original_data / "opencode" / "auth.json"
    target_auth = private_data / "opencode" / "auth.json"
    auth_copied = False
    if source_auth.is_file():
        target_auth.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source_auth, target_auth)
        target_auth.chmod(0o600)
        auth_copied = True

    # Web credentials are deliberately opt-in. An earlier benchmark isolated
    # HOME so completely that Epires web search was physically unavailable;
    # prompt compliance from such a run would be invalid evidence.
    source_web_credentials = original_home / ".epires" / "credentials.json"
    target_web_credentials = private_home / ".epires" / "credentials.json"
    web_auth_available = False
    if config.enable_web_auth:
        if env.get("PARALLEL_API_KEY", "").strip():
            web_auth_available = True
        elif source_web_credentials.is_file():
            target_web_credentials.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source_web_credentials, target_web_credentials)
            target_web_credentials.chmod(0o600)
            web_auth_available = True
    else:
        env.pop("PARALLEL_API_KEY", None)

    env["HOME"] = str(private_home)
    env["XDG_CONFIG_HOME"] = str(private_config)
    env["XDG_DATA_HOME"] = str(private_data)
    env["XDG_CACHE_HOME"] = str(private_cache)
    env["XDG_STATE_HOME"] = str(private_state)
    env.pop("OPENCODE_CONFIG", None)
    env["OPENCODE_CONFIG_DIR"] = str(private_config / "opencode")
    env["OPENCODE_CONFIG_CONTENT"] = "{}"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["CI"] = "1"

    resolved = shutil.which(epires_bin) if os.sep not in epires_bin else epires_bin
    if resolved:
        bin_dir = str(Path(resolved).resolve().parent)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env, auth_copied, web_auth_available


def _require_task_layout(task_dir: Path) -> tuple[Path, Path, Path]:
    project_dir = task_dir / "project"
    prompt_file = project_dir / "TASK.md"
    grader = task_dir / "hidden" / "grader.py"
    if not project_dir.is_dir():
        raise FileNotFoundError(f"task project directory not found: {project_dir}")
    if not prompt_file.is_file():
        raise FileNotFoundError(f"task prompt not found: {prompt_file}")
    if not grader.is_file():
        raise FileNotFoundError(f"hidden grader not found: {grader}")
    # The source handed to both arms must itself be treatment-free.  Rejecting
    # an accidentally instrumented task is safer than silently deleting files
    # that may be relevant to the kernel implementation.
    forbidden = [
        *project_dir.rglob("AGENTS.md"),
        *project_dir.rglob("SKILL.md"),
        project_dir / "opencode.json",
        project_dir / ".opencode" / "opencode.json",
        project_dir / ".opencode" / "skills",
        project_dir / ".mcp.json",
        project_dir / ".epires",
    ]
    present = [path for path in forbidden if path.exists()]
    if present:
        paths = ", ".join(str(path.relative_to(project_dir)) for path in present)
        raise ValueError(f"task project is not neutral; remove agent/MCP/skill configuration: {paths}")
    return project_dir, prompt_file, grader


def _git(command: Sequence[str], workspace: Path, env: Mapping[str, str]) -> _CommandResult:
    return _execute(
        ["git", "-c", "user.name=perf-ab", "-c", "user.email=perf-ab@invalid", *command],
        cwd=workspace,
        env=env,
        timeout=30,
    )


def _validate_epires_setup(workspace: Path) -> None:
    required = [
        workspace / ".epires" / "config.json",
        workspace / ".agents" / "skills" / "epires" / "SKILL.md",
        workspace / ".opencode" / "skills" / "epires" / "SKILL.md",
        workspace / "AGENTS.md",
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        names = ", ".join(str(path.relative_to(workspace)) for path in missing)
        raise RuntimeError(f"Epires setup returned success but did not create: {names}")

    config_path = workspace / "opencode.json"
    try:
        opencode_config = json.loads(config_path.read_text(encoding="utf-8"))
        mcp = opencode_config["mcp"]["epires"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Epires setup did not install a valid project-local OpenCode MCP config") from exc
    if not isinstance(mcp, dict) or not mcp.get("enabled", True):
        raise RuntimeError("Epires MCP is disabled after setup")


def _apply_direct_implementation_ablation(workspace: Path) -> None:
    """Remove only mandatory delegation while retaining Epires governance."""

    agents_path = workspace / "AGENTS.md"
    agents = agents_path.read_text(encoding="utf-8")
    skill_law = (
        "- **THE IRON LAW**: The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE. "
        "Scientific leadership, literature research, hypothesis formulation, strict subagent "
        "delegation, artifact verification, epistemic DAG governance only. Coding/testing is "
        "delegated to subagents."
    )
    direct_law = (
        "- **DIRECT IMPLEMENTATION ABLATION**: The Lead-PI writes implementation code directly. "
        "Do not delegate coding or testing to a subagent. Retain hypothesis formulation, artifact "
        "verification, evidence logging, and epistemic DAG governance."
    )
    skill_paths = [workspace / relative for relative in EPIRES_SKILL_RELATIVE_PATHS]
    skill_paths = [path for path in skill_paths if path.is_file()]
    if not skill_paths:
        raise RuntimeError("cannot apply direct ablation: no generated Epires skill found")
    for skill_path in skill_paths:
        skill = skill_path.read_text(encoding="utf-8")
        if skill_law not in skill:
            raise RuntimeError(f"cannot apply direct ablation: canonical Iron Law not found in {skill_path}")
        skill = skill.replace(skill_law, direct_law, 1)
        skill = skill.replace("[Delegate to Coder]", "[Implement Directly]", 1)
        skill = skill.replace(
            "Delegation contract (mandatory per task):",
            "Delegation contract (disabled in this ablation; implement directly):",
            1,
        )
        skill_path.write_text(skill, encoding="utf-8")

    agents_law = "- **THE IRON LAW**: **The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE**."
    if agents_law not in agents:
        raise RuntimeError("cannot apply direct ablation: canonical AGENTS Iron Law not found")
    agents = agents.replace(
        agents_law,
        "- **DIRECT IMPLEMENTATION ABLATION**: **The Lead-PI writes code directly and must not delegate implementation**.",
        1,
    )
    agents = agents.replace(
        "  - All script development, training loops, feature engineering, and test suites are strictly delegated to subagents.",
        "  - Implement and test the scoped task directly; keep the remaining Epires research protocol unchanged.",
        1,
    )
    agents = (
        "## Mandatory Ablation Controls\n"
        "- Load the `epires_researcher` skill and use the Epires MCP tools.\n"
        "- Register a hypothesis before experiments and log the experiment/evidence afterward.\n"
        "- Implement and test code directly; do not call a task/coder subagent.\n"
        "- This changes only delegation; hypothesis-first, ledger, audit, and trace behavior remain required.\n\n"
        + agents
    )
    agents_path.write_text(agents, encoding="utf-8")


_MINIMAL_SKILL = """---
name: epires_researcher
description: Minimal cold-start evidence loop for a directly implemented engineering probe.
---

# Epires Minimal Evidence Loop

1. Inspect the local task and run the supplied baseline/check before changing code.
2. Register exactly one obvious, reversible hypothesis with a mechanism and falsification criterion.
3. Implement and test the hypothesis directly. Do not delegate to a subagent.
4. Run the same public check/benchmark, then register the experiment and one evidence record.
5. If correctness passes and the measured objective improves, stop and return the artifact.

Do not use web research, VSA search, gap analysis, experiment scoring, or gates audit unless the
user explicitly requests them. Do not inflate a local replay above E2.
"""


_PROBE_SKILL = """---
name: epires_researcher
description: Evidence-triggered Probe-Measure-Escalate loop for adaptive engineering research.
---

# Epires Probe-Measure-Escalate Loop

## Cold start
1. Inspect the task and run the supplied baseline/check before changing code.
2. Register one obvious, cheap, reversible hypothesis with a mechanism and falsification criterion.
3. Implement and test it directly. Do not delegate the initial probe.
4. Register the experiment and evidence from the same public evaluation.

## Gate on observed results
- Correct with a clear improvement: stop if the target is met; otherwise try at most one more direct
  local hypothesis when its mechanism is obvious.
- Effect plausibly within timing noise: repeat the same measurement once; do not start research.
- Build/test failure with an identified local cause: repair once and replay.
- Unexplained anomaly, conflicting evidence, or two failed local probes: query Epires associative
  memory for relevant prior evidence.
- Only when local evidence is absent and an external knowledge gap can change the decision, use web
  research. Delegate only when at least two independent safe-to-fail probes can run usefully.

Keep every escalation tied to the observation that triggered it. A local replay cannot exceed E2.
"""


_WEB_POLICY_HEADER = """---
name: epires_researcher
description: Controlled direct evidence loop for the Epires web-search ablation.
---

# Epires Controlled Evidence Loop

This is a benchmark protocol. Follow the ordered steps exactly, implement directly, and do not
delegate. Preserve the task scope and public verification contract.
"""

_WEB_POLICY_TAIL = """
3. Register exactly one hypothesis with its mechanism and a falsification criterion.
4. Implement that hypothesis directly. Do not delegate to a subagent.
5. Run the supplied correctness check and benchmark after the change.
6. Register the experiment and one evidence record using the observed public result, then stop.

Do not use VSA search, gap analysis, experiment scoring, gates audit, or any additional web call.
Do not inflate a local replay above E2.
"""

_PROBE_NO_WEB_SKILL = (
    _WEB_POLICY_HEADER
    + """
1. Inspect `TASK.md` and the relevant source, then run the supplied baseline/check before editing.
2. Do not use web research in this condition.
"""
    + _WEB_POLICY_TAIL
)

_WEB_TASK_SKILL = (
    _WEB_POLICY_HEADER
    + """
1. Inspect `TASK.md` and the relevant source before editing.
2. Before running the baseline, call `epires_parallel_web_search` exactly once in `fast` mode with
   one precise query about the identified kernel bottleneck, `max_results=3`, and `max_chars=4000`.
   Use the result only to sharpen the hypothesis. Then run the supplied baseline/check.
"""
    + _WEB_POLICY_TAIL
)

_WEB_BASELINE_SKILL = (
    _WEB_POLICY_HEADER
    + """
1. Inspect `TASK.md` and the relevant source, then run the supplied baseline/check before editing.
2. After observing the baseline, call `epires_parallel_web_search` exactly once in `fast` mode with
   one precise query about the identified kernel bottleneck, `max_results=3`, and `max_chars=4000`.
   Use the result only to sharpen the hypothesis.
"""
    + _WEB_POLICY_TAIL
)


def _install_compact_policy(workspace: Path, *, skill: str, mode: str) -> None:
    agents_path = workspace / "AGENTS.md"
    skill_paths = [workspace / relative for relative in EPIRES_SKILL_RELATIVE_PATHS]
    skill_paths = [path for path in skill_paths if path.is_file()]
    if not skill_paths:
        raise RuntimeError("cannot install compact policy: no generated Epires skill found")
    for skill_path in skill_paths:
        skill_path.write_text(skill, encoding="utf-8")
    agents_path.write_text(
        "# AGENTS.md — Epires benchmark policy\n\n"
        f"Mode: `{mode}`.\n\n"
        "Load the `epires_researcher` skill and follow it exactly. Epires MCP and the hypothesis "
        "ledger remain enabled. Implement the initial probe directly and preserve the task's scoped "
        "files and verification contract.\n",
        encoding="utf-8",
    )


def _install_agents_only_policy(workspace: Path, *, policy: str, mode: str) -> None:
    for relative in EPIRES_SKILL_RELATIVE_PATHS:
        (workspace / relative).unlink(missing_ok=True)
    body = policy
    if body.startswith("---"):
        _, _, remainder = body.partition("---\n")
        _, separator, remainder = remainder.partition("---\n")
        if separator:
            body = remainder
    (workspace / "AGENTS.md").write_text(
        f"# AGENTS.md — Epires benchmark policy\n\nMode: `{mode}`.\n\n" + body.lstrip(),
        encoding="utf-8",
    )


def _apply_epires_condition_policy(workspace: Path, condition: Condition) -> None:
    if condition is Condition.EPIRES:
        return
    if condition is Condition.EPIRES_DIRECT:
        _apply_direct_implementation_ablation(workspace)
        return
    if condition is Condition.EPIRES_MINIMAL:
        _install_compact_policy(workspace, skill=_MINIMAL_SKILL, mode=condition.value)
        return
    if condition is Condition.EPIRES_PROBE:
        _install_compact_policy(workspace, skill=_PROBE_SKILL, mode=condition.value)
        return
    if condition is Condition.EPIRES_PROBE_NO_WEB:
        _install_compact_policy(workspace, skill=_PROBE_NO_WEB_SKILL, mode=condition.value)
        return
    if condition is Condition.EPIRES_WEB_TASK_SKILL:
        _install_compact_policy(workspace, skill=_WEB_TASK_SKILL, mode=condition.value)
        return
    if condition is Condition.EPIRES_WEB_TASK_AGENTS:
        _install_agents_only_policy(workspace, policy=_WEB_TASK_SKILL, mode=condition.value)
        return
    if condition is Condition.EPIRES_WEB_BASELINE_SKILL:
        _install_compact_policy(workspace, skill=_WEB_BASELINE_SKILL, mode=condition.value)
        return
    if condition is Condition.EPIRES_MCP_ONLY:
        # Keep project-local MCP configuration and the Epires store, but remove
        # every generated skill copy and policy instructions. OpenCode discovers
        # the cross-agent `.agents/` copy before its `.opencode/` copy.
        (workspace / "AGENTS.md").unlink(missing_ok=True)
        for relative in EPIRES_SKILL_RELATIVE_PATHS:
            (workspace / relative).unlink(missing_ok=True)
        return
    raise ValueError(f"unsupported Epires condition policy: {condition.value}")


def _prepare_workspace(
    config: RunConfig, workspace: Path, env: Mapping[str, str], epires_bin: str
) -> list[_CommandResult]:
    setup_results: list[_CommandResult] = []
    if config.condition is not Condition.BARE:
        setup_results.append(
            _execute(
                [epires_bin, "init", "--dir", str(workspace)],
                cwd=workspace,
                env=env,
                timeout=120,
            )
        )
        setup_results.append(
            _execute(
                [epires_bin, "setup", "opencode", "--dir", str(workspace)],
                cwd=workspace,
                env=env,
                timeout=60,
            )
        )
        failed = next((result for result in setup_results if result.returncode != 0 or result.timed_out), None)
        if failed:
            raise RuntimeError(f"Epires setup failed: {' '.join(failed.command)}: {failed.stderr.strip()}")
        _validate_epires_setup(workspace)
        _apply_epires_condition_policy(workspace, config.condition)

    init = _git(["init", "-q"], workspace, env)
    add = _git(["add", "-A"], workspace, env)
    commit = _git(["commit", "-qm", "benchmark baseline"], workspace, env)
    setup_results.extend([init, add, commit])
    failed = next((result for result in (init, add, commit) if result.returncode != 0), None)
    if failed:
        raise RuntimeError(f"git baseline setup failed: {' '.join(failed.command)}: {failed.stderr.strip()}")
    return setup_results


def _read_task_id(task_dir: Path) -> str:
    manifest = task_dir / "task.json"
    if not manifest.is_file():
        return task_dir.name
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return task_dir.name
    return str(value.get("id") or task_dir.name)


def _new_trial_id(config: RunConfig) -> str:
    if config.trial_id:
        if Path(config.trial_id).name != config.trial_id or config.trial_id in {"", ".", ".."}:
            raise ValueError("trial_id must be a single safe path component")
        return config.trial_id
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{config.condition.value}-{timestamp}-{uuid.uuid4().hex[:8]}"


def run_trial(config: RunConfig) -> dict[str, object]:
    """Run one condition and return the same record saved as ``result.json``.

    Agent failure and timeout are outcomes rather than exceptions: the hidden
    grader still runs so correctness and partial work are observable.  Invalid
    benchmark layout or setup failure raises before the treatment begins.
    """

    if not isinstance(config, RunConfig):
        raise TypeError("run_trial expects a RunConfig")

    project_dir, source_prompt, grader = _require_task_layout(config.task_dir)
    trial_id = _new_trial_id(config)
    output_root = Path(config.output_dir) if config.output_dir else config.task_dir / "results"
    result_dir = output_root / trial_id
    if result_dir.exists():
        raise FileExistsError(f"trial result directory already exists: {result_dir}")
    result_dir.mkdir(parents=True)

    workspace = Path(
        tempfile.mkdtemp(prefix=f"epires-perf-ab-{config.condition.value}-", dir=str(config.workspace_root))
    ).resolve()
    isolation_root = Path(tempfile.mkdtemp(prefix="epires-perf-ab-env-", dir=str(config.workspace_root))).resolve()
    shutil.copytree(project_dir, workspace, dirs_exist_ok=True)

    copied_prompt = workspace / "TASK.md"
    prompt_hash = _sha256(copied_prompt)
    if prompt_hash != _sha256(source_prompt):
        raise RuntimeError("TASK.md changed while copying the benchmark project")

    epires_bin = _resolve_epires_bin(config.epires_bin)
    env, auth_copied, web_auth_available = _isolated_env(config, epires_bin, isolation_root)
    if config.condition in WEB_REQUIRED_CONDITIONS and not web_auth_available:
        if not config.keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(isolation_root, ignore_errors=True)
        shutil.rmtree(result_dir, ignore_errors=True)
        raise RuntimeError(
            f"{config.condition.value} requires web credentials; rerun with enable_web_auth=True "
            "and configure Epires Parallel search"
        )
    env["PWD"] = str(workspace)
    started_at = _utc_now()
    total_started = time.monotonic()
    setup_results: list[_CommandResult] = []

    try:
        setup_results = _prepare_workspace(config, workspace, env, epires_bin)
        revision_result = _git(["rev-parse", "HEAD"], workspace, env)
        if revision_result.returncode != 0:
            raise RuntimeError(f"cannot resolve baseline revision: {revision_result.stderr.strip()}")
        base_revision = revision_result.stdout.strip()

        for index, setup_result in enumerate(setup_results):
            (result_dir / f"setup-{index}.stdout.log").write_text(setup_result.stdout, encoding="utf-8")
            (result_dir / f"setup-{index}.stderr.log").write_text(setup_result.stderr, encoding="utf-8")

        opencode_command = [
            config.opencode_bin,
            "run",
            "--pure",
            "--model",
            config.model,
        ]
        if config.variant:
            opencode_command.extend(["--variant", config.variant])
        opencode_command.extend(["--format", "json", config.prompt])
        agent = _execute(
            opencode_command,
            cwd=workspace,
            env=env,
            timeout=config.timeout_seconds,
        )
        (result_dir / "agent.stdout.jsonl").write_text(agent.stdout, encoding="utf-8")
        (result_dir / "agent.stderr.log").write_text(agent.stderr, encoding="utf-8")
        (result_dir / "agent_transcript.jsonl").write_text(agent.stdout + agent.stderr, encoding="utf-8")

        grade_path = result_dir / "grade.json"
        grader_command = [
            env.get("PYTHON", sys.executable),
            str(grader),
            "--submission",
            str(workspace),
            "--output",
            str(grade_path),
            "--base-revision",
            base_revision,
        ]
        grader_result = _execute(
            grader_command,
            cwd=config.task_dir,
            env=env,
            timeout=config.grader_timeout_seconds,
        )
        (result_dir / "grader.stdout.log").write_text(grader_result.stdout, encoding="utf-8")
        (result_dir / "grader.stderr.log").write_text(grader_result.stderr, encoding="utf-8")

        grade: object | None = None
        grade_parse_error: str | None = None
        if grade_path.is_file():
            try:
                grade = json.loads(grade_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                grade_parse_error = str(exc)
        elif grader_result.stdout.strip():
            try:
                grade = json.loads(grader_result.stdout)
            except json.JSONDecodeError as exc:
                grade_parse_error = str(exc)

        if grader_result.timed_out:
            status = "grader_timeout"
        elif grader_result.returncode != 0 or grade is None:
            status = "grader_failed"
        elif agent.timed_out:
            status = "agent_timeout"
        elif agent.returncode != 0:
            status = "agent_failed"
        else:
            status = "completed"

        record: dict[str, object] = {
            "schema_version": 1,
            "trial_id": trial_id,
            "pair_id": config.pair_id,
            "replicate": config.replicate,
            "task_id": _read_task_id(config.task_dir),
            "condition": config.condition.value,
            "model": config.model,
            "variant": config.variant,
            "status": status,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "duration_seconds": time.monotonic() - total_started,
            "limits": {
                "agent_timeout_seconds": config.timeout_seconds,
                "grader_timeout_seconds": config.grader_timeout_seconds,
            },
            "workspace": str(workspace),
            "workspace_retained": config.keep_workspace,
            "result_dir": str(result_dir),
            "prompt_sha256": prompt_hash,
            "base_revision": base_revision,
            "setup": [_command_dict(item) for item in setup_results],
            "agent": _command_dict(agent),
            "grader": {
                **_command_dict(grader_result),
                "result": grade,
                "parse_error": grade_parse_error,
            },
            "isolation": {
                "temporary_git_repository": True,
                "private_home_and_xdg": True,
                "provider_auth_only_copied": auth_copied,
                "web_auth_opt_in": config.enable_web_auth,
                "web_auth_available": web_auth_available,
                "global_opencode_config_available": False,
                "external_opencode_plugins_disabled": True,
                "hidden_assets_copied_to_workspace": False,
            },
            "ablation": {
                "mandatory_delegation_removed": config.condition
                in {
                    Condition.EPIRES_DIRECT,
                    Condition.EPIRES_MINIMAL,
                    Condition.EPIRES_PROBE,
                    Condition.EPIRES_PROBE_NO_WEB,
                    Condition.EPIRES_WEB_TASK_SKILL,
                    Condition.EPIRES_WEB_TASK_AGENTS,
                    Condition.EPIRES_WEB_BASELINE_SKILL,
                },
                "epires_mcp_retained": config.condition is not Condition.BARE,
                "hypothesis_ledger_retained": config.condition is not Condition.BARE,
                "policy": config.condition.value,
                "adaptive_escalation_gate": config.condition is Condition.EPIRES_PROBE,
                "compact_hypothesis_loop": config.condition
                in {
                    Condition.EPIRES_MINIMAL,
                    Condition.EPIRES_PROBE,
                    Condition.EPIRES_PROBE_NO_WEB,
                    Condition.EPIRES_WEB_TASK_SKILL,
                    Condition.EPIRES_WEB_TASK_AGENTS,
                    Condition.EPIRES_WEB_BASELINE_SKILL,
                },
                "policy_instructions_removed": config.condition is Condition.EPIRES_MCP_ONLY,
                "web_required_by_policy": config.condition in WEB_REQUIRED_CONDITIONS,
                "policy_location": (
                    "agents"
                    if config.condition is Condition.EPIRES_WEB_TASK_AGENTS
                    else "skill"
                    if config.condition
                    in {
                        Condition.EPIRES_PROBE_NO_WEB,
                        Condition.EPIRES_WEB_TASK_SKILL,
                        Condition.EPIRES_WEB_BASELINE_SKILL,
                    }
                    else None
                ),
            },
        }
        _write_json(result_dir / "result.json", record)
        return record
    finally:
        if not config.keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)
        shutil.rmtree(isolation_root, ignore_errors=True)


def config_as_dict(config: RunConfig) -> dict[str, object]:
    """JSON-friendly representation useful to benchmark orchestrators."""

    result = asdict(config)
    result["task_dir"] = str(config.task_dir)
    result["condition"] = config.condition.value
    result["workspace_root"] = str(config.workspace_root)
    if config.output_dir is not None:
        result["output_dir"] = str(config.output_dir)
    result["env"] = dict(config.env)
    return result
