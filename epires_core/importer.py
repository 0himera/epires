"""Ingestion, Parsing, and Graph Serialization Engine for Epires."""

from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .models import (
    Entity,
    EvidenceClaim,
    EvidenceLevel,
    ExperimentNode,
    HypothesisNode,
    HypothesisStatus,
    RelationEdge,
    RelationType,
    SourceConfidence,
    TraceEntry,
)
from .store import EpiresStore


def parse_markdown_findings(content: str) -> Tuple[List[HypothesisNode], List[EvidenceClaim]]:
    """Smart heuristic parser for Markdown experiment/hypothesis documents.

    Supports various formats:
    - Headings with H-tags: `# H1: ...`, `## H-001 - Title`, `### [CONFIRMED] H2: Title`
    - Bullet points with Mechanism, Falsification Criteria, Metrics, Evidence.
    """
    hypotheses: List[HypothesisNode] = []
    evidence_list: List[EvidenceClaim] = []

    # Regex to identify hypothesis headings:
    # e.g., "## H1: Baseline model", "### [CONFIRMED] H-02: Haar Wavelets", "## Hypothesis 3 - VSA Memory"
    h_pattern = re.compile(
        r"^(?:#{1,4})\s+(?:\[(?P<status_tag>PROPOSED|CONFIRMED|FALSIFIED|BLOCKED|IN_PROGRESS|REFINED)\]\s+)?(?:(?:Hypothesis|Гипотеза)\s+(?P<id_hypo>[A-Za-z0-9_\-\.]+)|(?P<id_h>H[-_]?[A-Za-z0-9_\-\.]+))(?:\s*[:\-–—]\s*|\s+)(?P<title>.+)$",
        re.MULTILINE | re.IGNORECASE
    )

    matches = list(h_pattern.finditer(content))
    if not matches:
        # Fallback: check for numbered list items like "1. H1: ...", "- H1: ..."
        alt_pattern = re.compile(
            r"^(?:[\*\-\+]|\d+\.)\s+(?:\[(?P<status_tag>PROPOSED|CONFIRMED|FALSIFIED|BLOCKED|IN_PROGRESS|REFINED)\]\s+)?(?:(?:Hypothesis|Гипотеза)\s+(?P<id_hypo>[A-Za-z0-9_\-\.]+)|(?P<id_h>H[-_]?[A-Za-z0-9_\-\.]+))(?:\s*[:\-–—]\s*|\s+)(?P<title>.+)$",
            re.MULTILINE | re.IGNORECASE
        )
        matches = list(alt_pattern.finditer(content))

    for i, match in enumerate(matches):
        raw_id = (match.group("id_hypo") or match.group("id_h") or f"H-{i+1}").strip()
        h_id = raw_id if raw_id.upper().startswith("H") else f"H-{raw_id}"
        title = match.group("title").strip()
        raw_status = match.group("status_tag")

        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start_pos:end_pos].strip()
        clean_body = re.sub(r"\*\*|\*|__|_", "", body)

        # Parse a priori mechanism
        mechanism_match = re.search(
            r"(?:a\s+priori|mechanism|theoretical\s+basis|rationale|theory)\s*[:\-–—]\s*(.+)",
            clean_body, re.IGNORECASE
        )
        mechanism = mechanism_match.group(1).strip() if mechanism_match else "Extracted from research documentation."

        # Parse falsification criteria
        falsification_match = re.search(
            r"(?:falsification|falsify|falsification\s+criteria|refutation\s+criteria|threshold)\s*[:\-–—]\s*(.+)",
            clean_body, re.IGNORECASE
        )
        falsification = falsification_match.group(1).strip() if falsification_match else "Empirical validation failure or delta >= 0.0"

        # Parse target / current evidence levels
        level_match = re.search(r"(?:target\s+level|level|evidence\s+level)\s*[:\-–—]\s*(E[0-5])", clean_body, re.IGNORECASE)
        target_level = EvidenceLevel(level_match.group(1).upper()) if level_match else EvidenceLevel.E3

        # Parse parent dependencies (depends_on / parents)
        parents: List[str] = []
        parents_match = re.search(r"(?:depends\s+on|parents|dependencies|base)\s*[:\-–—]\s*(.+)", clean_body, re.IGNORECASE)
        if parents_match:
            raw_parents = parents_match.group(1).strip()
            parents = [p.strip() for p in re.findall(r"[A-Za-z0-9_\-\.]+", raw_parents) if p.strip()]

        # Parse tags and entities
        tags: List[str] = []
        tags_match = re.search(r"(?:tags|keywords|labels)\s*[:\-–—]\s*(.+)", clean_body, re.IGNORECASE)
        if tags_match:
            tags = [t.strip().lower() for t in re.split(r"[,;|\s]+", tags_match.group(1)) if t.strip()]

        entities: List[Entity] = []
        models_match = re.search(r"(?:model|architecture)\s*[:\-–—]\s*(.+)", clean_body, re.IGNORECASE)
        if models_match:
            entities.append(Entity(type="Model", value=models_match.group(1).strip()))
        features_match = re.search(r"(?:feature|representation)\s*[:\-–—]\s*(.+)", clean_body, re.IGNORECASE)
        if features_match:
            entities.append(Entity(type="Feature", value=features_match.group(1).strip()))

        # Determine initial status
        status = HypothesisStatus.PROPOSED
        if raw_status:
            try:
                status = HypothesisStatus(raw_status.upper())
            except ValueError:
                pass
        elif re.search(r"\b(?:falsified|refuted|failed)\b", clean_body, re.IGNORECASE):
            status = HypothesisStatus.FALSIFIED
        elif re.search(r"\b(?:confirmed|validated|passed|accepted)\b", clean_body, re.IGNORECASE):
            status = HypothesisStatus.CONFIRMED
        elif re.search(r"\b(?:in\s+progress|testing|running)\b", clean_body, re.IGNORECASE):
            status = HypothesisStatus.IN_PROGRESS

        h_node = HypothesisNode(
            id=h_id,
            title=title,
            a_priori_mechanism=mechanism,
            falsification_criteria=falsification,
            target_evidence_level=target_level,
            current_evidence_level=EvidenceLevel.E0,
            status=status,
            parent_ids=parents,
            entities=entities,
            tags=tags,
        )
        hypotheses.append(h_node)

        # Parse any associated evidence claims mentioned in body
        evidence_matches = re.finditer(
            r"(?:evidence|result|observation|metric)\s*[:\-–—]\s*(?P<claim>[^\n]+)",
            clean_body, re.IGNORECASE
        )
        for ev_idx, ev_m in enumerate(evidence_matches):
            claim_text = ev_m.group("claim").strip()
            # Extract metric number if present
            metric_val_m = re.search(r"(?:=\s*|:\s*)([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", claim_text)
            metric_val = float(metric_val_m.group(1)) if metric_val_m else None
            
            is_falsified = status == HypothesisStatus.FALSIFIED or bool(re.search(r"fail|falsif", claim_text, re.IGNORECASE))
            ev_claim = EvidenceClaim(
                id=f"ev_{h_id}_{ev_idx + 1}",
                hypothesis_id=h_id,
                evidence_level=target_level if status != HypothesisStatus.PROPOSED else EvidenceLevel.E1,
                source_confidence=SourceConfidence.V,
                claim=claim_text,
                metric_name="metric" if metric_val is not None else None,
                metric_value=metric_val,
                falsification_triggered=is_falsified,
                citation_or_path="",
            )
            evidence_list.append(ev_claim)

    return hypotheses, evidence_list


def export_graph_bundle(store: EpiresStore, project_name: str = "epires") -> Dict[str, Any]:
    """Export complete research memory graph to a portable, versioned bundle with checksum."""
    hypotheses = [h.model_dump() for h in store.list_hypotheses()]
    evidence = [e.model_dump() for e in store.list_evidence()]
    relations = [
        {
            "source_id": r.source_id,
            "target_id": r.target_id,
            "relation_type": r.relation_type.value,
            "metadata": r.metadata
        }
        for r in store.list_relations()
    ]
    traces = [t.model_dump() for t in store.list_traces(limit=10000)]
    experiments = [exp.model_dump() for exp in store.list_experiments()]

    core_payload = {
        "schema_version": "epires.v1",
        "project_name": project_name,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "hypotheses": len(hypotheses),
            "evidence": len(evidence),
            "relations": len(relations),
            "traces": len(traces),
            "experiments": len(experiments),
        },
        "hypotheses": hypotheses,
        "evidence": evidence,
        "relations": relations,
        "experiments": experiments,
        "traces": traces,
    }

    # Generate deterministic SHA256 checksum over content
    content_str = json.dumps({k: core_payload[k] for k in ["hypotheses", "evidence", "relations"]}, sort_keys=True)
    checksum = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
    core_payload["checksum_sha256"] = checksum

    return core_payload


def import_graph_bundle(
    store: EpiresStore,
    bundle: Dict[str, Any],
    upsert: bool = True,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Import a versioned bundle into Epires SQLite store."""
    if bundle.get("schema_version") not in {"epires.v1", "atlas.v1"}:
        raise ValueError(f"Unsupported bundle schema version: {bundle.get('schema_version')}")

    raw_hypotheses = bundle.get("hypotheses", [])
    raw_evidence = bundle.get("evidence", [])

    hypotheses: List[HypothesisNode] = []
    for raw in raw_hypotheses:
        if isinstance(raw, dict):
            # Parse entities properly
            entities = [
                Entity(**e) if isinstance(e, dict) else e
                for e in raw.get("entities", [])
            ]
            raw_copy = dict(raw)
            raw_copy["entities"] = entities
            hypotheses.append(HypothesisNode(**raw_copy))

    evidence: List[EvidenceClaim] = []
    for raw in raw_evidence:
        if isinstance(raw, dict):
            evidence.append(EvidenceClaim(**raw))

    if dry_run:
        return {
            "dry_run": True,
            "hypotheses_count": len(hypotheses),
            "evidence_count": len(evidence),
            "hypotheses_ids": [h.id for h in hypotheses],
        }

    return store.bulk_import(
        hypotheses=hypotheses,
        evidence=evidence,
        upsert=upsert,
        emit_summary_trace=True
    )


def ingest_file(
    store: EpiresStore,
    file_path: Union[str, Path],
    dry_run: bool = False,
    upsert: bool = True
) -> Dict[str, Any]:
    """Universal ingestion entrypoint for .md, .json, and .jsonl files."""
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    content = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()

    if ext == ".json":
        data = json.loads(content)
        if isinstance(data, dict) and "schema_version" in data:
            return import_graph_bundle(store, data, upsert=upsert, dry_run=dry_run)
        elif isinstance(data, list):
            # Array of hypotheses
            hypotheses = [HypothesisNode(**item) for item in data]
            if dry_run:
                return {"dry_run": True, "hypotheses_count": len(hypotheses), "evidence_count": 0}
            return store.bulk_import(hypotheses=hypotheses, evidence=[], upsert=upsert)
        else:
            raise ValueError("Unrecognized JSON structure for graph ingestion.")

    elif ext == ".jsonl":
        hypotheses = []
        evidence = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if "a_priori_mechanism" in item or "falsification_criteria" in item:
                hypotheses.append(HypothesisNode(**item))
            elif "claim" in item and "hypothesis_id" in item:
                evidence.append(EvidenceClaim(**item))

        if dry_run:
            return {"dry_run": True, "hypotheses_count": len(hypotheses), "evidence_count": len(evidence)}
        return store.bulk_import(hypotheses=hypotheses, evidence=evidence, upsert=upsert)

    else:
        # Markdown / text
        hypotheses, evidence = parse_markdown_findings(content)
        if dry_run:
            return {
                "dry_run": True,
                "hypotheses_count": len(hypotheses),
                "evidence_count": len(evidence),
                "hypotheses": [{"id": h.id, "title": h.title, "status": h.status.value} for h in hypotheses]
            }
        return store.bulk_import(hypotheses=hypotheses, evidence=evidence, upsert=upsert)
