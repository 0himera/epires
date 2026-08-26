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
        root_id: Optional[str] = None,
        depth: int = -1,
    ) -> str:
        """Generates a Mermaid graph markdown representing the hypothesis dependency DAG.

        frontier_only: If True, only includes active (PROPOSED / IN_PROGRESS) hypotheses and their immediate parents.
        statuses: If provided, filters to hypotheses matching the given status strings.
        root_id: If provided, extracts the connected subtree / neighborhood around this node.
        depth: Max traversal hops from root_id (-1 for entire connected component).
        """
        all_h = self.list_hypotheses()
        if not all_h:
            return "```mermaid\ngraph TD\n  Empty[No Hypotheses Registered]\n```"

        with self._get_connection() as conn:
            edges = conn.execute("SELECT * FROM relations").fetchall()

        # Build adjacency for bidirectional search
        neighbors: dict[str, set[str]] = {h.id: set() for h in all_h}
        for edge in edges:
            src = edge["source_id"]
            tgt = edge["target_id"]
            if src in neighbors and tgt in neighbors:
                neighbors[src].add(tgt)
                neighbors[tgt].add(src)

        target_nodes: set[str] = set()
        if root_id:
            if root_id not in neighbors:
                return f"```mermaid\ngraph TD\n  Empty[Hypothesis '{root_id}' Not Found]\n```"
            visited = {root_id}
            queue = [(root_id, 0)]
            while queue:
                curr, d = queue.pop(0)
                if depth >= 0 and d >= depth:
                    continue
                for nxt in neighbors.get(curr, ()):
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append((nxt, d + 1))
            target_nodes = visited
        elif frontier_only:
            active = [h for h in all_h if h.status in (HypothesisStatus.PROPOSED, HypothesisStatus.IN_PROGRESS)]
            for h in active:
                target_nodes.add(h.id)
                for pid in h.parent_ids:
                    target_nodes.add(pid)
        else:
            target_nodes = {h.id for h in all_h}

        if statuses:
            status_set = {s.upper() for s in statuses}
            target_nodes = {
                hid for hid in target_nodes if any(h.id == hid and h.status.value in status_set for h in all_h)
            }

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

    def get_summary(self) -> dict:
        """Returns an aggregated, lightweight status summary of the research graph."""
        all_h = self.list_hypotheses()
        by_status: dict[str, int] = {}
        by_level: dict[str, int] = {}
        active_frontier: list[dict] = []
        blocked_branches: list[str] = []
        falsified_nodes: list[str] = []
        confirmed_audit_passed: list[str] = []
        confirmed_audit_debt: list[str] = []

        for h in all_h:
            s = h.status.value
            lvl = h.current_evidence_level.value
            by_status[s] = by_status.get(s, 0) + 1
            by_level[lvl] = by_level.get(lvl, 0) + 1

            if h.status in (HypothesisStatus.PROPOSED, HypothesisStatus.IN_PROGRESS):
                active_frontier.append(
                    {
                        "id": h.id,
                        "title": h.title,
                        "status": h.status.value,
                        "current_level": h.current_evidence_level.value,
                        "target_level": h.target_evidence_level.value,
                        "parents": h.parent_ids,
                    }
                )
            elif h.status == HypothesisStatus.BLOCKED:
                blocked_branches.append(h.id)
            elif h.status == HypothesisStatus.FALSIFIED:
                falsified_nodes.append(h.id)
            if h.status == HypothesisStatus.CONFIRMED:
                audit = self.audit_pass(h.id)
                target = confirmed_audit_passed if audit.get("passed") else confirmed_audit_debt
                target.append(h.id)

        with self._get_connection() as conn:
            ev_count = conn.execute("SELECT COUNT(*) FROM evidence WHERE is_retracted = 0").fetchone()[0]
            exp_count = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
            trace_count = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]

        return {
            "total_hypotheses": len(all_h),
            "by_status": by_status,
            "by_evidence_level": by_level,
            "active_frontier": active_frontier,
            "blocked_branches": blocked_branches,
            "falsified_nodes": falsified_nodes,
            "audit_version": "gates-v2",
            "confirmed_audit_passed": confirmed_audit_passed,
            "confirmed_audit_debt": confirmed_audit_debt,
            "evidence_count": ev_count,
            "experiments_count": exp_count,
            "traces_count": trace_count,
        }

    def audit_pass(self, h_id: str) -> dict:
        from ..audit import audit_hypothesis

        return audit_hypothesis(h_id, self)

    def check_algedonic(self) -> list[dict]:
        from ..algedonic import check_triggers

        return check_triggers(self)
