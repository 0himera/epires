"""Canonical Schemas and Ingestion Script Generator for Epires."""

from __future__ import annotations
from typing import Any, Dict


def get_canonical_schema() -> Dict[str, Any]:
    """Returns the strict, canonical data schema and enumeration values for Epires."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Epires Canonical Research Graph Schema",
        "version": "1.0.0",
        "enums": {
            "EvidenceLevel": ["E0", "E1", "E2", "E3", "E4", "E5"],
            "HypothesisStatus": ["PROPOSED", "IN_PROGRESS", "CONFIRMED", "FALSIFIED", "BLOCKED", "REFINED"],
            "SourceConfidence": ["V", "P", "D"],
            "RelationType": [
                "DEPENDS_ON",
                "REPLICATES",
                "SUPERSEDES",
                "CONFLICTS_WITH",
                "REFINES",
                "BLOCKS",
                "FALSIFIES",
                "PRODUCES",
                "GATED_BY",
            ],
        },
        "hypothesis_format": {
            "id": "H1 (string, required, unique node identifier)",
            "title": "Short descriptive title (string, required)",
            "a_priori_mechanism": "Theoretical/mathematical justification before empirics (string, required)",
            "falsification_criteria": "Strict numerical threshold or condition for refutation (string, required)",
            "target_evidence_level": "E3 (enum: E0..E5, default: E3)",
            "current_evidence_level": "E0 (enum: E0..E5, default: E0)",
            "status": "PROPOSED (enum: PROPOSED, IN_PROGRESS, CONFIRMED, FALSIFIED, BLOCKED, REFINED)",
            "parent_ids": ["H0 (list of parent hypothesis IDs)"],
            "entities": [{"type": "Model", "value": "CatBoost"}, {"type": "Feature", "value": "HaarWavelets"}],
            "tags": ["wavelets", "tabular", "gbm"],
        },
        "evidence_format": {
            "id": "ev_H1_1 (string, unique evidence ID)",
            "hypothesis_id": "H1 (string, target hypothesis ID)",
            "evidence_level": "E3 (enum: E0..E5)",
            "source_confidence": "V (enum: V=Verified artifact, P=Reported paper, D=Derived)",
            "claim": "RMSLE = 0.38 achieved on fold 2 validation (string, required)",
            "metric_name": "RMSLE (string, optional)",
            "metric_value": 0.38,
            "delta_vs_baseline": -0.05,
            "falsification_triggered": False,
            "citation_or_path": "artifacts/metrics/run1.json",
        },
        "python_quickstart": """
from epires_core import EpiresStore, HypothesisNode, EvidenceClaim, EvidenceLevel, HypothesisStatus, SourceConfidence

store = EpiresStore()

# Bulk Ingestion
hypotheses = [
    HypothesisNode(
        id="H1",
        title="Haar Wavelet Decomposition",
        a_priori_mechanism="Multiresolution filter separates high-frequency noise",
        falsification_criteria="RMSLE > 0.45",
        target_evidence_level=EvidenceLevel.E3,
        status=HypothesisStatus.CONFIRMED,
        parent_ids=[]
    )
]

evidence = [
    EvidenceClaim(
        id="ev_H1_1",
        hypothesis_id="H1",
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        claim="Validation RMSLE = 0.38",
        metric_name="RMSLE",
        metric_value=0.38
    )
]

store.bulk_import(hypotheses=hypotheses, evidence=evidence, upsert=True)
""",
    }


def generate_migration_script_template(source_file: str = "docs/findings-and-hypotheses.md") -> str:
    """Generates an editable, clean Python script template for custom repo migrations."""
    return f"""#!/usr/bin/env python3
\"\"\"Custom migration script for onboarding historical research findings into Epires.

Usage:
    python scripts/migrate_findings.py
\"\"\"

import re
from pathlib import Path
from epires_core import (
    EpiresStore,
    HypothesisNode,
    EvidenceClaim,
    EvidenceLevel,
    HypothesisStatus,
    SourceConfidence,
    Entity
)

SOURCE_PATH = Path("{source_file}")

def main():
    store = EpiresStore()
    
    if not SOURCE_PATH.exists():
        print(f"[!] Source file not found: {{SOURCE_PATH}}")
        print("    Please adjust SOURCE_PATH in this script to point to your notes file.")
        return

    content = SOURCE_PATH.read_text(encoding="utf-8")
    print(f"[*] Parsing {{SOURCE_PATH}} ({{len(content)}} characters) ...")

    hypotheses = []
    evidence = []

    # -------------------------------------------------------------------------
    # Custom Parser Logic (Customize this block for your specific notes format)
    # -------------------------------------------------------------------------
    # Example: Scanning for bullet lines like:
    # - **H1 — Title [E1, V]**: Mechanism description. Falsification: Criteria...
    pattern = re.compile(
        r"^[\\*\\-\\+]\\s+\\*\\*(?P<tag>[A-Za-z0-9_\\-\\.]+)(?P<label>[^\\*:]*)\\*\\*\\s*[:\\-–—]\\s*(?P<body>.+)$",
        re.MULTILINE
    )

    for idx, match in enumerate(pattern.finditer(content)):
        tag = match.group("tag").strip()
        label = match.group("label").strip()
        body = match.group("body").strip()

        # Determine level & status
        is_rejected = bool(re.search(r"REJECT|FALSIF|FAIL|NEGATIVE", label + body, re.IGNORECASE))
        is_confirmed = bool(re.search(r"PROMOT|PASS|CONFIRM|VALIDAT", label + body, re.IGNORECASE))
        
        status = HypothesisStatus.PROPOSED
        if is_rejected:
            status = HypothesisStatus.FALSIFIED
        elif is_confirmed:
            status = HypothesisStatus.CONFIRMED

        h_node = HypothesisNode(
            id=tag,
            title=label.strip(" —-–:[]") or f"Hypothesis {{tag}}",
            a_priori_mechanism=body[:200],
            falsification_criteria="Empirical performance regression vs baseline",
            target_evidence_level=EvidenceLevel.E3,
            current_evidence_level=EvidenceLevel.E0,
            status=status,
            parent_ids=[],
            tags=[tag.lower()]
        )
        hypotheses.append(h_node)

    print(f"[+] Extracted {{len(hypotheses)}} hypotheses and {{len(evidence)}} evidence claims.")
    
    # Commit into SQLite database
    res = store.bulk_import(hypotheses=hypotheses, evidence=evidence, upsert=True)
    print(f"[✓] Migration complete! Total in database: {{res['total_hypotheses']}} hypotheses.")

if __name__ == "__main__":
    main()
"""
