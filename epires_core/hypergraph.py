"""Hypergraph encoder mapping hypotheses, experiments and evidence into unified VSA hypervectors."""

from __future__ import annotations
from typing import List, Sequence
import numpy as np

from .models import HypothesisNode, ExperimentNode, EvidenceClaim, RelationEdge, Entity
from .vsa import BipolarVSA


class HypergraphEncoder:
    def __init__(self, vsa: BipolarVSA | None = None):
        self.vsa = vsa or BipolarVSA()

    def encode_entity(self, entity: Entity, role: str = "entity") -> np.ndarray:
        """Encodes an entity bound to its semantic role."""
        v_role = self.vsa.get_or_create_vector(f"ROLE:{role}")
        v_val = self.vsa.get_or_create_vector(entity.to_key())
        return self.vsa.bind(v_role, v_val)

    def encode_relation(self, edge: RelationEdge) -> np.ndarray:
        """Encodes a directed relation: Source ⊗ Rel ⊗ permute(Target)."""
        v_src = self.vsa.get_or_create_vector(f"NODE:{edge.source_id}")
        v_rel = self.vsa.get_or_create_vector(f"REL:{edge.relation_type.value}")
        v_tgt = self.vsa.get_or_create_vector(f"NODE:{edge.target_id}")
        
        # Permute target to encode directionality
        v_tgt_perm = self.vsa.permute(v_tgt, shifts=1)
        return self.vsa.bind(self.vsa.bind(v_src, v_rel), v_tgt_perm)

    def encode_hypothesis(
        self,
        hypothesis: HypothesisNode,
        relations: Sequence[RelationEdge] = (),
        evidence_claims: Sequence[EvidenceClaim] = (),
    ) -> np.ndarray:
        """Encodes an entire hypothesis into a single 10,000-D hypervector."""
        component_vectors: List[np.ndarray] = []

        # 1. Base identity
        v_id = self.vsa.get_or_create_vector(f"HYPOTHESIS:{hypothesis.id}")
        component_vectors.append(v_id)

        # 2. Status and Evidence Level
        v_status_role = self.vsa.get_or_create_vector("ROLE:status")
        v_status_val = self.vsa.get_or_create_vector(f"STATUS:{hypothesis.status.value}")
        component_vectors.append(self.vsa.bind(v_status_role, v_status_val))

        v_level_role = self.vsa.get_or_create_vector("ROLE:evidence_level")
        v_level_val = self.vsa.get_or_create_vector(f"LEVEL:{hypothesis.current_evidence_level.value}")
        component_vectors.append(self.vsa.bind(v_level_role, v_level_val))

        # 3. Associated Entities (Model, Feature, Regime, etc.)
        for ent in hypothesis.entities:
            component_vectors.append(self.encode_entity(ent, role="attribute"))

        # 4. Tags and Text Tokens
        for tag in hypothesis.tags:
            t = tag.lower().strip()
            if not t:
                continue
            v_tag = self.vsa.get_or_create_vector(f"TAG:{t}")
            v_tag_role = self.vsa.get_or_create_vector("ROLE:tag")
            component_vectors.append(v_tag)
            component_vectors.append(self.vsa.bind(v_tag_role, v_tag))

        # 5. Directed Relations (Parent-Child, Gating, Falsification)
        for rel in relations:
            component_vectors.append(self.encode_relation(rel))

        # 6. Evidence claims
        for claim in evidence_claims:
            v_claim_role = self.vsa.get_or_create_vector("ROLE:evidence")
            v_claim_level = self.vsa.get_or_create_vector(f"EVIDENCE_LEVEL:{claim.evidence_level.value}")
            v_conf = self.vsa.get_or_create_vector(f"CONFIDENCE:{claim.source_confidence.value}")
            claim_vec = self.vsa.bind(v_claim_role, self.vsa.bind(v_claim_level, v_conf))
            component_vectors.append(claim_vec)

        return self.vsa.bundle(component_vectors)

    def encode_query(
        self,
        text_terms: Sequence[str] = (),
        entities: Sequence[Entity] = (),
        status: str | None = None,
        level: str | None = None,
    ) -> np.ndarray:
        """Encodes an associative search query vector for cosine similarity matching."""
        query_vectors: List[np.ndarray] = []

        v_tag_role = self.vsa.get_or_create_vector("ROLE:tag")
        for term in text_terms:
            t = term.lower().strip()
            if not t:
                continue
            v_term = self.vsa.get_or_create_vector(f"TAG:{t}")
            query_vectors.append(v_term)
            query_vectors.append(self.vsa.bind(v_tag_role, v_term))

        for ent in entities:
            query_vectors.append(self.encode_entity(ent, role="attribute"))

        if status:
            v_status_role = self.vsa.get_or_create_vector("ROLE:status")
            v_status_val = self.vsa.get_or_create_vector(f"STATUS:{status}")
            query_vectors.append(self.vsa.bind(v_status_role, v_status_val))

        if level:
            v_level_role = self.vsa.get_or_create_vector("ROLE:evidence_level")
            v_level_val = self.vsa.get_or_create_vector(f"LEVEL:{level}")
            query_vectors.append(self.vsa.bind(v_level_role, v_level_val))

        if not query_vectors:
            return self.vsa.generate_vector()

        return self.vsa.bundle(query_vectors)
