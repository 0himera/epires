"""Dynamic and Antifragile Configuration Management for Epires Research Projects."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProjectPaths(BaseModel):
    db_path: str = ".epires/hypotheses.db"
    trace_path: str = "docs/agent-trace.md"
    artifacts_dir: str = "artifacts"
    source_roots: List[str] = Field(default_factory=lambda: ["src", "scripts"])
    custom_doc_paths: List[str] = Field(default_factory=list)


class EpiresProjectConfig(BaseModel):
    project_name: str = "epires_research"
    domain: str = "General Scientific & Quantitative Research"
    task_description: str = "Empirical research, hypothesis testing, and policy optimization"
    primary_metric: str = "Score"
    metric_goal: str = "maximize"  # "maximize" or "minimize"
    promotion_gate: Optional[float] = None
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    lead_pi_protocol_file: str = "AGENTS.md"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, project_dir: str | Path = ".") -> EpiresProjectConfig:
        """Loads .epires/config.json from project root or returns default configuration."""
        root = find_project_root(project_dir)
        config_path = root / ".epires" / "config.json"
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                return cls(**data)
            except Exception:
                pass
        return cls()

    def save(self, project_dir: str | Path = ".") -> Path:
        """Saves configuration to .epires/config.json."""
        root = Path(project_dir).resolve()
        epires_dir = root / ".epires"
        epires_dir.mkdir(parents=True, exist_ok=True)
        config_path = epires_dir / "config.json"
        config_path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return config_path


def find_project_root(start_dir: str | Path = ".") -> Path:
    """Searches upward for .epires directory, .git directory, or pyproject.toml."""
    curr = Path(start_dir).resolve()
    for parent in [curr, *curr.parents]:
        if (parent / ".epires").exists() or (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return curr


def detect_project_profile(project_dir: str | Path = ".") -> Dict[str, Any]:
    """Inspects a directory to dynamically infer domain, stack, existing docs, and emptiness."""
    root = Path(project_dir).resolve()

    # Exclude system/internal files when checking for user codebase presence
    ignore_parts = {".git", ".venv", "__pycache__", ".epires", ".pytest_cache"}

    user_files = [
        f for f in root.glob("**/*")
        if f.is_file()
        and not any(p in f.parts for p in ignore_parts)
        and f.name not in {".gitignore", "agent-trace.md"}
    ]

    if not user_files:
        return {
            "is_empty": True,
            "project_name": root.name,
            "detected_domain": "New Research Project",
            "detected_stack": "Clean Workspace",
            "candidate_doc_files": [],
            "candidate_trace_files": [],
            "suggested_metric": "Primary Metric (e.g. Accuracy / Loss / Sharpe / RMSLE)"
        }

    # Detect stack
    stack = []
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        stack.append("Python")
    if (root / "Cargo.toml").exists():
        stack.append("Rust")
    if (root / "package.json").exists():
        stack.append("TypeScript/JS")

    # Detect existing docs & candidate hypotheses
    candidate_docs = []
    candidate_traces = []
    domain_hints = []

    for f in user_files:
        rel_path = str(f.relative_to(root))
        lower_name = f.name.lower()
        if lower_name.endswith(".md") or lower_name.endswith(".txt"):
            candidate_docs.append(rel_path)
            if "trace" in lower_name or "log" in lower_name:
                candidate_traces.append(rel_path)

            # Read snippet for domain classification
            try:
                content_snippet = f.read_text(encoding="utf-8", errors="ignore")[:3000].lower()
                if any(w in content_snippet for w in ["trading", "perp", "orderbook", "order flow", "funding rate", "microstructure", "sharpe", "avellaneda"]):
                    domain_hints.append("Quantitative Trading / Market Microstructure")
                elif any(w in content_snippet for w in ["gmv", "forecasting", "time-series", "rmsle", "tweedie", "catboost", "lightgbm", "tabular"]):
                    domain_hints.append("Temporal Forecasting / Tabular ML")
                elif any(w in content_snippet for w in ["reinforcement learning", "marl", "self-play", "posg", "multi-agent", "ppo", "q-learning", "game theory"]):
                    domain_hints.append("Multi-Agent Reinforcement Learning / Game Theory")
                elif any(w in content_snippet for w in ["physics", "quantum", "material", "molecular", "pde", "hamiltonian"]):
                    domain_hints.append("Computational Physics & Materials")
            except Exception:
                pass

    if domain_hints:
        detected_domain = max(set(domain_hints), key=domain_hints.count)
    else:
        detected_domain = "General Scientific & Quantitative Research"

    suggested_metric = (
        "RMSLE" if "Forecasting" in detected_domain
        else ("Sharpe Ratio" if "Trading" in detected_domain
        else ("Reward / WinRate" if "Reinforcement" in detected_domain else "Objective Score"))
    )

    return {
        "is_empty": False,
        "project_name": root.name,
        "detected_domain": detected_domain,
        "detected_stack": " / ".join(stack) or "Custom",
        "candidate_doc_files": candidate_docs[:10],
        "candidate_trace_files": candidate_traces[:5],
        "suggested_metric": suggested_metric
    }
