"""Epires Core Engine: VSA Hypergraph, Hypothesis Falsification DAG, and Automated Tracing."""

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
]
