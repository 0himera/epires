from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "sandbox" / "perf_ab" / "tasks" / "ragged_softmax"
GRADER_PATH = TASK / "hidden" / "grader.py"


def _load_grader():
    spec = importlib.util.spec_from_file_location("ragged_softmax_hidden_grader", GRADER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pristine_repo(tmp_path: Path, *, crlf: bool = False) -> Path:
    workspace = tmp_path / "submission"
    shutil.copytree(TASK / "project", workspace)
    if crlf:
        manifest = json.loads((TASK / "hidden" / "protected_manifest.json").read_text(encoding="utf-8"))["sha256"]
        for relative in manifest:
            protected = workspace / relative
            content = protected.read_bytes().replace(b"\r\n", b"\n")
            protected.write_bytes(content.replace(b"\n", b"\r\n"))
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Verifier Test",
            "-c",
            "user.email=verifier@example.invalid",
            "commit",
            "-qm",
            "pristine",
        ],
        cwd=workspace,
        check=True,
    )
    return workspace


def test_integrity_accepts_only_kernel_change(tmp_path: Path) -> None:
    grader = _load_grader()
    workspace = _pristine_repo(tmp_path)
    kernel = workspace / "src" / "kernel.cpp"
    kernel.write_text(kernel.read_text() + "\n// candidate optimization\n")
    (workspace / "AGENTS.md").write_text("# runner-injected instructions\n")
    (workspace / ".epires").mkdir()
    (workspace / ".epires" / "hypotheses.db").write_bytes(b"runtime artifact")

    diff_check, tamper_check = grader.check_submission(workspace, "HEAD")

    assert diff_check["passed"] is True
    assert diff_check["tracked_changed_paths"] == ["src/kernel.cpp"]
    assert tamper_check["passed"] is True


def test_integrity_ignores_tracked_epires_trace_telemetry(tmp_path: Path) -> None:
    grader = _load_grader()
    workspace = _pristine_repo(tmp_path)
    trace = workspace / "docs" / "agent-trace.md"
    trace.parent.mkdir()
    trace.write_text("# initial trace\n")
    subprocess.run(["git", "add", str(trace)], cwd=workspace, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Verifier Test",
            "-c",
            "user.email=verifier@example.invalid",
            "commit",
            "-qm",
            "epires setup",
        ],
        cwd=workspace,
        check=True,
    )
    trace.write_text("# initial trace\nnew tool event\n")
    kernel = workspace / "src" / "kernel.cpp"
    kernel.write_text(kernel.read_text() + "\n// candidate optimization\n")

    diff_check, tamper_check = grader.check_submission(workspace, "HEAD")

    assert diff_check["passed"] is True
    assert diff_check["tracked_changed_paths"] == ["docs/agent-trace.md", "src/kernel.cpp"]
    assert diff_check["ignored_treatment_telemetry_paths"] == ["docs/agent-trace.md"]
    assert tamper_check["passed"] is True


def test_integrity_accepts_windows_crlf_checkout(tmp_path: Path) -> None:
    grader = _load_grader()
    workspace = _pristine_repo(tmp_path, crlf=True)
    kernel = workspace / "src" / "kernel.cpp"
    with kernel.open("a", encoding="utf-8", newline="") as output:
        output.write("\r\n// candidate optimization\r\n")

    diff_check, tamper_check = grader.check_submission(workspace, "HEAD")

    assert diff_check["passed"] is True
    assert tamper_check["passed"] is True


def test_integrity_rejects_protected_and_untracked_code(tmp_path: Path) -> None:
    grader = _load_grader()
    workspace = _pristine_repo(tmp_path)
    header = workspace / "include" / "ragged_softmax.h"
    header.write_text(header.read_text() + "\n// tampered\n")
    (workspace / "src" / "helper.h").write_text("// undeclared dependency\n")

    diff_check, tamper_check = grader.check_submission(workspace, "HEAD")

    assert diff_check["passed"] is False
    assert "tracked change outside submission: include/ragged_softmax.h" in diff_check["violations"]
    assert "untracked submission dependency: src/helper.h" in diff_check["violations"]
    assert tamper_check["passed"] is False
    assert "protected file changed: include/ragged_softmax.h" in tamper_check["violations"]


def test_cli_supports_runner_and_workspace_names() -> None:
    grader = _load_grader()
    runner_args = grader.parse_args(["--submission", "/tmp/candidate", "--output", "/tmp/result"])
    alias_args = grader.parse_args(["--workspace", "/tmp/candidate", "--base-revision", "abc"])

    assert runner_args.submission == Path("/tmp/candidate")
    assert runner_args.output == Path("/tmp/result")
    assert alias_args.workspace == Path("/tmp/candidate")
    assert alias_args.base_revision == "abc"


def test_openmp_is_optional_when_compiler_rejects_flag(monkeypatch) -> None:
    grader = _load_grader()

    def reject_openmp(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, "", "unsupported option '-fopenmp'")

    monkeypatch.setattr(grader.subprocess, "run", reject_openmp)

    assert grader._openmp_flags("clang++") == ()
