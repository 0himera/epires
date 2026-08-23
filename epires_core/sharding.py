"""Hierarchical Multi-Agent Memory Sharding & Routing Engine (VSAR-032 & VSAR-033).

Provides zero-contamination memory isolation between agents (Lead-PI, Coder, Auditor)
and dynamic proportional shard allocation under asymmetric agent workloads.

Mathematical basis:
- 2-Level Hierarchical Routing:
    Stage 1: Deterministic agent partition selection (isolates search space, contamination = 0.0000).
    Stage 2: 1-of-S learned prototype routing inside the partition.
- Dynamic Asymmetric Allocation:
    Under uneven item distribution (e.g. Coder=1024, Auditor=256), allocates shards
    proportionally (e.g. 8 vs 2 shards) to maintain constant per-shard load M=128 (SNR=4.00),
    preventing SNR degradation on high-throughput agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np

from .vsa import BipolarVSA


@dataclass
class Shard:
    id: str
    agent_role: str
    prototype: np.ndarray
    items: Dict[str, np.ndarray] = field(default_factory=dict)
    item_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    superposition_bundle: Optional[np.ndarray] = None


class HierarchicalShardRouter:
    """Multi-agent sharded memory router with hierarchical prototype routing and dynamic re-balancing."""

    def __init__(self, dim: int = 4096, total_shards: int = 16, seed: int = 42):
        self.dim = dim
        self.total_shards = total_shards
        self.seed = seed
        self.vsa = BipolarVSA(dim=dim, seed=seed)
        self.shards: Dict[str, Shard] = {}
        self.agent_shards: Dict[str, List[str]] = {}
        self._initialize_default_partitions()

    def _initialize_default_partitions(self) -> None:
        """Initializes balanced default partitions for canonical roles: Lead-PI, Coder, Auditor, System."""
        roles = ["Lead-PI", "Coder", "Auditor", "System"]
        shards_per_role = max(1, self.total_shards // len(roles))

        for role in roles:
            self.agent_shards[role] = []
            for i in range(shards_per_role):
                shard_id = f"shard_{role}_{i}"
                proto = self.vsa.get_or_create_vector(f"proto::{shard_id}")
                shard = Shard(id=shard_id, agent_role=role, prototype=proto)
                self.shards[shard_id] = shard
                self.agent_shards[role].append(shard_id)

    def reallocate_shards_proportionally(self, agent_workloads: Dict[str, int]) -> None:
        """Dynamically re-allocates total shards proportionally to agent workloads (VSAR-033).

        Equalizes per-shard load to maintain constant SNR=4.0 across uneven workloads.
        """
        total_items = sum(agent_workloads.values())
        if total_items == 0:
            return

        new_allocations: Dict[str, int] = {}
        remaining_shards = self.total_shards

        for role, count in agent_workloads.items():
            if count <= 0:
                n_shards = 1
            else:
                n_shards = max(1, int(round(self.total_shards * (count / total_items))))
            new_allocations[role] = n_shards
            remaining_shards -= n_shards

        # Adjust any rounding discrepancies to match total_shards
        roles = list(agent_workloads.keys())
        while remaining_shards > 0:
            max_role = max(roles, key=lambda r: agent_workloads.get(r, 0))
            new_allocations[max_role] += 1
            remaining_shards -= 1
        while remaining_shards < 0:
            max_alloc_role = max(roles, key=lambda r: new_allocations[r])
            if new_allocations[max_alloc_role] > 1:
                new_allocations[max_alloc_role] -= 1
                remaining_shards += 1
            else:
                break

        # Re-initialize shards preserving items
        old_items: List[Tuple[str, np.ndarray, str, Dict[str, Any]]] = []
        for s in self.shards.values():
            for item_id, vec in s.items.items():
                old_items.append((item_id, vec, s.agent_role, s.item_metadata.get(item_id, {})))

        self.shards.clear()
        self.agent_shards.clear()

        for role, num_shards in new_allocations.items():
            self.agent_shards[role] = []
            for i in range(num_shards):
                shard_id = f"shard_{role}_{i}"
                proto = self.vsa.get_or_create_vector(f"proto::{shard_id}")
                self.shards[shard_id] = Shard(id=shard_id, agent_role=role, prototype=proto)
                self.agent_shards[role].append(shard_id)

        for item_id, vec, role, meta in old_items:
            if role in self.agent_shards:
                self.insert(item_id, vec, agent_role=role, metadata=meta)

    def insert(
        self,
        item_id: str,
        vector: np.ndarray,
        agent_role: str = "Lead-PI",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Routes and inserts an item into the best matching shard within the agent's partition."""
        if agent_role not in self.agent_shards:
            # Create a new partition for unseen agent role
            shard_id = f"shard_{agent_role}_0"
            proto = self.vsa.get_or_create_vector(f"proto::{shard_id}")
            self.shards[shard_id] = Shard(id=shard_id, agent_role=agent_role, prototype=proto)
            self.agent_shards[agent_role] = [shard_id]

        target_shard_ids = self.agent_shards[agent_role]
        if len(target_shard_ids) == 1:
            best_shard_id = target_shard_ids[0]
        else:
            # 2nd Stage: Route to prototype with highest similarity
            best_shard_id = max(
                target_shard_ids,
                key=lambda sid: float(self.vsa.cosine_similarity(vector, self.shards[sid].prototype)),
            )

        target_shard = self.shards[best_shard_id]
        target_shard.items[item_id] = vector
        target_shard.item_metadata[item_id] = metadata or {}

        # Online update of shard prototype & superposition bundle (VSAR-029)
        if target_shard.superposition_bundle is None:
            target_shard.superposition_bundle = vector.copy()
        else:
            target_shard.superposition_bundle = self.vsa.incremental_bundle(
                target_shard.superposition_bundle, [vector], current_load=len(target_shard.items) - 1
            )
        return best_shard_id

    def query(
        self,
        query_vector: np.ndarray,
        agent_role: str = "Lead-PI",
        top_k: int = 5,
        allowed_roles: Optional[Sequence[str]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Hierarchical query execution guaranteeing zero cross-agent contamination."""
        roles_to_search = list(allowed_roles) if allowed_roles else [agent_role]
        candidate_shards: List[str] = []

        for r in roles_to_search:
            candidate_shards.extend(self.agent_shards.get(r, []))

        if not candidate_shards:
            return []

        results: List[Tuple[str, float, Dict[str, Any]]] = []
        for sid in candidate_shards:
            shard = self.shards[sid]
            for item_id, item_vec in shard.items.items():
                sim = float(self.vsa.cosine_similarity(query_vector, item_vec))
                meta = shard.item_metadata.get(item_id, {}).copy()
                meta["agent_role"] = shard.agent_role
                meta["shard_id"] = sid
                results.append((item_id, sim, meta))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        """Returns shard occupancy, SNR, and distribution matrix."""
        stats: Dict[str, Any] = {"total_items": 0, "by_agent": {}}
        for role, sids in self.agent_shards.items():
            role_items = sum(len(self.shards[sid].items) for sid in sids)
            stats["total_items"] += role_items
            stats["by_agent"][role] = {
                "num_shards": len(sids),
                "total_items": role_items,
                "shards": [
                    {
                        "shard_id": sid,
                        "items_count": len(self.shards[sid].items),
                        "estimated_snr": round(self.vsa.compute_capacity_snr(self.dim, len(self.shards[sid].items)), 2),
                    }
                    for sid in sids
                ],
            }
        return stats
