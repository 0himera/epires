"""Tests for IDE and Agent MCP Setup configurations."""

import json
from pathlib import Path
import tempfile

from epires_core.setup import (
    setup_cursor,
    setup_claude_code,
    setup_opencode,
    setup_codex,
    setup_antigravity,
    setup_all,
)


def test_setup_cursor():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = setup_cursor(tmpdir)
        assert len(paths) >= 2
        mcp_file = Path(tmpdir) / ".cursor" / "mcp.json"
        assert mcp_file.exists()
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        assert "epires" in data["mcpServers"]
        assert data["mcpServers"]["epires"]["command"] == "epires"

        # Check cursor rule .cursor/rules/epires.mdc
        rules_file = Path(tmpdir) / ".cursor" / "rules" / "epires.mdc"
        assert rules_file.exists()


def test_setup_claude_code():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = setup_claude_code(tmpdir)
        assert len(paths) >= 2
        mcp_file = Path(tmpdir) / ".mcp.json"
        assert mcp_file.exists()
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
        assert "epires" in data["mcpServers"]

        # Check skill file
        skill_file = Path(tmpdir) / ".claude" / "skills" / "epires" / "SKILL.md"
        assert skill_file.exists()


def test_setup_opencode():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = setup_opencode(tmpdir)
        assert len(paths) >= 2
        opencode_file = Path(tmpdir) / "opencode.json"
        assert opencode_file.exists()
        data = json.loads(opencode_file.read_text(encoding="utf-8"))
        assert "epires" in data["mcp"]
        assert "$schema" in data

        # Check skill file
        skill_file = Path(tmpdir) / ".opencode" / "skills" / "epires" / "SKILL.md"
        assert skill_file.exists()


def test_setup_codex():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = setup_codex(tmpdir)
        assert len(paths) >= 2
        mcp_file = Path(tmpdir) / ".codex" / "mcp.json"
        assert mcp_file.exists()


def test_setup_antigravity():
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = setup_antigravity(tmpdir)
        assert len(paths) >= 2
        mcp_file = Path(tmpdir) / ".gemini" / "mcp.json"
        assert mcp_file.exists()


def test_setup_all_merges_preserving_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        cursor_file = Path(tmpdir) / ".cursor" / "mcp.json"
        cursor_file.parent.mkdir(parents=True, exist_ok=True)
        cursor_file.write_text(json.dumps({
            "mcpServers": {
                "existing_custom_server": {"command": "custom", "args": []}
            }
        }), encoding="utf-8")

        setup_all(tmpdir)

        # Verify preservation of existing server + addition of epires
        data = json.loads(cursor_file.read_text(encoding="utf-8"))
        assert "existing_custom_server" in data["mcpServers"]
        assert "epires" in data["mcpServers"]
