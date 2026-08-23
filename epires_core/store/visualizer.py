"""Mermaid DAG visualization and epistemic audit/algedonic triggers."""

from __future__ import annotations

from typing import List, Optional
from ..models import HypothesisStatus, RelationType


class VisualizerMixin:
    """Provides Mermaid DAG export and high-level health/algedonic checks."""

    def export_mermaid_dag(
        self,
        frontier_only: bool = False,
        statuses: Optional[List[str]] = None,
    ) -> str:
        """Generates a Mermaid graph markdown representing the hypothesis dependency DAG.

        frontier_only: If True, only includes active (PROPOSED / IN_PROGRESS) hypotheses and their immediate parents.
        statuses: If provided, filters to hypotheses matching the given status strings.
        """
        all_h = self.list_hypotheses()
        if not all_h:
            return "```mermaid\ngraph TD\n  Empty[No Hypotheses Registered]\n```"

        target_nodes = set()
        if frontier_only:
            active = [h for h in all_h if h.status in (HypothesisStatus.PROPOSED, HypothesisStatus.IN_PROGRESS)]
            for h in active:
                target_nodes.add(h.id)
                for pid in h.parent_ids:
                    target_nodes.add(pid)
        elif statuses:
            status_set = {s.upper() for s in statuses}
            for h in all_h:
                if h.status.value in status_set:
                    target_nodes.add(h.id)
        else:
            target_nodes = {h.id for h in all_h}

        filtered_h = [h for h in all_h if h.id in target_nodes]
        if not filtered_h:
            return "```mermaid\ngraph TD\n  Empty[No Hypotheses Matched Filter]\n```"

        lines = ["```mermaid", "graph TD"]

        # Color classes
        lines.append("  classDef confirmed fill:#2ea043,stroke:#1b4b27,color:#fff;")
        lines.append("  classDef falsified fill:#da3633,stroke:#8e1519,color:#fff;")
        lines.append("  classDef blocked fill:#6e7681,stroke:#30363d,color:#fff;")
        lines.append("  classDef in_prog fill:#d29922,stroke:#bb8009,color:#fff;")
        lines.append("  classDef proposed fill:#58a6ff,stroke:#1f6feb,color:#fff;")

        with self._get_connection() as conn:
            edges = conn.execute("SELECT * FROM relations").fetchall()

        for h in filtered_h:
            status_style = {
                HypothesisStatus.CONFIRMED: "confirmed",
                HypothesisStatus.FALSIFIED: "falsified",
                HypothesisStatus.BLOCKED: "blocked",
                HypothesisStatus.IN_PROGRESS: "in_prog",
                HypothesisStatus.PROPOSED: "proposed",
                HypothesisStatus.REFINED: "in_prog",
            }.get(h.status, "proposed")

            title_clean = h.title.replace('"', "'")
            lines.append(
                f'  {h.id}["{h.id}: {title_clean}<br/>[{h.current_evidence_level.value} | {h.status.value}]"]:::{status_style}'
            )

        for edge in edges:
            src = edge["source_id"]
            tgt = edge["target_id"]
            if src in target_nodes and tgt in target_nodes:
                rel = edge["relation_type"]
                if rel == RelationType.DEPENDS_ON.value:
                    lines.append(f"  {src} --> {tgt}")
                elif rel == RelationType.BLOCKS.value:
                    lines.append(f"  {src} -.->|blocks| {tgt}")
                elif rel == RelationType.SUPERSEDES.value:
                    lines.append(f"  {src} ==>|supersedes| {tgt}")
                elif rel == RelationType.CONFLICTS_WITH.value:
                    lines.append(f"  {src} <-->|conflicts| {tgt}")
                else:
                    lines.append(f"  {src} --- {tgt}")

        lines.append("```")
        return "\n".join(lines)

    def audit_pass(self, h_id: str) -> dict:
        from ..audit import audit_hypothesis

        return audit_hypothesis(h_id, self)

    def check_algedonic(self) -> list[dict]:
        from ..algedonic import check_triggers

        return check_triggers(self)
