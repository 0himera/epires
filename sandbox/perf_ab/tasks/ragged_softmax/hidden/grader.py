#!/usr/bin/env python3
"""Private grader for the ragged-softmax performance task.

The submitted worktree supplies exactly one translation unit.  The reference
implementation and all workload generation stay next to this script, outside
the worktree shown to the optimizing agent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


TASK_ID = "ragged_softmax_cpp"
ALLOWED_CHANGED_PATHS = {"src/kernel.cpp"}
IGNORED_TRACKED_PATHS = {
    # Epires appends tool telemetry here after the baseline commit. It is not
    # part of the submitted translation unit and must not invalidate only the
    # treatment arm.
    "docs/agent-trace.md",
}
IGNORED_UNTRACKED_PREFIXES = (
    ".epires/",
    ".opencode/",
    ".codex/",
    "build/",
)
IGNORED_UNTRACKED_PATHS = {
    ".perf_ab_base_revision",
    "AGENTS.md",
    "agent_transcript.jsonl",
    "docs/agent-trace.md",
    "store.db",
}
COMPILE_FLAGS = (
    "-O3",
    "-std=c++17",
    "-march=native",
    "-DNDEBUG",
    "-Wall",
    "-Wextra",
)


def _run_git(workspace: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _is_ignored_untracked(path: str) -> bool:
    return path in IGNORED_UNTRACKED_PATHS or path.startswith(IGNORED_UNTRACKED_PREFIXES)


def _discover_base_revision(workspace: Path, requested: str | None) -> tuple[str | None, str]:
    if requested:
        return requested, "argument"
    marker = workspace / ".perf_ab_base_revision"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return value, "marker"
    return "HEAD", "fallback_head"


def check_submission(workspace: Path, base_revision: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = Path(__file__).with_name("protected_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["sha256"]

    integrity_violations: list[str] = []
    manifest_actual: dict[str, str | None] = {}
    for relative, expected in manifest.items():
        path = workspace / relative
        if not path.is_file() or path.is_symlink():
            manifest_actual[relative] = None
            integrity_violations.append(f"protected file missing or not regular: {relative}")
            continue
        actual = _sha256(path)
        manifest_actual[relative] = actual
        if actual != expected:
            integrity_violations.append(f"protected file changed: {relative}")

    kernel_path = workspace / "src" / "kernel.cpp"
    kernel_ok = False
    if kernel_path.exists():
        mode = kernel_path.lstat().st_mode
        kernel_ok = stat.S_ISREG(mode) and not kernel_path.is_symlink()
    if not kernel_ok:
        integrity_violations.append("submitted src/kernel.cpp is missing, a symlink, or not regular")
    elif kernel_path.stat().st_size > 1024 * 1024:
        kernel_ok = False
        integrity_violations.append("submitted src/kernel.cpp exceeds 1 MiB")

    requested_revision, revision_source = _discover_base_revision(workspace, base_revision)
    resolved_revision: str | None = None
    tracked_changes: list[str] = []
    untracked_paths: list[str] = []
    diff_violations: list[str] = []
    git_error: str | None = None

    resolved = _run_git(workspace, ["rev-parse", "--verify", f"{requested_revision}^{{commit}}"])
    if resolved.returncode != 0:
        git_error = resolved.stderr.strip() or f"cannot resolve {requested_revision}"
        diff_violations.append("base revision could not be resolved")
    else:
        resolved_revision = resolved.stdout.strip()
        changed = _run_git(
            workspace,
            ["diff", "--relative", "--name-only", "--diff-filter=ACDMRTUXB", resolved_revision, "--", "."],
        )
        untracked = _run_git(workspace, ["ls-files", "--others", "--exclude-standard", "--", "."])
        if changed.returncode != 0 or untracked.returncode != 0:
            git_error = (changed.stderr + "\n" + untracked.stderr).strip()
            diff_violations.append("git diff inspection failed")
        else:
            tracked_changes = sorted({line for line in changed.stdout.splitlines() if line})
            untracked_paths = sorted({line for line in untracked.stdout.splitlines() if line})
            for path in tracked_changes:
                if path not in ALLOWED_CHANGED_PATHS and path not in IGNORED_TRACKED_PATHS:
                    diff_violations.append(f"tracked change outside submission: {path}")
            for path in untracked_paths:
                if not _is_ignored_untracked(path):
                    diff_violations.append(f"untracked submission dependency: {path}")

    diff_check = {
        "passed": not diff_violations,
        "base_revision_requested": requested_revision,
        "base_revision_source": revision_source,
        "base_revision_resolved": resolved_revision,
        "allowed_changed_paths": sorted(ALLOWED_CHANGED_PATHS),
        "ignored_treatment_telemetry_paths": sorted(IGNORED_TRACKED_PATHS),
        "tracked_changed_paths": tracked_changes,
        "untracked_paths": untracked_paths,
        "violations": diff_violations,
        "git_error": git_error,
    }
    tamper_violations = [*integrity_violations, *diff_violations]
    tamper_check = {
        "passed": not tamper_violations,
        "kernel_regular_file": kernel_ok,
        "protected_manifest": {
            "expected": manifest,
            "actual": manifest_actual,
            "passed": not integrity_violations,
        },
        "violations": tamper_violations,
    }
    return diff_check, tamper_check


def _available_affinity() -> list[int]:
    if hasattr(os, "sched_getaffinity"):
        return sorted(os.sched_getaffinity(0))
    return list(range(os.cpu_count() or 1))


def _physical_core_key(cpu: int) -> tuple[str, str]:
    topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
    try:
        package = (topology / "physical_package_id").read_text().strip()
        core = (topology / "core_id").read_text().strip()
        return package, core
    except OSError:
        return "unknown", str(cpu)


def _select_cpus(limit: int = 4) -> list[int]:
    available = _available_affinity()
    selected: list[int] = []
    seen_cores: set[tuple[str, str]] = set()
    for cpu in available:
        key = _physical_core_key(cpu)
        if key in seen_cores:
            continue
        selected.append(cpu)
        seen_cores.add(key)
        if len(selected) == limit:
            break
    if not selected:
        selected = available[:1]
    return selected


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def _compiler_version(compiler: str) -> str:
    result = subprocess.run(
        [compiler, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10, check=False
    )
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def _openmp_flags(compiler: str) -> tuple[str, ...]:
    """Enable OpenMP only when the selected compiler can compile and link it."""

    try:
        probe = subprocess.run(
            [compiler, "-std=c++17", "-fopenmp", "-x", "c++", "-", "-o", os.devnull],
            input="int main() { return 0; }\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return ("-fopenmp",) if probe.returncode == 0 else ()


def _empty_correctness(failure: str) -> dict[str, Any]:
    return {
        "passed": False,
        "cases_total": 0,
        "cases_passed": 0,
        "max_abs_error": None,
        "max_rel_error": None,
        "failure": failure,
    }


def _geomean(values: list[float]) -> float:
    if not values or any(not math.isfinite(value) or value <= 0.0 for value in values):
        return 0.0
    return math.exp(math.fsum(math.log(value) for value in values) / len(values))


def grade(workspace: Path, base_revision: str | None) -> dict[str, Any]:
    started = time.monotonic()
    hidden_dir = Path(__file__).resolve().parent
    workspace = workspace.resolve()
    diff_check, tamper_check = check_submission(workspace, base_revision)
    selected_cpus = _select_cpus()
    compiler = shutil.which(os.environ.get("CXX", "g++"))
    openmp_flags = _openmp_flags(compiler) if compiler is not None else ()
    compile_flags = (*COMPILE_FLAGS, *openmp_flags)
    metadata: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": _cpu_model(),
        "available_affinity_cpus": _available_affinity(),
        "selected_affinity_cpus": selected_cpus,
        "affinity_enforced": False,
        "omp_threads": len(selected_cpus) if openmp_flags else 1,
        "openmp_enabled": bool(openmp_flags),
        "compiler": compiler,
        "compile_flags": list(compile_flags),
        "paired_interleaved": True,
        "baseline_rerun_in_candidate_process": True,
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "status": "invalid_submission" if not tamper_check["passed"] else "pending",
        "correctness": _empty_correctness("submission integrity check failed"),
        "workloads": [],
        "geomean_speedup": 0.0,
        "primary_score": 0.0,
        "diff_check": diff_check,
        "tamper_check": tamper_check,
        "metadata": metadata,
    }

    if not tamper_check["passed"]:
        metadata["total_elapsed_seconds"] = time.monotonic() - started
        return result
    if compiler is None:
        result["status"] = "infrastructure_error"
        result["correctness"] = _empty_correctness("C++ compiler not found")
        metadata["total_elapsed_seconds"] = time.monotonic() - started
        return result

    metadata["compiler_version"] = _compiler_version(compiler)
    with tempfile.TemporaryDirectory(prefix="ragged-softmax-grade-") as temporary:
        executable = Path(temporary) / "hidden_driver"
        compile_command = [
            compiler,
            *compile_flags,
            f"-I{workspace / 'include'}",
            str(workspace / "src" / "kernel.cpp"),
            str(hidden_dir / "pristine_baseline.cpp"),
            str(hidden_dir / "driver.cpp"),
            "-o",
            str(executable),
        ]
        compile_started = time.monotonic()
        try:
            compiled = subprocess.run(
                compile_command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                cwd=temporary,
            )
        except subprocess.TimeoutExpired as error:
            result["status"] = "build_timeout"
            result["correctness"] = _empty_correctness("compilation exceeded 30 seconds")
            metadata["compile_elapsed_seconds"] = time.monotonic() - compile_started
            metadata["compile_stderr"] = (error.stderr or "")[-8000:]
            metadata["total_elapsed_seconds"] = time.monotonic() - started
            return result
        metadata["compile_elapsed_seconds"] = time.monotonic() - compile_started
        metadata["compile_stdout"] = compiled.stdout[-4000:]
        metadata["compile_stderr"] = compiled.stderr[-8000:]
        if compiled.returncode != 0:
            result["status"] = "build_error"
            result["correctness"] = _empty_correctness("candidate failed to compile")
            metadata["compile_returncode"] = compiled.returncode
            metadata["total_elapsed_seconds"] = time.monotonic() - started
            return result

        environment = os.environ.copy()
        environment.update(
            {
                "OMP_NUM_THREADS": str(len(selected_cpus)),
                "OMP_DYNAMIC": "FALSE",
                # The child is already restricted to selected physical cores.
                # Leave workers migratable inside that set; binding the master
                # to one OpenMP place makes sched_getaffinity metadata appear
                # narrower than the process cpuset.
                "OMP_PROC_BIND": "FALSE",
            }
        )

        def enforce_affinity() -> None:
            if hasattr(os, "sched_setaffinity"):
                os.sched_setaffinity(0, set(selected_cpus))

        preexec_fn = enforce_affinity if hasattr(os, "sched_setaffinity") else None
        run_started = time.monotonic()
        try:
            executed = subprocess.run(
                [str(executable)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=45,
                check=False,
                cwd=temporary,
                env=environment,
                preexec_fn=preexec_fn,
            )
            metadata["affinity_enforced"] = preexec_fn is not None
        except subprocess.TimeoutExpired as error:
            result["status"] = "runtime_timeout"
            result["correctness"] = _empty_correctness("hidden driver exceeded 45 seconds")
            metadata["run_elapsed_seconds"] = time.monotonic() - run_started
            metadata["run_stderr"] = (error.stderr or "")[-8000:]
            metadata["total_elapsed_seconds"] = time.monotonic() - started
            return result
        metadata["run_elapsed_seconds"] = time.monotonic() - run_started
        metadata["run_returncode"] = executed.returncode
        metadata["run_stderr"] = executed.stderr[-8000:]
        try:
            driver_result = json.loads(executed.stdout)
        except (json.JSONDecodeError, TypeError) as error:
            result["status"] = "runtime_error"
            result["correctness"] = _empty_correctness(f"driver returned invalid JSON: {error}")
            metadata["run_stdout"] = executed.stdout[-8000:]
            metadata["total_elapsed_seconds"] = time.monotonic() - started
            return result

        result["correctness"] = driver_result["correctness"]
        result["workloads"] = driver_result.get("workloads", [])
        metadata["driver"] = driver_result.get("metadata", {})
        correctness_passed = bool(result["correctness"].get("passed"))
        if executed.returncode not in (0, 2) or (executed.returncode == 0) != correctness_passed:
            result["status"] = "runtime_error"
            result["correctness"]["passed"] = False
            result["correctness"]["failure"] = "driver exit status disagrees with its result"
        else:
            result["status"] = "ok" if correctness_passed else "correctness_failed"

        speedups = [float(workload["speedup"]) for workload in result["workloads"]]
        result["geomean_speedup"] = _geomean(speedups) if correctness_passed else 0.0
        if correctness_passed and tamper_check["passed"] and result["status"] == "ok":
            result["primary_score"] = result["geomean_speedup"]

    metadata["total_elapsed_seconds"] = time.monotonic() - started
    return result


def _write_atomic(path: Path, payload: str) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(payload)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    submission = parser.add_mutually_exclusive_group(required=True)
    submission.add_argument("--submission", type=Path, help="candidate project worktree")
    submission.add_argument("--workspace", type=Path, help="alias for --submission")
    parser.add_argument("--base-revision", help="pristine git commit used for diff checks")
    parser.add_argument("--output", type=Path, help="also write the JSON result to this path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = args.submission or args.workspace
    try:
        result = grade(workspace, args.base_revision)
    except Exception as error:  # Keep the runner's output machine-readable.
        result = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "status": "grader_error",
            "correctness": _empty_correctness(f"grader error: {error}"),
            "workloads": [],
            "geomean_speedup": 0.0,
            "primary_score": 0.0,
            "diff_check": {"passed": False},
            "tamper_check": {"passed": False, "violations": [str(error)]},
            "metadata": {},
        }
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if args.output:
        _write_atomic(args.output, payload)
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
