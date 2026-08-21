"""Pydantic data models for hypotheses, experiments, evidence, DAG relations and traces."""

from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceLevel(str, Enum):
    E0 = "E0"  # Speculative / Theoretical Hypothesis
    E1 = "E1"  # Mechanism Implemented
    E2 = "E2"  # Descriptive / Smoke / Local Replay Pass
    E3 = "E3"  # Targeted Evaluation / Holdout Pass
    E4 = "E4"  # Repeated Out-of-Time / Cross-Validation with Bootstrap CI
    E5 = "E5"  # Final Hidden-Test / Production Grade


class SourceConfidence(str, Enum):
    V = "V"  # Primary source read directly / verified artifact
    P = "P"  # Secondary source / reported externally
    D = "D"  # Inferred / derived from adjacent work


class HypothesisStatus(str, Enum):
    PROPOSED = "PROPOSED"  # Registered E0
    IN_PROGRESS = "IN_PROGRESS"  # Currently being tested E1-E3
    CONFIRMED = "CONFIRMED"  # Successfully verified at target level
    FALSIFIED = "FALSIFIED"  # Popperian falsification criteria met
    BLOCKED = "BLOCKED"  # Invalidation cascaded from parent hypothesis failure
    REFINED = "REFINED"  # Superseded by a more precise hypothesis


class RelationType(str, Enum):
    DEPENDS_ON = "DEPENDS_ON"  # Child hypothesis requires parent premise
    SUPERSEDES = "SUPERSEDES"  # New hypothesis replaces/improves upon older hypothesis
    CONFLICTS_WITH = "CONFLICTS_WITH"  # Mutually exclusive hypotheses / competing paradigms
    REFINES = "REFINES"  # Hypothesis provides higher precision / parameter specialization
    BLOCKS = "BLOCKS"  # Negative result prevents downstream work
    FALSIFIES = "FALSIFIES"  # Experiment or finding refutes hypothesis
    PRODUCES = "PRODUCES"  # Experiment produces evidence or artifact
    GATED_BY = "GATED_BY"  # Hypothesis requires passing a specific statistical gate


class Entity(BaseModel):
    type: str  # e.g., "Model", "Feature", "Metric", "Regime", "Dataset"
    value: str  # e.g., "CatBoost", "HaarWavelet", "RMSLE", "CrashRegime"

    def to_key(self) -> str:
        return f"{self.type}:{self.value}"


class RelationEdge(BaseModel):
    source_id: str
    target_id: str
    relation_type: RelationType
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceClaim(BaseModel):
    id: str
    hypothesis_id: str
    evidence_level: EvidenceLevel
    source_confidence: SourceConfidence = SourceConfidence.V
    claim: str
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    delta_vs_baseline: Optional[float] = None
    ci_95_lower: Optional[float] = None
    ci_95_upper: Optional[float] = None
    falsification_triggered: bool = False
    citation_or_path: str = ""
    artifact_hash: Optional[str] = None
    timestamp: str = ""
    observer_id: str = ""
    criteria_version: str = "v1"
    stated_p: float | None = None
    assumption_ids: list[str] = Field(default_factory=list)
    prediction: str | None = None


class HypothesisNode(BaseModel):
    id: str  # e.g. "H14" or "H53a"
    title: str
    a_priori_mechanism: str
    falsification_criteria: str
    target_evidence_level: EvidenceLevel = EvidenceLevel.E3
    current_evidence_level: EvidenceLevel = EvidenceLevel.E0
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    parent_ids: List[str] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    criteria_version: str = "v1"
    observation_context: str = ""
    created_at: str = ""
    updated_at: str = ""


class ExperimentNode(BaseModel):
    id: str
    hypothesis_id: str
    name: str
    script_path: str
    commit_hash: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, float] = Field(default_factory=dict)
    evidence_ids: List[str] = Field(default_factory=list)
    artifact_paths: List[str] = Field(default_factory=list)
    created_at: str = ""


class TraceEntry(BaseModel):
    id: Optional[int] = None
    timestamp: str
    action: str  # e.g. "REGISTER_HYPOTHESIS", "RUN_EXPERIMENT", "FALSIFY", "DELEGATE"
    agent_role: str = "Lead-PI"  # "Lead-PI", "Coder-Subagent", "Reviewer"
    h_tag: Optional[str] = None
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)


class GapQuery(BaseModel):
    dimensions: List[str] = Field(..., description="Entity types to check combinations for (e.g. ['Model', 'Feature'])")
    min_tested: int = Field(default=1, description="Threshold for unstudied or under-studied combinations")


class SearchQuery(BaseModel):
    query: Optional[str] = None
    entities: Optional[List[Entity]] = None
    status: Optional[HypothesisStatus] = None
    limit: int = 10
