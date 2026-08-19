"""CLI entrypoint for Epires Research Engine."""

import argparse
import asyncio
import sys
import uvicorn

from epires_core.store import EpiresStore
from server.app import create_app
from server.mcp_server import create_mcp_server


def main():
    parser = argparse.ArgumentParser(
        prog="epires",
        description="Epires: Minimalist Cybernetic AI-Research Operating System"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

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

    if args.command == "serve":
        app = create_app()
        print(f"[*] Starting Epires FastAPI server on {args.host}:{args.port} ...")
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "mcp":
        mcp = create_mcp_server()
        asyncio.run(mcp.run_stdio_async())

    elif args.command == "status":
        store = EpiresStore()
        hypotheses = store.list_hypotheses()
        print(f"\n==================== EPIRES RESEARCH STATUS ====================")
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
        store = EpiresStore()
        print(store.export_mermaid_dag())

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
