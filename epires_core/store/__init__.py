"""Epires Embedded Storage & VSA Hypergraph Engine with Cascading Falsification DAG."""

from __future__ import annotations

from ..models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    ExperimentNode,
    GapQuery,
    HypothesisNode,
    HypothesisStatus,
    RelationEdge,
    RelationType,
    SearchQuery,
    SourceConfidence,
    TraceEntry,
)
from .base import StoreBase
from .dag import DAGMixin
from .evidence import EvidenceMixin
from .experiments import ExperimentMixin
from .hypotheses import HypothesisMixin
from .search import SearchMixin
from .traces import TraceMixin
from .visualizer import VisualizerMixin


class EpiresStore(
    StoreBase,
    DAGMixin,
    HypothesisMixin,
    EvidenceMixin,
    ExperimentMixin,
    SearchMixin,
    TraceMixin,
    VisualizerMixin,
):
    """Complete modular SQLite + VSA Hypergraph research store with cascading falsification DAG."""

    pass


__all__ = [
    "EpiresStore",
    "StoreBase",
    "Entity",
    "EvidenceClaim",
    "EvidenceLevel",
    "ExperimentNode",
    "GapQuery",
    "HypothesisNode",
    "HypothesisStatus",
    "RelationEdge",
    "RelationType",
    "SearchQuery",
    "SourceConfidence",
    "TraceEntry",
]
