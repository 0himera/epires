"""Tests for epires doctor diagnostic checks."""

import tempfile
from pathlib import Path

from epires_core.doctor import run_epires_doctor, print_doctor_report


def test_doctor_diagnostics():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        checks = run_epires_doctor(project_dir=tmp_path)
        assert len(checks) >= 5

        # Python check must pass
        py_check = next(c for c in checks if c.name == "Python Environment")
        assert py_check.passed is True

        # MCP check must pass
        mcp_check = next(c for c in checks if c.name == "MCP Server & Tool Registry")
        assert mcp_check.passed is True
        assert len(mcp_check.details.get("tools", [])) == 16

        # Report printer
        all_ok = print_doctor_report(checks)
        assert all_ok is True
