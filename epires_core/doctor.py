"""System Health, Diagnostic, and MCP Doctor for Epires."""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List

from .config import EpiresProjectConfig, find_project_root
from .store import EpiresStore
from server.mcp_server import create_mcp_server
from tools.web_search import get_parallel_api_key


class DoctorCheck:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.passed: bool = False
        self.warning: bool = False
        self.message: str = ""
        self.details: Dict[str, Any] = {}

    def pass_check(self, message: str, **details: Any) -> None:
        self.passed = True
        self.warning = False
        self.message = message
        self.details = details

    def warn_check(self, message: str, **details: Any) -> None:
        self.passed = True
        self.warning = True
        self.message = message
        self.details = details

    def fail_check(self, message: str, **details: Any) -> None:
        self.passed = False
        self.warning = False
        self.message = message
        self.details = details


def run_epires_doctor(project_dir: Path | None = None) -> List[DoctorCheck]:
    """Runs a complete battery of diagnostic checks on the Epires installation."""
    checks: List[DoctorCheck] = []
    root = find_project_root(project_dir or Path.cwd())

    # 1. Python runtime
    c_py = DoctorCheck("Python Environment", "Verifies supported Python version")
    py_ver = sys.version_info
    if py_ver >= (3, 10):
        c_py.pass_check(f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} ({sys.executable})")
    else:
        c_py.fail_check(f"Python {py_ver.major}.{py_ver.minor} is unsupported. Epires requires Python >= 3.10")
    checks.append(c_py)

    # 2. Project Config (.epires/config.json)
    c_cfg = DoctorCheck("Project Configuration", "Validates .epires/config.json profile")
    config_file = root / ".epires" / "config.json"
    if config_file.exists():
        try:
            cfg = EpiresProjectConfig.load(root)
            c_cfg.pass_check(
                f"Project: '{cfg.project_name}' | Domain: '{cfg.domain}' | Metric: '{cfg.primary_metric}'",
                domain=cfg.domain,
                metric=cfg.primary_metric,
            )
        except Exception as e:
            c_cfg.fail_check(f"Malformed config.json: {e}")
    else:
        c_cfg.warn_check("No .epires/config.json found. Run 'epires init' to initialize.")
    checks.append(c_cfg)

    # 3. Database Integrity & VSA Tables
    c_db = DoctorCheck("SQLite Research Database", "Checks database file and schema integrity")
    db_file = root / ".epires" / "hypotheses.db"
    if db_file.exists():
        try:
            store = EpiresStore(db_path=str(db_file))
            with store._get_connection() as conn:
                res = conn.execute("PRAGMA integrity_check;").fetchone()
                integrity_ok = res and res[0] == "ok"

            if integrity_ok:
                hypotheses = store.list_hypotheses()
                evidence = store.list_evidence()
                traces = store.list_traces(limit=10000)
                c_db.pass_check(
                    f"Database OK ({len(hypotheses)} hypotheses, {len(evidence)} evidence records, {len(traces)} traces)",
                    hypotheses_count=len(hypotheses),
                    evidence_count=len(evidence),
                )
            else:
                c_db.fail_check(f"SQLite PRAGMA integrity check failed: {res}")
        except Exception as e:
            c_db.fail_check(f"Database error: {e}")
    else:
        c_db.warn_check(f"Database file not yet created at {db_file}. Will be generated on first registration.")
    checks.append(c_db)

    # 3b. Database Redundancy & Ambiguity Check
    c_db_redundancy = DoctorCheck(
        "Database Architecture Cleanliness", "Detects obsolete or duplicate SQLite databases in .epires/"
    )
    epires_dir = root / ".epires"
    if epires_dir.exists():
        all_dbs = [f for f in epires_dir.glob("*.db") if not f.name.endswith(("-journal", "-wal", "-shm"))]
        legacy_dbs = [f.name for f in all_dbs if f.name != "hypotheses.db"]
        if legacy_dbs:
            c_db_redundancy.warn_check(
                f"Multiple/legacy database files detected in .epires/: {', '.join(legacy_dbs)}. Canonical database is 'hypotheses.db'.",
                redundant_databases=legacy_dbs,
            )
        else:
            c_db_redundancy.pass_check("Clean single database architecture (.epires/hypotheses.db)")
    else:
        c_db_redundancy.pass_check("No .epires directory created yet")
    checks.append(c_db_redundancy)

    # 4. MCP Server & Live Tool Registry
    c_mcp = DoctorCheck("MCP Server & Tool Registry", "Spawns MCPServer and verifies tool availability")
    try:
        mcp = create_mcp_server(db_path=str(db_file))
        tools = mcp._tool_manager.list_tools()
        tool_names = [t.name for t in tools]
        expected_tools = [
            "epires_get_schema",
            "epires_register_hypothesis",
            "epires_register_experiment",
            "epires_list_experiments",
            "epires_log_evidence",
            "epires_retract_evidence",
            "epires_update_hypothesis",
            "epires_add_relation",
            "epires_list_relations",
            "epires_bulk_import",
            "epires_export_graph",
            "epires_import_graph",
            "epires_query_graph",
            "epires_find_gaps",
            "epires_associative_search",
            "epires_export_mermaid_dag",
            "epires_parallel_web_search",
            "epires_parallel_extract",
            "epires_record_trace",
            "epires_system_status",
        ]
        registered_count = len(tool_names)
        missing = [t for t in expected_tools if t not in tool_names]
        if missing:
            c_mcp.warn_check(f"MCP Server missing expected tools: {', '.join(missing)}")
        else:
            c_mcp.pass_check(
                f"MCP Server active with {registered_count} tools registered and ready for agents.", tools=tool_names
            )
    except Exception as e:
        c_mcp.fail_check(f"Failed to instantiate MCP server: {e}")
    checks.append(c_mcp)

    # 5. MCP Client Configs in Workspace
    c_clients = DoctorCheck("IDE & Agent MCP Configs", "Detects client configuration files")
    detected_clients: List[str] = []
    if (root / ".codex" / "config.toml").exists():
        detected_clients.append("Codex (.codex/config.toml)")
    elif (root / ".codex" / "mcp.json").exists():
        detected_clients.append("Codex (.codex/mcp.json)")
    if (root / ".cursor" / "mcp.json").exists():
        detected_clients.append("Cursor (.cursor/mcp.json)")
    if (root / ".vscode" / "mcp.json").exists():
        detected_clients.append("VS Code (.vscode/mcp.json)")
    if (root / ".mcp.json").exists() or (root / "claude.json").exists():
        detected_clients.append("Claude Code (.mcp.json)")
    elif (Path.home() / ".claude.json").exists():
        detected_clients.append("Claude Code (global ~/.claude.json)")
    if (root / "opencode.json").exists() or (root / ".opencode" / "opencode.json").exists():
        detected_clients.append("OpenCode (opencode.json)")
    if (root / ".gemini" / "mcp.json").exists():
        detected_clients.append("Antigravity (.gemini/mcp.json)")
    if (root / "AGENTS.md").exists():
        detected_clients.append("AGENTS.md Protocol")

    if detected_clients:
        c_clients.pass_check(f"Detected: {', '.join(detected_clients)}")
    else:
        c_clients.warn_check(
            "No IDE MCP configs detected in workspace. Run 'epires init' or 'epires setup <ide>' to configure."
        )
    checks.append(c_clients)

    # 6. Parallel Web Search API
    c_web = DoctorCheck("Parallel Web Search", "Checks ArXiv/literature search connectivity")
    api_key = get_parallel_api_key()
    if api_key:
        c_web.pass_check("Parallel API key configured (Multi-query search active)")
    else:
        c_web.warn_check(
            "Parallel API key not configured (Native agent search fallback will be used). Run 'epires login' to set key."
        )
    checks.append(c_web)

    return checks


def print_doctor_report(checks: List[DoctorCheck]) -> bool:
    """Pretty prints the doctor diagnostic report to stdout. Returns True if all passed/warned."""
    print("=" * 72)
    print("  EPIRES DIAGNOSTIC DOCTOR & MCP CONNECTIVITY REPORT")
    print("=" * 72)

    all_ok = True
    for c in checks:
        if not c.passed:
            all_ok = False
            symbol = "❌ FAIL"
        elif c.warning:
            symbol = "⚠️  WARN"
        else:
            symbol = "✅ PASS"

        print(f"\n{symbol}  [{c.name}]")
        print(f"       {c.message}")

    print("\n" + "-" * 72)
    if all_ok:
        print("  All essential systems verified. Epires is ready for auto-research.")
    else:
        print("  Issues detected. Please review the failed checks above.")
    print("=" * 72)
    return all_ok
