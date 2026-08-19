"""CLI entrypoint for Epires: Minimalist Cybernetic AI-Research Operating System."""

from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import uvicorn

from epires_core.config import (
    EpiresProjectConfig,
    ProjectPaths,
    detect_project_profile,
    find_project_root,
)
from epires_core.store import EpiresStore
from server.app import create_app
from server.mcp_server import create_mcp_server


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

    # Generate MCP configuration for IDEs
    mcp_config = {
        "mcpServers": {
            "epires": {
                "command": "uv",
                "args": ["run", "python", "-m", "server.mcp_server"],
                "cwd": str(root)
            }
        }
    }
    mcp_json_path = epires_dir / "mcp_config.json"
    mcp_json_path.write_text(json.dumps(mcp_config, indent=2), encoding="utf-8")
    print(f"[+] Generated IDE MCP config: {mcp_json_path.relative_to(root)}")

    # Initialize empty DB if not present
    db_file = root / config.paths.db_path
    store = EpiresStore(db_path=db_file)
    print(f"[+] Verified local VSA Hypergraph database: {config.paths.db_path}")

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


def main():
    parser = argparse.ArgumentParser(
        prog="epires",
        description="Epires: Minimalist Cybernetic AI-Research Operating System"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Init
    init_parser = subparsers.add_parser("init", help="Initialize Epires in the current project")
    init_parser.add_argument("--dir", default=".", help="Project directory (default: current directory)")
    init_parser.add_argument("--force", action="store_true", help="Force overwrite config")

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

    args = parser.parse_args()

    if args.command == "init":
        init_workspace(target_dir=args.dir, force=args.force)

    elif args.command == "recon":
        profile = detect_project_profile(args.dir)
        print(json.dumps(profile, indent=2, ensure_ascii=False))

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
                "PROPOSED": "🔵"
            }.get(h.status.value, "⚪")
            print(f"{status_icon} [{h.id}] {h.title} (Level: {h.current_evidence_level.value}, Status: {h.status.value})")
        print("================================================================\n")

    elif args.command == "dag":
        root = find_project_root()
        config = EpiresProjectConfig.load(root)
        store = EpiresStore(db_path=str(root / config.paths.db_path))
        print(store.export_mermaid_dag())

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
