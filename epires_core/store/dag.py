"""DAG cycle validation, cascading falsification, and unblocking."""

from __future__ import annotations

import json
from typing import Dict, List
from ..models import HypothesisStatus, RelationType, TraceEntry


class DAGMixin:
    """Provides DAG graph algorithms for dependency validation and falsification cascading."""

    def _check_dag_cycle(self, node_id: str, proposed_parents: List[str]) -> None:
        """Verifies that adding proposed_parents as dependencies to node_id does not form a directed cycle."""
        if not proposed_parents:
            return

        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT source_id, target_id FROM relations WHERE relation_type = ?", (RelationType.DEPENDS_ON.value,)
            ).fetchall()

        adj: Dict[str, List[str]] = {}
        for r in rows:
            src, tgt = r["source_id"], r["target_id"]
            if src != node_id:  # replace existing parent edges for this node
                adj.setdefault(src, []).append(tgt)

        for parent in proposed_parents:
            if parent == node_id:
                raise ValueError(f"Self-dependency cycle detected: hypothesis '{node_id}' cannot depend on itself.")

            # BFS from parent to see if it can reach node_id
            visited = set()
            queue = [parent]
            while queue:
                curr = queue.pop(0)
                if curr == node_id:
                    raise ValueError(
                        f"DAG cycle detected: hypothesis '{node_id}' cannot depend on '{parent}' "
                        f"because '{parent}' already transitively depends on '{node_id}'."
                    )
                if curr not in visited:
                    visited.add(curr)
                    queue.extend(adj.get(curr, []))

    def _cascade_falsification(self, falsified_h_id: str) -> List[str]:
        """Finds all child hypotheses that depend on the falsified parent and marks them BLOCKED."""
        blocked: List[str] = []
        with self._get_connection() as conn:
            # Recursive query to find all downstream dependent hypotheses
            cursor = conn.execute(
                """
            WITH RECURSIVE downstream AS (
                SELECT source_id AS child_id FROM relations
                WHERE target_id = ? AND relation_type = 'DEPENDS_ON'
                UNION
                SELECT r.source_id FROM relations r
                JOIN downstream d ON r.target_id = d.child_id
                WHERE r.relation_type = 'DEPENDS_ON'
            )
            SELECT child_id FROM downstream;
            """,
                (falsified_h_id,),
            )
            rows = cursor.fetchall()
            for r in rows:
                child_id = r["child_id"]
                child_status = conn.execute("SELECT status FROM hypotheses WHERE id = ?", (child_id,)).fetchone()
                # A separately falsified child remains FALSIFIED; do not
                # replace one terminal scientific result with another label.
                if child_status and child_status["status"] == HypothesisStatus.FALSIFIED.value:
                    continue
                conn.execute(
                    "UPDATE hypotheses SET status = ?, updated_at = ? WHERE id = ?",
                    (HypothesisStatus.BLOCKED.value, self._now(), child_id),
                )
                conn.execute(
                    """
                INSERT OR IGNORE INTO relations (source_id, target_id, relation_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                    (falsified_h_id, child_id, RelationType.BLOCKS.value, json.dumps({"reason": "parent_falsified"})),
                )
                blocked.append(child_id)

        if blocked:
            self.log_trace(
                TraceEntry(
                    timestamp=self._now(),
                    action="CASCADING_BLOCK",
                    agent_role="System-DAG",
                    h_tag=falsified_h_id,
                    summary=f"Falsification of {falsified_h_id} cascaded to block dependent hypotheses: {', '.join(blocked)}",
                    details={"blocked_hypotheses": blocked},
                )
            )
        return blocked

    def _cascade_unblock(self, unblocked_h_id: str) -> List[str]:
        """Finds all child hypotheses that were BLOCKED by unblocked_h_id, checks if all their

        parents are now valid, and if so restores their status and cascades to their descendants.
        """
        unblocked: List[str] = []
        with self._get_connection() as conn:
            # Remove BLOCKS relations originating from this unblocked parent
            conn.execute(
                "DELETE FROM relations WHERE source_id = ? AND relation_type = ?",
                (unblocked_h_id, RelationType.BLOCKS.value),
            )

            # Query all downstream candidates that depend on unblocked_h_id
            cursor = conn.execute(
                """
            WITH RECURSIVE downstream AS (
                SELECT source_id AS child_id FROM relations
                WHERE target_id = ? AND relation_type = 'DEPENDS_ON'
                UNION
                SELECT r.source_id FROM relations r
                JOIN downstream d ON r.target_id = d.child_id
                WHERE r.relation_type = 'DEPENDS_ON'
            )
            SELECT DISTINCT child_id FROM downstream;
            """,
                (unblocked_h_id,),
            )
            candidates = [r["child_id"] for r in cursor.fetchall()]

        # Process candidates
        for child_id in candidates:
            child = self.get_hypothesis(child_id)
            if not child or child.status != HypothesisStatus.BLOCKED:
                continue

            # Check if ANY parent of child_id is currently FALSIFIED or BLOCKED
            parent_ids = child.parent_ids
            has_blocked_parent = False
            for p_id in parent_ids:
                parent = self.get_hypothesis(p_id)
                if parent and parent.status in {HypothesisStatus.FALSIFIED, HypothesisStatus.BLOCKED}:
                    has_blocked_parent = True
                    break

            if not has_blocked_parent:
                # All parents are healthy! Restore child status based on its own active evidence
                child_ev = self.get_evidence_for_hypothesis(child_id)
                has_own_falsification = any(ev.falsification_triggered for ev in child_ev)
                if has_own_falsification:
                    child.status = HypothesisStatus.FALSIFIED
                elif len(child_ev) == 0:
                    child.status = HypothesisStatus.PROPOSED
                elif child.current_evidence_level.value >= child.target_evidence_level.value:
                    child.status = HypothesisStatus.CONFIRMED
                else:
                    child.status = HypothesisStatus.IN_PROGRESS

                self.register_hypothesis(child, allow_status_override=True, emit_trace=False)
                unblocked.append(child_id)
                # Recursively cascade unblocking for child's descendants
                sub_unblocked = self._cascade_unblock(child_id)
                unblocked.extend([sub for sub in sub_unblocked if sub not in unblocked])

        return unblocked
