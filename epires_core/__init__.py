"""Epires Core Engine: VSA Hypergraph, Hypothesis Falsification DAG, and Automated Tracing."""

from .config import (
    EpiresProjectConfig,
    ProjectPaths,
    find_project_root,
    detect_project_profile,
)
from .setup import (
    setup_cursor,
    setup_claude_code,
    setup_opencode,
    setup_codex,
    setup_antigravity,
    setup_all,
)
from .vsa import BipolarVSA
from .models import (
    EvidenceLevel,
    SourceConfidence,
    HypothesisStatus,
    RelationType,
    HypothesisNode,
    ExperimentNode,
    EvidenceClaim,
    RelationEdge,
    TraceEntry,
    GapQuery,
    SearchQuery,
)
from .hypergraph import HypergraphEncoder
from .store import EpiresStore
from .tracer import AutoTracer

__all__ = [
    "EpiresProjectConfig",
    "ProjectPaths",
    "find_project_root",
    "detect_project_profile",
    "setup_cursor",
    "setup_claude_code",
    "setup_opencode",
    "setup_codex",
    "setup_antigravity",
    "setup_all",
    "BipolarVSA",
    "EvidenceLevel",
    "SourceConfidence",
    "HypothesisStatus",
    "RelationType",
    "HypothesisNode",
    "ExperimentNode",
    "EvidenceClaim",
    "RelationEdge",
    "TraceEntry",
    "GapQuery",
    "SearchQuery",
    "HypergraphEncoder",
    "EpiresStore",
    "AutoTracer",
    "__version__",
]

__version__ = "0.3.3.1"
