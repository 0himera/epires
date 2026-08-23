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
                db_path=".epires/hypotheses.db", trace_path="docs/agent-trace.md", artifacts_dir="artifacts"
            ),
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
            encoding="utf-8",
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
    parser = argparse.ArgumentParser(prog="epires", description="Epires: Epistemic Auto-Research Harness")
    parser.add_argument(
        "-v", "--version", action="version", version=f"epires {__version__}", help="Show Epires version and exit."
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
        help="Target IDE/Agent (default: all)",
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

    # Status & Summary
    subparsers.add_parser("status", help="Print summary of research graph & evidence")
    subparsers.add_parser("summary", help="Print compact JSON summary of research state")

    # Mermaid DAG
    dag_parser = subparsers.add_parser("dag", help="Print Mermaid diagram of hypothesis DAG")
    dag_parser.add_argument(
        "--frontier",
        action="store_true",
        help="Filter DAG to active frontier (PROPOSED & IN_PROGRESS nodes + immediate parents)",
    )
    dag_parser.add_argument(
        "--status",
        default=None,
        help="Comma-separated status filter (e.g. 'CONFIRMED,IN_PROGRESS')",
    )
    dag_parser.add_argument(
        "--root",
        "-r",
        default=None,
        help="Root hypothesis ID to extract connected subtree",
    )
    dag_parser.add_argument(
        "--depth",
        "-d",
        type=int,
        default=-1,
        help="Max hop depth from root hypothesis (-1 for full connected component)",
    )

    # Compute Gate
    gate_parser = subparsers.add_parser(
        "compute-gate", help="Evaluate results against hypothesis falsification criteria and statistical gates"
    )
    gate_parser.add_argument("hypothesis_id", help="Target hypothesis ID")
    gate_parser.add_argument("--results", "-r", default=None, help="Path to results.json")
    gate_parser.add_argument("--metric-name", "-m", default=None, help="Observed metric name")
    gate_parser.add_argument("--metric-value", "-v", type=float, default=None, help="Observed metric value")
    gate_parser.add_argument("--delta", default=None, type=float, help="Delta vs baseline")
    gate_parser.add_argument("--ci-lower", type=float, default=None, help="95% CI lower bound")
    gate_parser.add_argument("--ci-upper", type=float, default=None, help="95% CI upper bound")

    # Multihop VSA
    multihop_parser = subparsers.add_parser(
        "multihop", help="Execute 2-hop relational causal query on VSA knowledge graph"
    )
    multihop_parser.add_argument("head_id", help="Source/Head hypothesis ID")
    multihop_parser.add_argument("rel1", help="First relation type (e.g. BLOCKS)")
    multihop_parser.add_argument("rel2", help="Second relation type (e.g. GATED_BY)")
    multihop_parser.add_argument("--top-k", "-k", type=int, default=5, help="Number of top candidates")

    # Context Compressor
    compress_parser = subparsers.add_parser(
        "compress", help="Compress recent trace history into dense VSA semantic digest"
    )
    compress_parser.add_argument("--limit", "-n", type=int, default=50, help="Number of recent traces to compress")

    # Doctor
    subparsers.add_parser("doctor", help="Run comprehensive diagnostic checks on MCP, SQLite, and configuration")

    # Schema
    schema_parser = subparsers.add_parser(
        "schema", help="Output canonical JSON Schema and Python SDK migration snippet"
    )
    schema_parser.add_argument(
        "--format", choices=["json", "python"], default="json", help="Output format (default: json)"
    )

    # Ingest
    ingest_parser = subparsers.add_parser(
        "ingest", help="Bulk import hypotheses & evidence from Markdown, JSON, or JSONL"
    )
    ingest_parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to findings.md, hypotheses.json, or experiments.jsonl (auto-detected if omitted)",
    )
    ingest_parser.add_argument(
        "--dry-run", action="store_true", help="Preview extracted records without modifying database"
    )
    ingest_parser.add_argument(
        "--upsert", action="store_true", default=True, help="Update existing hypotheses if present (default: True)"
    )
    ingest_parser.add_argument(
        "--no-upsert", action="store_false", dest="upsert", help="Do not overwrite existing hypotheses"
    )
    ingest_parser.add_argument(
        "--template",
        nargs="?",
        const="scripts/migrate_findings.py",
        default=None,
        help="Generate a customized Python migration script template (default: scripts/migrate_findings.py)",
    )

    # Export
    export_parser = subparsers.add_parser(
        "export", help="Export research graph to portable JSON bundle with SHA256 checksum"
    )
    export_parser.add_argument(
        "--out", "-o", default=None, help="Output file path (default: stdout or research-graph.json)"
    )
    export_parser.add_argument(
        "--format", choices=["json", "jsonl"], default="json", help="Export format (default: json)"
    )

    # Import
    import_parser = subparsers.add_parser("import", help="Import research graph from JSON bundle")
    import_parser.add_argument(
        "file",
        nargs="?",
        default="research-graph.json",
        help="Path to exported graph bundle JSON file (default: research-graph.json)",
    )
    import_parser.add_argument("--dry-run", action="store_true", help="Preview import without modifying database")
    import_parser.add_argument(
        "--upsert", action="store_true", default=True, help="Upsert existing hypotheses (default: True)"
    )

    # Audit
    audit_parser = subparsers.add_parser("audit", help="Run deterministic/S3* audit on hypotheses")
    audit_parser.add_argument("--h-id", "-H", default=None, help="Specific hypothesis ID to audit")
    audit_parser.add_argument("--deep", action="store_true", help="Run S3* LLM independent audit on target")
    audit_parser.add_argument("--strict", action="store_true", help="Enforce strict gate rules (EPIRES_STRICT_GATES=1)")

    # POSIWID
    posiwid_parser = subparsers.add_parser("posiwid", help="Compute POSIWID integrity metrics and status distribution")
    posiwid_parser.add_argument("--json", action="store_true", help="Output raw JSON format")

    # Algedonic
    algedonic_parser = subparsers.add_parser(
        "algedonic", help="Check algedonic bypass pain signals and freeze failing subtrees"
    )
    algedonic_parser.add_argument("--threshold", type=int, default=3, help="Cascade failures threshold (default: 3)")
    algedonic_parser.add_argument("--freeze", default=None, help="Freeze downstream branch for given hypothesis ID")
    algedonic_parser.add_argument(
        "--active-only", action="store_true", help="Only check active IN_PROGRESS and CONFIRMED hypotheses"
    )
    algedonic_parser.add_argument(
        "--min-level", choices=["E0", "E1", "E2", "E3", "E4", "E5"], default="E0", help="Minimum evidence level"
    )

    # Synthesis
    synthesis_parser = subparsers.add_parser(
        "synthesis", help="Generate comprehensive Markdown Epistemic Synthesis Report"
    )
    synthesis_parser.add_argument("--out", "-o", default=None, help="Output markdown file path (default: stdout)")

    # Register Hypothesis
    reg_parser = subparsers.add_parser(
        "register-hypothesis", aliases=["register"], help="Register a new hypothesis in the epistemic hypergraph"
    )
    reg_parser.add_argument("--id", "-i", "-H", required=True, help="Unique hypothesis ID (e.g., H93, VSAR-025)")
    reg_parser.add_argument("--title", "-t", required=True, help="Descriptive hypothesis title")
    reg_parser.add_argument(
        "--mechanism", "-m", required=True, help="A priori theoretical mechanism / mathematical justification"
    )
    reg_parser.add_argument(
        "--criteria", "-c", required=True, help="Popperian falsification criteria (e.g., 'delta < 0')"
    )
    reg_parser.add_argument("--parents", "-p", default="", help="Comma-separated parent hypothesis IDs")
    reg_parser.add_argument(
        "--status",
        "-s",
        choices=["PROPOSED", "IN_PROGRESS", "CONFIRMED", "FALSIFIED", "BLOCKED", "REFINED"],
        default="PROPOSED",
        help="Initial status (default: PROPOSED)",
    )
    reg_parser.add_argument(
        "--target-level",
        "-l",
        choices=["E0", "E1", "E2", "E3", "E4", "E5"],
        default="E3",
        help="Target evidence level (default: E3)",
    )
    reg_parser.add_argument("--domain", default=None, help="Domain override")
    reg_parser.add_argument("--primary-metric", default=None, help="Primary metric override")

    # Log Evidence
    ev_parser = subparsers.add_parser(
        "log-evidence", aliases=["evidence"], help="Log empirical evidence claim and update hypothesis status"
    )
    ev_parser.add_argument("--hypothesis", "-H", "-i", required=True, help="Target hypothesis ID (e.g. H92-T1)")
    ev_parser.add_argument("--claim", "-c", required=True, help="Empirical evidence claim text")
    ev_parser.add_argument(
        "--level",
        "-l",
        choices=["E0", "E1", "E2", "E3", "E4", "E5"],
        default="E2",
        help="Evidence level (default: E2)",
    )
    ev_parser.add_argument(
        "--source",
        "-s",
        choices=["V", "P", "D"],
        default="V",
        help="Source confidence: [V]erified, [P]roposed/secondary, [D]erived (default: V)",
    )
    ev_parser.add_argument("--metric", "-m", default=None, help="Primary metric name (e.g. RMSLE, AUC, loss)")
    ev_parser.add_argument("--delta", "-d", type=float, default=None, help="Delta vs baseline (positive or negative)")
    ev_parser.add_argument("--ci", default=None, help="95% Confidence interval as '[lower, upper]' or 'lower,upper'")
    ev_parser.add_argument(
        "--falsified",
        "--falsification-triggered",
        dest="falsification_triggered",
        action="store_true",
        help="Mark evidence as triggering falsification",
    )
    ev_parser.add_argument(
        "--status",
        choices=["CONFIRMED", "FALSIFIED", "BLOCKED", "IN_PROGRESS", "PROPOSED", "REFINED"],
        default=None,
        help="Explicit status transition override",
    )
    ev_parser.add_argument(
        "--assumptions",
        "-a",
        default=None,
        help="Comma-separated suspect auxiliary assumptions (e.g. 'AUX_SAMPLING,AUX_SEED')",
    )
    ev_parser.add_argument("--commit", default=None, help="Git commit SHA associated with evidence")
    ev_parser.add_argument("--artifact", default=None, help="Path to primary artifact")

    # Scaffold Experiment
    scaffold_parser = subparsers.add_parser(
        "scaffold", help="Generate an automated Python experiment runner template for a hypothesis"
    )
    scaffold_parser.add_argument("hypothesis_id", help="Target hypothesis ID (e.g. H92-T1)")
    scaffold_parser.add_argument("--out", "-o", default=None, help="Output script file path")

    # Verify Gates
    verify_parser = subparsers.add_parser(
        "verify-gates", help="Verify experiment JSON artifact against falsification criteria and G0-G8 gates"
    )
    verify_parser.add_argument("artifact", help="Path to experiment JSON artifact (e.g. artifacts/metrics/h92_t1.json)")
    verify_parser.add_argument("--hypothesis", "-H", default=None, help="Hypothesis ID override")
    verify_parser.add_argument(
        "--apply", action="store_true", help="Automatically log verified EvidenceClaim and update hypothesis status"
    )
    verify_parser.add_argument(
        "--level",
        "-l",
        choices=["E0", "E1", "E2", "E3", "E4", "E5"],
        default="E3",
        help="Evidence level (default: E3)",
    )
    verify_parser.add_argument(
        "--source",
        "-s",
        choices=["V", "P", "D"],
        default="V",
        help="Source confidence: [V]erified, [P]roposed, [D]erived (default: V)",
    )

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
            print(
                f"    Edit {template_path.name} to match your repo notes and run: python {template_path.relative_to(root)}"
            )
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
            print(
                f"[+] Successfully ingested {res.get('hypotheses_ingested', 0)} hypotheses and {res.get('evidence_ingested', 0)} evidence claims."
            )
            print(
                f"[+] Total database state: {res.get('total_hypotheses', 0)} hypotheses, {res.get('total_evidence', 0)} evidence records."
            )

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
            print(
                f"[+] Exported research graph ({bundle['counts']['hypotheses']} hypotheses, {bundle['counts']['evidence']} evidence) to {out_path}"
            )
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
            print(
                f"[DRY RUN] Would import {res['hypotheses_count']} hypotheses and {res['evidence_count']} evidence records."
            )
        else:
            print(
                f"[+] Successfully imported {res.get('hypotheses_ingested', 0)} hypotheses and {res.get('evidence_ingested', 0)} evidence claims."
            )

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
                "REFINED": "🟣",
            }.get(h.status.value, "⚪")
            print(
                f"{status_icon} [{h.id}] {h.title} (Level: {h.current_evidence_level.value}, Status: {h.status.value})"
            )
        print("================================================================\n")

    elif args.command == "version":
        print(f"epires {__version__}")

    elif args.command == "dag":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        statuses = [s.strip() for s in args.status.split(",") if s.strip()] if args.status else None
        print(
            store.export_mermaid_dag(
                frontier_only=args.frontier,
                statuses=statuses,
                root_id=args.root,
                depth=args.depth,
            )
        )

    elif args.command == "summary":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        print(json.dumps(store.get_summary(), indent=2, ensure_ascii=False))

    elif args.command == "compute-gate":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        h = store.get_hypothesis(args.hypothesis_id)
        if not h:
            print(f"[!] Hypothesis '{args.hypothesis_id}' not found in research graph.")
            sys.exit(1)
        from .gates import evaluate_result_gate

        payload = (
            args.results
            if args.results
            else {
                "metric_name": args.metric_name,
                "metric_value": args.metric_value,
                "delta_vs_baseline": args.delta,
                "ci_95_lower": args.ci_lower,
                "ci_95_upper": args.ci_upper,
            }
        )
        res = evaluate_result_gate(hypothesis=h, results=payload)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "multihop":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        results = store.query_2hop_relations(
            head_id=args.head_id,
            relation_1=args.rel1,
            relation_2=args.rel2,
            top_k=args.top_k,
        )
        print(json.dumps(results, indent=2, ensure_ascii=False))

    elif args.command == "compress":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        res = store.compress_trace_context(limit=args.limit)
        print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "audit":
        import os
        from .audit import audit_hypothesis
        from .models import HypothesisStatus

        if args.strict:
            os.environ["EPIRES_STRICT_GATES"] = "1"
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))

        if args.h_id:
            if args.deep:
                from .auditor import independent_audit

                print(f"[*] Running S3* LLM Independent Audit on '{args.h_id}' ...")
                res = independent_audit(args.h_id, store)
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                res = audit_hypothesis(args.h_id, store)
                icon = "🟢" if res["passed"] else "🔴"
                print(f"{icon} Audit for '{args.h_id}': {'PASSED' if res['passed'] else 'FAILED'}")
                if res.get("violations"):
                    print("  Violations:")
                    for v in res["violations"]:
                        print(f"    - {v}")
                if res.get("gates"):
                    print(f"  Gates: {res['gates']}")
        else:
            confirmed = store.list_hypotheses(status=HypothesisStatus.CONFIRMED)
            print(f"\n[*] Auditing all {len(confirmed)} CONFIRMED hypotheses ...")
            passed_cnt = 0
            for h in confirmed:
                res = audit_hypothesis(h.id, store)
                icon = "🟢" if res["passed"] else "🔴"
                print(f"  {icon} [{h.id}] {h.title} (Passed: {res['passed']})")
                if not res["passed"]:
                    for v in res.get("violations", []):
                        print(f"       Violation: {v}")
                else:
                    passed_cnt += 1
            print(f"\n[+] Audit summary: {passed_cnt}/{len(confirmed)} passed.\n")

    elif args.command == "posiwid":
        from .audit import posiwid_report

        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        rep = posiwid_report(store)
        if args.json:
            print(json.dumps(rep, indent=2, ensure_ascii=False))
        else:
            print(f"\n==================== POSIWID INTEGRITY: {config.project_name.upper()} ====================")
            gap = rep.get("integrity_gap", 0.0) * 100.0
            print(f"Integrity Gap:       {gap:.1f}% (violated confirmed / total confirmed)")
            print(f"Confirmed Total:     {rep.get('total_confirmed', 0)}")
            print(f"Violated Confirmed:  {rep.get('violated_confirmed', 0)}")
            print(f"Total Hypotheses:    {rep.get('total_hypotheses', 0)}")
            print("\nStatus Distribution:")
            for st, cnt in sorted(rep.get("status_distribution", {}).items(), key=lambda x: -x[1]):
                print(f"  - {st:<15}: {cnt}")
            print("========================================================================\n")

    elif args.command == "algedonic":
        from .algedonic import check_triggers, freeze_branch

        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        if args.freeze:
            blocked = freeze_branch(args.freeze, store)
            print(f"[!] Algedonic freeze triggered on '{args.freeze}': blocked {len(blocked)} downstream hypotheses.")
            for b in blocked:
                print(f"    - ⚫ {b}")
        else:
            alerts = check_triggers(
                store,
                n_failures_threshold=args.threshold,
                active_only=args.active_only,
                min_evidence_level=args.min_level,
            )
            print(f"\n==================== ALGEDONIC ALERTS: {config.project_name.upper()} ====================")
            if not alerts:
                print("🟢 No active pain triggers. Research graph is operating normally.")
            else:
                for a in alerts:
                    sev = a.get("severity", "medium").upper()
                    print(f"🔴 [{sev}] Trigger: {a.get('trigger')} on Node: {a.get('node_id')}")
            print("========================================================================\n")

    elif args.command == "synthesis":
        from .synthesis import generate_synthesis_report

        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        report_md = generate_synthesis_report(store, project_name=config.project_name)
        if args.out:
            out_file = Path(args.out).resolve()
            out_file.write_text(report_md, encoding="utf-8")
            print(f"[+] Epistemic synthesis report generated and written to {out_file}")
        else:
            print(report_md)

    elif args.command in ("register-hypothesis", "register"):
        from .models import HypothesisNode, HypothesisStatus, EvidenceLevel

        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))

        parents = [p.strip() for p in args.parents.split(",") if p.strip()] if args.parents else []
        h = HypothesisNode(
            id=args.id.strip(),
            title=args.title.strip(),
            a_priori_mechanism=args.mechanism.strip(),
            falsification_criteria=args.criteria.strip(),
            parent_ids=parents,
            status=HypothesisStatus(args.status),
            target_evidence_level=EvidenceLevel(args.target_level),
            domain=args.domain or config.domain,
            primary_metric=args.primary_metric or config.primary_metric,
        )
        saved = store.register_hypothesis(h, allow_status_override=True)
        print(f"[+] Successfully registered hypothesis [{saved.id}]: '{saved.title}'")
        print(
            f"    Status: {saved.status.value} | Target Level: {saved.target_evidence_level.value} | Parents: {saved.parent_ids}"
        )

    elif args.command in ("log-evidence", "evidence"):
        from .models import EvidenceClaim, EvidenceLevel, SourceConfidence, HypothesisStatus

        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))

        target_h = store.get_hypothesis(args.hypothesis.strip())
        if not target_h:
            print(f"[!] Error: Hypothesis '{args.hypothesis}' does not exist in research graph.")
            sys.exit(1)

        # Parse CI bounds
        lower_ci: float | None = None
        upper_ci: float | None = None
        if args.ci:
            import re

            cleaned = args.ci.strip("[](){}\"'\t ")
            parts = re.split(r"[,;\s]+", cleaned)
            nums = []
            for p in parts:
                if p:
                    try:
                        nums.append(float(p))
                    except ValueError:
                        pass
            if len(nums) >= 2:
                lower_ci, upper_ci = nums[0], nums[1]
            elif len(nums) == 1:
                lower_ci = nums[0]

        assumptions = [a.strip() for a in args.assumptions.split(",") if a.strip()] if args.assumptions else []

        ev = EvidenceClaim(
            hypothesis_id=args.hypothesis.strip(),
            evidence_level=EvidenceLevel(args.level),
            source_confidence=SourceConfidence(args.source),
            claim=args.claim.strip(),
            metric_name=args.metric or config.primary_metric,
            delta_vs_baseline=args.delta,
            ci_95_lower=lower_ci,
            ci_95_upper=upper_ci,
            falsification_triggered=args.falsification_triggered or (args.status == "FALSIFIED"),
            assumption_ids=assumptions,
            commit_hash=args.commit,
            citation_or_path=args.artifact or "",
        )

        ev, blocked_children = store.log_evidence(ev)
        if args.status:
            target_h.status = HypothesisStatus(args.status)
            store.register_hypothesis(target_h, allow_status_override=True, emit_trace=False)

        updated_h = store.get_hypothesis(args.hypothesis.strip())
        status_icon = (
            "🟢"
            if updated_h.status == HypothesisStatus.CONFIRMED
            else "🔴"
            if updated_h.status == HypothesisStatus.FALSIFIED
            else "⚫"
            if updated_h.status == HypothesisStatus.BLOCKED
            else "🟡"
        )
        print(f"[+] Evidence logged for [{updated_h.id}] (Claim ID: {ev.id}):")
        print(f"    Claim:  {ev.claim}")
        print(f"    Status: {status_icon} {updated_h.status.value} (Level: {updated_h.current_evidence_level.value})")
        if ev.delta_vs_baseline is not None:
            ci_str = f" [95% CI: {ev.ci_95_lower}, {ev.ci_95_upper}]" if ev.ci_95_lower is not None else ""
            print(f"    Delta:  {ev.delta_vs_baseline:+g} on {ev.metric_name}{ci_str}")
        if blocked_children:
            print(
                f"    [!] Cascaded invalidation: BLOCKED {len(blocked_children)} child hypotheses: {blocked_children}"
            )

    elif args.command == "scaffold":
        import re
        from .scaffold import generate_experiment_scaffold

        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))

        h = store.get_hypothesis(args.hypothesis_id.strip())
        title = h.title if h else "Experiment"
        mech = h.a_priori_mechanism if h else "Theoretical basis"
        crit = h.falsification_criteria if h else "delta < 0"

        code = generate_experiment_scaffold(
            hypothesis_id=args.hypothesis_id.strip(),
            title=title,
            mechanism=mech,
            falsification_criteria=crit,
            primary_metric=config.primary_metric,
        )

        hid_clean = re.sub(r"[^a-zA-Z0-9_]", "_", args.hypothesis_id.lower())
        out_file = Path(args.out).resolve() if args.out else (root / "scripts" / f"eval_{hid_clean}.py")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(code, encoding="utf-8")
        try:
            out_file.chmod(0o755)
        except Exception:
            pass
        rel_str = out_file.relative_to(root) if out_file.is_relative_to(root) else out_file
        print(f"[+] Generated experiment scaffold: {rel_str}")
        print(f"    Run via: python {rel_str} --help")

    elif args.command == "verify-gates":
        from .verifier import verify_experiment_artifact

        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))

        res = verify_experiment_artifact(
            artifact_path=args.artifact,
            store=store,
            hypothesis_id=args.hypothesis,
            apply=args.apply,
            evidence_level=args.level,
            source_confidence=args.source,
        )

        icon = "🟢" if res["passed_all_gates"] else "🔴" if res["falsification_triggered"] else "🟡"
        print(f"\n==================== GATE VERIFICATION: {res['hypothesis_id']} ====================")
        print(f"Artifact: {res['artifact_file']}")
        print(f"Verdict:  {icon} {res['verdict_status']} (Passed all gates: {res['passed_all_gates']})")
        if res.get("falsification_reason"):
            print(f"Refutation: {res['falsification_reason']}")
        print(f"Gates:    {res['gates']}")
        print(f"Metrics:  {res['metrics']}")
        if res.get("applied"):
            print(f"[+] Successfully logged EvidenceClaim [{res['evidence_id']}] to research hypergraph.")
            if res.get("blocked_children"):
                print(f"    Cascaded invalidation: BLOCKED {len(res['blocked_children'])} child hypotheses.")
        else:
            print("Run with --apply to commit evidence and update status in database.")
        print("========================================================================\n")

    else:
        parser.print_help()
