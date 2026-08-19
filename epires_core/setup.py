"""IDE & Agent Setup Manager for Epires.

Configures MCP servers, Skills, and Rules across:
- Cursor (.cursor/mcp.json, .cursor/rules/epires.mdc, .cursor/skills/epires/SKILL.md)
- Claude Code (.mcp.json, CLAUDE.md, .claude/skills/epires/SKILL.md)
- OpenCode (opencode.json with "mcp", .opencode/skills/epires/SKILL.md)
- OpenAI Codex (.codex/mcp.json, .codex/instructions.md)
- Google Antigravity (.gemini/mcp.json, .gemini/skills/epires/SKILL.md)
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_skill_content() -> str:
    """Returns the standard Lead-PI researcher skill markdown content."""
    skill_file = Path(__file__).resolve().parent.parent / "skills" / "epires_researcher" / "SKILL.md"
    if skill_file.exists():
        return skill_file.read_text(encoding="utf-8")
    
    return """---
name: epires_researcher
description: Operating protocol and cognitive scaffolding for the Principal Investigator (Lead-PI) in Epires.
---

# Epires Researcher Protocol — Lead-PI Standard

## Core Law:
The Lead-PI NEVER WRITES implementation code. Coding is strictly delegated to subagents.

## Workflow:
1. Literature Search (epires_parallel_web_search / native).
2. Gap Analysis (epires_find_gaps).
3. Hypothesis Registration (epires_register_hypothesis).
4. Subagent Contract Delegation (IN/OUT scope, Target Metric, DoD).
5. Zero-Trust Diff Audit.
6. Evidence Logging & DAG Update (epires_log_evidence).
7. Trace Ledger Sync (epires_record_trace).
"""


def _merge_json(file_path: Path, mutator_fn) -> None:
    """Safely updates or creates a JSON configuration file preserving other fields."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {}
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    mutator_fn(data)
    file_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def setup_cursor(project_dir: str | Path = ".") -> List[Path]:
    """Configures Cursor MCP and Rules."""
    root = Path(project_dir).resolve()
    configured = []

    # 1. .cursor/mcp.json
    mcp_file = root / ".cursor" / "mcp.json"
    def update_cursor_mcp(d: Dict[str, Any]):
        if "mcpServers" not in d or not isinstance(d["mcpServers"], dict):
            d["mcpServers"] = {}
        d["mcpServers"]["epires"] = {
            "command": "epires",
            "args": ["mcp"],
            "cwd": str(root)
        }
    _merge_json(mcp_file, update_cursor_mcp)
    configured.append(mcp_file)

    # 2. .cursor/rules/epires.mdc
    rules_file = root / ".cursor" / "rules" / "epires.mdc"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(
        "---\ndescription: Epires Auto-Research Harness Lead-PI Protocol\nglobs: *\nalwaysApply: true\n---\n\n"
        + get_skill_content(),
        encoding="utf-8"
    )
    configured.append(rules_file)

    # 3. .cursor/skills/epires/SKILL.md
    skill_file = root / ".cursor" / "skills" / "epires" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(get_skill_content(), encoding="utf-8")
    configured.append(skill_file)

    return configured


def setup_claude_code(project_dir: str | Path = ".") -> List[Path]:
    """Configures Claude Code MCP and Skill."""
    root = Path(project_dir).resolve()
    configured = []

    # 1. .mcp.json
    mcp_file = root / ".mcp.json"
    def update_claude_mcp(d: Dict[str, Any]):
        if "mcpServers" not in d or not isinstance(d["mcpServers"], dict):
            d["mcpServers"] = {}
        d["mcpServers"]["epires"] = {
            "command": "epires",
            "args": ["mcp"],
            "cwd": str(root)
        }
    _merge_json(mcp_file, update_claude_mcp)
    configured.append(mcp_file)

    # 2. .claude/skills/epires/SKILL.md
    skill_file = root / ".claude" / "skills" / "epires" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(get_skill_content(), encoding="utf-8")
    configured.append(skill_file)

    return configured


def setup_opencode(project_dir: str | Path = ".") -> List[Path]:
    """Configures OpenCode V1 and OpenCode 2 (opencode2) configs and skills."""
    root = Path(project_dir).resolve()
    configured = []

    def update_opencode_schema(d: Dict[str, Any]):
        if "$schema" not in d:
            d["$schema"] = "https://opencode.ai/config.json"
        
        # OpenCode V1 syntax
        if "mcp" not in d or not isinstance(d["mcp"], dict):
            d["mcp"] = {}
        d["mcp"]["epires"] = {
            "type": "local",
            "command": ["epires", "mcp"],
            "enabled": True
        }

        # OpenCode V2 (opencode2) syntax
        if "servers" not in d["mcp"] or not isinstance(d["mcp"]["servers"], dict):
            d["mcp"]["servers"] = {}
        d["mcp"]["servers"]["epires"] = {
            "type": "local",
            "command": ["epires", "mcp"],
            "enabled": True
        }

        # Standard mcpServers fallback
        if "mcpServers" not in d or not isinstance(d["mcpServers"], dict):
            d["mcpServers"] = {}
        d["mcpServers"]["epires"] = {
            "command": "epires",
            "args": ["mcp"],
            "cwd": str(root)
        }

    # 1. Project-root opencode.json
    opencode_root = root / "opencode.json"
    _merge_json(opencode_root, update_opencode_schema)
    configured.append(opencode_root)

    # 2. .opencode/opencode.json (for OpenCode 2 nested discovery)
    opencode_nested = root / ".opencode" / "opencode.json"
    _merge_json(opencode_nested, update_opencode_schema)
    configured.append(opencode_nested)

    # 3. .opencode/skills/epires/SKILL.md
    skill_file = root / ".opencode" / "skills" / "epires" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(get_skill_content(), encoding="utf-8")
    configured.append(skill_file)

    return configured


def setup_codex(project_dir: str | Path = ".") -> List[Path]:
    """Configures OpenAI Codex in .codex/mcp.json and instructions."""
    root = Path(project_dir).resolve()
    configured = []

    # 1. .codex/mcp.json
    mcp_file = root / ".codex" / "mcp.json"
    def update_codex_mcp(d: Dict[str, Any]):
        if "mcpServers" not in d or not isinstance(d["mcpServers"], dict):
            d["mcpServers"] = {}
        d["mcpServers"]["epires"] = {
            "command": "epires",
            "args": ["mcp"],
            "cwd": str(root)
        }
    _merge_json(mcp_file, update_codex_mcp)
    configured.append(mcp_file)

    # 2. .codex/instructions.md
    instr_file = root / ".codex" / "instructions.md"
    instr_file.parent.mkdir(parents=True, exist_ok=True)
    instr_file.write_text(get_skill_content(), encoding="utf-8")
    configured.append(instr_file)

    return configured


def setup_antigravity(project_dir: str | Path = ".") -> List[Path]:
    """Configures Google Antigravity (.gemini/mcp.json & skills)."""
    root = Path(project_dir).resolve()
    configured = []

    # 1. .gemini/mcp.json
    mcp_file = root / ".gemini" / "mcp.json"
    def update_agy_mcp(d: Dict[str, Any]):
        if "mcpServers" not in d or not isinstance(d["mcpServers"], dict):
            d["mcpServers"] = {}
        d["mcpServers"]["epires"] = {
            "command": "epires",
            "args": ["mcp"],
            "cwd": str(root)
        }
    _merge_json(mcp_file, update_agy_mcp)
    configured.append(mcp_file)

    # 2. .gemini/skills/epires/SKILL.md
    skill_file = root / ".gemini" / "skills" / "epires" / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(get_skill_content(), encoding="utf-8")
    configured.append(skill_file)

    return configured


def setup_all(project_dir: str | Path = ".") -> List[Path]:
    """Configures MCP and Skills across all supported environments."""
    root = Path(project_dir).resolve()
    configured: List[Path] = []
    for fn in [setup_cursor, setup_claude_code, setup_opencode, setup_codex, setup_antigravity]:
        configured.extend(fn(root))
    
    seen = set()
    result = []
    for p in configured:
        if str(p) not in seen:
            seen.add(str(p))
            result.append(p)
    return result
