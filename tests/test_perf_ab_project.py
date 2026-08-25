from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


PROJECT = Path(__file__).resolve().parents[1] / "sandbox" / "perf_ab" / "tasks" / "ragged_softmax" / "project"


def test_ragged_softmax_task_has_isolated_submission_surface() -> None:
    assert (PROJECT / "TASK.md").is_file()
    assert (PROJECT / "src" / "kernel.cpp").is_file()
    assert (PROJECT / "src" / "baseline.cpp").is_file()
    assert (PROJECT / "src" / "public_bench.cpp").is_file()
    assert (PROJECT / "include" / "ragged_softmax.h").is_file()


@pytest.mark.skipif(shutil.which("g++") is None or shutil.which("make") is None, reason="C++ toolchain unavailable")
def test_ragged_softmax_public_correctness(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    shutil.copytree(PROJECT, workspace, ignore=shutil.ignore_patterns("build"))
    result = subprocess.run(
        ["make", "check"],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "public correctness: PASS" in result.stdout
