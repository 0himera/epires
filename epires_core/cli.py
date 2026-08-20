"""CLI Entrypoint implementation for Epires."""

from __future__ import annotations
import argparse
import asyncio
import json
import sys
import webbrowser
from pathlib import Path
from typing import List
import uvicorn

from .config import (
    EpiresProjectConfig,
    ProjectPaths,
    detect_project_profile,
    find_project_root,
)
from .setup import (
    setup_cursor,
    setup_claude_code,
    setup_opencode,
    setup_codex,
    setup_antigravity,
    setup_all,
)
from .store import EpiresStore
from server.app import create_app
from server.mcp_server import create_mcp_server
from tools.web_search import get_parallel_api_key, save_global_api_key


def generate_default_agents_md(config: EpiresProjectConfig) -> str:
    """Generates a standard AGENTS.md instruction file for the Lead-PI."""
    return f"""# AGENTS.md — Research Operating Protocol

> Project: **{config.project_name}** | Domain: **{config.domain}** | Target: **{config.primary_metric}**

## 1. Core Identity & Role
- **Role**: Principal Investigator (Lead-PI) & Research Overseer.
- **THE IRON LAW**: **The Lead-PI DOES NOT WRITE IMPLEMENTATION CODE**.
  - All script development, training loops, feature engineering, and test suites are strictly delegated to subagents.
  - The Lead-PI conducts literature search, gap analysis, hypothesis formulation, subagent contract enforcement, diff verification, and epistemic DAG logging.

---

## 2. Research Operating Loop
```
[Literature Search: parallel-web / native] ➔ [VSA Gap Discovery] ➔ [Register H-tag] ➔ [Contract Delegation] ➔ [Zero-Trust Diff Audit] ➔ [Log Evidence & DAG Update] ➔ [AutoTrace]
```

---

## 3. Hypothesis-First & Falsification Discipline
1. **Hypothesis-First**: No experiment may be executed without first registering the hypothesis in the VSA Hypergraph via `epires_register_hypothesis`.
2. **A Priori Justification**: Before empirics, prove the theoretical mechanism or mathematical basis of the claim.
3. **Popperian Falsification Criteria**: Explicitly define what numerical boundary falsifies the hypothesis.
4. **Evidence Scale (E0–E5)**:
   - `E0`: Speculative hypothesis (a priori reasoning only).
   - `E1`: Mechanism implemented and unit-tested.
   - `E2`: Descriptive / local smoke pass / replay verified.
   - `E3`: Targeted evaluation / cross-validation pass.
   - `E4`: Repeated out-of-time (OOT) validation with 95% Bootstrap CI.
   - `E5`: Final hidden-test / production-grade evidence.
5. **Source Provenance**: `[V]` (Verified primary code/data), `[P]` (Reported secondary), `[D]` (Derived).

---

## 4. MCP Tools Reference
- `epires_register_hypothesis`: Register new hypothesis with a priori mechanism and falsification criteria.
- `epires_log_evidence`: Record empirical evidence, update levels (E0..E5), and trigger cascading DAG invalidation.
- `epires_query_graph`: Inspect status (CONFIRMED, FALSIFIED, BLOCKED) and active hypotheses.
- `epires_find_gaps`: Discover unexplored parameter/feature/model combinations in the VSA Hypergraph.
- `epires_associative_search`: Sub-millisecond VSA cosine similarity search across research memory.
- `epires_parallel_web_search`: Multi-query parallel scientific web/ArXiv search.
- `epires_parallel_extract`: Extract structured markdown from specific research URLs.
- `epires_export_mermaid_dag`: Export current hypothesis DAG as Mermaid markdown.
- `epires_record_trace`: Record milestone rationale into SQLite and `docs/agent-trace.md`.

---

## 5. Subagent Delegation Contract
When delegating work to coder/runner subagents, enforce:
```markdown
### Subagent Task Contract: [H-TAG]
- **IN Scope**: [Specific file/module and function to write or optimize]
- **OUT of Scope**: [What the subagent must NOT touch]
- **Goal / Metric Target**: [Exact quantitative target]
- **Definition of Done (DoD)**: [Tests pass, artifacts saved to artifacts/..., no uncommitted files]
- **Output Constraint**: "Write detailed digest to artifacts/<name>.md and return a <= 10-line summary with exit code."
```

---

## 6. Zero-Trust Summary Rule
- **NEVER trust subagent summaries**.
- Inspect generated code diffs, logs, and artifact hashes directly before promoting evidence levels.
"""


def login_flow(key_arg: str | None = None) -> None:
    """Interactive authentication for Parallel Web Search."""
    print("\n==================== EPIRES PARALLEL AUTH ====================")
    if key_arg:
        key = key_arg.strip()
    else:
        print("[*] Opening Parallel Platform in your web browser: https://platform.parallel.ai ...")
        try:
            webbrowser.open("https://platform.parallel.ai")
        except Exception:
            pass
        print("Please copy your API key from https://platform.parallel.ai/settings/keys\n")
        try:
            key = input("Enter your Parallel API Key: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[!] Login cancelled.")
            return

    if not key:
        print("[!] No API key provided.")
        return

    saved_path = save_global_api_key(key)
    print(f"[+] Successfully authenticated! Credentials saved to: {saved_path}")
    print("    Parallel Web Search is now active globally across all your projects.\n")


def init_workspace(target_dir: str = ".", force: bool = False) -> None:
    """Initializes or configures an Epires research workspace non-destructively."""
    root = Path(target_dir).resolve()
    epires_dir = root / ".epires"
    epires_dir.mkdir(parents=True, exist_ok=True)

    profile = detect_project_profile(root)
    config_file = epires_dir / "config.json"

    # Load existing or create fresh config
    if config_file.exists() and not force:
        config = EpiresProjectConfig.load(root)
        print(f"[*] Found existing Epires configuration in {config_file}")
    else:
        config = EpiresProjectConfig(
            project_name=profile["project_name"],
            domain=profile["detected_domain"],
            primary_metric=profile["suggested_metric"],
            paths=ProjectPaths(
                db_path=".epires/hypotheses.db",
                trace_path="docs/agent-trace.md",
                artifacts_dir="artifacts"
            )
        )
        config.save(root)
        print(f"[+] Initialized .epires/config.json with domain: '{config.domain}'")

    # Safe append to .gitignore
    gitignore = root / ".gitignore"
    needed_rules = [".epires/*.db", ".epires/*.db-journal", ".epires/*.db-wal"]
    existing_content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    missing_rules = [r for r in needed_rules if r not in existing_content]
    if missing_rules:
        with open(gitignore, "a", encoding="utf-8") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            f.write("\n# Epires Local Research Database\n" + "\n".join(missing_rules) + "\n")
        print(f"[+] Safely updated {gitignore.name} with Epires database rules")

    # Create AGENTS.md if missing
    agents_file = root / config.lead_pi_protocol_file
    if not agents_file.exists() or force:
        agents_file.write_text(generate_default_agents_md(config), encoding="utf-8")
        print(f"[+] Created agent instructions: {agents_file.name}")
    else:
        print(f"[*] Existing {agents_file.name} detected. Kept untouched.")

    # Ensure trace markdown exists
    trace_path = root / config.paths.trace_path
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    if not trace_path.exists():
        trace_path.write_text(
            "# Agent Trace & Epistemic Log\n\n"
            f"> Project: **{config.project_name}** | Domain: **{config.domain}** | Target: **{config.primary_metric}**\n\n"
            "| Timestamp (UTC) | Role | Action | H-Tag | Commit | Summary |\n"
            "|---|---|---|---|---|---|\n",
            encoding="utf-8"
        )
        print(f"[+] Created trace ledger: {config.paths.trace_path}")

    # Setup MCP for IDEs
    configured = setup_all(root)
    print(f"[+] Configured MCP across: {', '.join(str(p.relative_to(root)) for p in configured)}")

    # Initialize empty DB if not present
    db_file = root / config.paths.db_path
    store = EpiresStore(db_path=db_file)
    print(f"[+] Verified local VSA Hypergraph database: {config.paths.db_path}")

    # Check Parallel API Key
    p_key = get_parallel_api_key()
    if p_key:
        print("[+] Parallel Web Search: Authenticated (global key detected)")
    else:
        print("[i] Parallel Web Search: Not configured. (Run 'epires login' once to enable parallel literature search)")

    print("\n==================================================================")
    if profile["is_empty"]:
        print("🌱 Clean / Empty Repository Onboarded!")
        print("   Ready for initial hypothesis formulation and baseline model.")
    else:
        print(f"🔬 Existing Repository Onboarded: {profile['project_name']}")
        print(f"   Detected Domain: {profile['detected_domain']}")
        print(f"   Detected Stack:  {profile['detected_stack']}")
        if profile["candidate_doc_files"]:
            print(f"   Candidate Docs:  {', '.join(profile['candidate_doc_files'])}")
    print("==================================================================\n")


def setup_flow(target_ide: str = "all", project_dir: str = ".") -> None:
    """Configures MCP for specific IDEs or all supported environments."""
    root = Path(project_dir).resolve()
    target_ide = target_ide.lower()

    print("\n==================== EPIRES MCP SETUP ====================")
    paths: List[Path] = []
    if target_ide == "cursor":
        paths = setup_cursor(root)
    elif target_ide in {"claude", "claude-code", "claude_code"}:
        paths = setup_claude_code(root)
    elif target_ide in {"opencode", "open-code"}:
        paths = setup_opencode(root)
    elif target_ide == "codex":
        paths = setup_codex(root)
    elif target_ide in {"antigravity", "agy", "gemini"}:
        paths = setup_antigravity(root)
    elif target_ide == "all":
        paths = setup_all(root)
    else:
        print(f"[!] Unknown IDE '{target_ide}'. Choose from: cursor, claude, opencode, codex, antigravity, all")
        return

    for p in paths:
        print(f"[+] Configured: {p.relative_to(root)}")
    print("==========================================================\n")


from . import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="epires",
        description="Epires: Epistemic Auto-Research Harness"
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"epires {__version__}",
        help="Show Epires version and exit."
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Version
    subparsers.add_parser("version", help="Print Epires version and exit")

    # Init
    init_parser = subparsers.add_parser("init", help="Initialize Epires in the current project")
    init_parser.add_argument("--dir", default=".", help="Project directory (default: current directory)")
    init_parser.add_argument("--force", action="store_true", help="Force overwrite config")

    # Setup
    setup_parser = subparsers.add_parser("setup", help="Configure MCP servers for IDEs and coding agents")
    setup_parser.add_argument(
        "ide",
        nargs="?",
        default="all",
        choices=["cursor", "claude", "claude-code", "opencode", "codex", "antigravity", "agy", "all"],
        help="Target IDE/Agent (default: all)"
    )
    setup_parser.add_argument("--dir", default=".", help="Project directory (default: current directory)")

    # Login
    login_parser = subparsers.add_parser("login", help="Authenticate with Parallel Web Search (saves globally)")
    login_parser.add_argument("--key", help="API key (optional; if omitted, opens browser)")

    # Recon
    recon_parser = subparsers.add_parser("recon", help="Scan and detect project topology and domain")
    recon_parser.add_argument("--dir", default=".", help="Project directory to scan")

    # Serve (FastAPI)
    serve_parser = subparsers.add_parser("serve", help="Start FastAPI REST server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host address")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port number")

    # MCP (Stdio Server)
    subparsers.add_parser("mcp", help="Start MCP stdio server for AI agents")

    # Status
    subparsers.add_parser("status", help="Print summary of research graph & evidence")

    # Mermaid
    subparsers.add_parser("dag", help="Print Mermaid diagram of hypothesis DAG")

    # Doctor
    subparsers.add_parser("doctor", help="Run comprehensive diagnostic checks on MCP, SQLite, and configuration")

    # Schema
    schema_parser = subparsers.add_parser("schema", help="Output canonical JSON Schema and Python SDK migration snippet")
    schema_parser.add_argument("--format", choices=["json", "python"], default="json", help="Output format (default: json)")

    # Ingest
    ingest_parser = subparsers.add_parser("ingest", help="Bulk import hypotheses & evidence from Markdown, JSON, or JSONL")
    ingest_parser.add_argument("file", nargs="?", default=None, help="Path to findings.md, hypotheses.json, or experiments.jsonl (auto-detected if omitted)")
    ingest_parser.add_argument("--dry-run", action="store_true", help="Preview extracted records without modifying database")
    ingest_parser.add_argument("--upsert", action="store_true", default=True, help="Update existing hypotheses if present (default: True)")
    ingest_parser.add_argument("--no-upsert", action="store_false", dest="upsert", help="Do not overwrite existing hypotheses")
    ingest_parser.add_argument("--template", nargs="?", const="scripts/migrate_findings.py", default=None, help="Generate a customized Python migration script template (default: scripts/migrate_findings.py)")

    # Export
    export_parser = subparsers.add_parser("export", help="Export research graph to portable JSON bundle with SHA256 checksum")
    export_parser.add_argument("--out", "-o", default=None, help="Output file path (default: stdout or research-graph.json)")
    export_parser.add_argument("--format", choices=["json", "jsonl"], default="json", help="Export format (default: json)")

    # Import
    import_parser = subparsers.add_parser("import", help="Import research graph from JSON bundle")
    import_parser.add_argument("file", nargs="?", default="research-graph.json", help="Path to exported graph bundle JSON file (default: research-graph.json)")
    import_parser.add_argument("--dry-run", action="store_true", help="Preview import without modifying database")
    import_parser.add_argument("--upsert", action="store_true", default=True, help="Upsert existing hypotheses (default: True)")

    args = parser.parse_args()

    if args.command == "init":
        init_workspace(target_dir=args.dir, force=args.force)

    elif args.command == "setup":
        setup_flow(target_ide=args.ide, project_dir=args.dir)

    elif args.command == "login":
        login_flow(key_arg=args.key)

    elif args.command == "recon":
        profile = detect_project_profile(args.dir)
        print(json.dumps(profile, indent=2, ensure_ascii=False))

    elif args.command == "doctor":
        from .doctor import run_epires_doctor, print_doctor_report
        checks = run_epires_doctor()
        ok = print_doctor_report(checks)
        sys.exit(0 if ok else 1)

    elif args.command == "schema":
        from .schema import get_canonical_schema
        schema_data = get_canonical_schema()
        if args.format == "python":
            print(schema_data["python_quickstart"].strip())
        else:
            print(json.dumps(schema_data, indent=2, ensure_ascii=False))

    elif args.command == "ingest":
        from .importer import ingest_file
        from .schema import generate_migration_script_template
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))

        if args.template:
            template_path = root / args.template
            template_path.parent.mkdir(parents=True, exist_ok=True)
            source_candidate = args.file or "docs/findings-and-hypotheses.md"
            template_code = generate_migration_script_template(source_file=source_candidate)
            template_path.write_text(template_code, encoding="utf-8")
            print(f"[+] Created custom migration template: {template_path.relative_to(root)}")
            print(f"    Edit {template_path.name} to match your repo notes and run: python {template_path.relative_to(root)}")
            return

        if not args.file:
            candidates = [
                root / "findings.md",
                root / "hypotheses.md",
                root / "experiments.md",
                root / "research.md",
                root / "notes.md",
                root / "docs" / "findings.md",
                root / "docs" / "hypotheses.md",
                root / "docs" / "research.md",
                root / "README.md",
            ]
            found = [c for c in candidates if c.exists()]
            if not found:
                print("[!] No findings file found. Please specify file: epires ingest <path/to/findings.md>")
                sys.exit(1)
            target_file = found[0]
            print(f"[*] Auto-detected research findings file: {target_file.relative_to(root)}")
        else:
            target_file = Path(args.file).resolve()

        print(f"[*] Ingesting research findings from {target_file.name} ...")
        res = ingest_file(store=store, file_path=target_file, dry_run=args.dry_run, upsert=args.upsert)

        if args.dry_run:
            print("\n[DRY RUN PREVIEW]")
            print(f"  Recognized Hypotheses: {res.get('hypotheses_count', 0)}")
            print(f"  Recognized Evidence:   {res.get('evidence_count', 0)}")
            if "hypotheses" in res:
                for h in res["hypotheses"]:
                    print(f"    - [{h['id']}] {h['title']} (Status: {h['status']})")
            print("\nRun without --dry-run to commit records into SQLite research database.")
        else:
            print(f"[+] Successfully ingested {res.get('hypotheses_ingested', 0)} hypotheses and {res.get('evidence_ingested', 0)} evidence claims.")
            print(f"[+] Total database state: {res.get('total_hypotheses', 0)} hypotheses, {res.get('total_evidence', 0)} evidence records.")

    elif args.command == "export":
        from .importer import export_graph_bundle
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        bundle = export_graph_bundle(store=store, project_name=config.project_name)

        if args.format == "jsonl":
            lines = []
            for h in bundle["hypotheses"]:
                lines.append(json.dumps({"type": "hypothesis", **h}, ensure_ascii=False))
            for ev in bundle["evidence"]:
                lines.append(json.dumps({"type": "evidence", **ev}, ensure_ascii=False))
            out_str = "\n".join(lines)
        else:
            out_str = json.dumps(bundle, indent=2, ensure_ascii=False)

        if args.out:
            out_path = Path(args.out).resolve()
            out_path.write_text(out_str, encoding="utf-8")
            print(f"[+] Exported research graph ({bundle['counts']['hypotheses']} hypotheses, {bundle['counts']['evidence']} evidence) to {out_path}")
            print(f"    SHA256 Checksum: {bundle['checksum_sha256']}")
        else:
            print(out_str)

    elif args.command == "import":
        from .importer import import_graph_bundle
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        import_path = Path(args.file).resolve()

        bundle = json.loads(import_path.read_text(encoding="utf-8"))
        res = import_graph_bundle(store=store, bundle=bundle, upsert=args.upsert, dry_run=args.dry_run)

        if args.dry_run:
            print(f"[DRY RUN] Would import {res['hypotheses_count']} hypotheses and {res['evidence_count']} evidence records.")
        else:
            print(f"[+] Successfully imported {res.get('hypotheses_ingested', 0)} hypotheses and {res.get('evidence_ingested', 0)} evidence claims.")

    elif args.command == "serve":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        app = create_app(db_path=str(root / config.paths.db_path), trace_md=str(root / config.paths.trace_path))
        print(f"[*] Starting Epires FastAPI server for '{config.project_name}' on {args.host}:{args.port} ...")
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "mcp":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        mcp = create_mcp_server(db_path=str(root / config.paths.db_path), trace_md=str(root / config.paths.trace_path))
        asyncio.run(mcp.run_stdio_async())

    elif args.command == "status":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        hypotheses = store.list_hypotheses()
        print(f"\n==================== EPIRES: {config.project_name.upper()} ====================")
        print(f"Domain: {config.domain} | Target Metric: {config.primary_metric}")
        print(f"Total Hypotheses: {len(hypotheses)}")
        for h in hypotheses:
            status_icon = {
                "CONFIRMED": "🟢",
                "FALSIFIED": "🔴",
                "BLOCKED": "⚫",
                "IN_PROGRESS": "🟡",
                "PROPOSED": "🔵",
                "REFINED": "🟣"
            }.get(h.status.value, "⚪")
            print(f"{status_icon} [{h.id}] {h.title} (Level: {h.current_evidence_level.value}, Status: {h.status.value})")
        print("================================================================\n")

    elif args.command == "version":
        print(f"epires {__version__}")

    elif args.command == "dag":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        print(store.export_mermaid_dag())

    else:
        parser.print_help()
