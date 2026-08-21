"""Scoring: EIG + cost/deviation + Gupta test. EIG≈E_o[KL(q||q(·|o))]; fallback H(q)*coverage."""

from __future__ import annotations

import copy
import math
import random
from typing import Any

ALPHA = 1.0
BETA = 0.3
GAMMA = 0.5


def _normalize(d: dict[str, float]) -> dict[str, float]:
    s = sum(float(v) for v in d.values())
    if s <= 0:
        n = len(d) if d else 1
        return {k: 1.0 / n for k in d}
    return {k: float(v) / s for k, v in d.items()}


def _entropy(q: dict[str, float]) -> float:
    nq = _normalize(q)
    return -sum(p * math.log(max(p, 1e-12)) for p in nq.values())


def _kl(p: dict[str, float], q: dict[str, float]) -> float:
    pn = _normalize(p)
    qn = _normalize(q)
    eps = 1e-12
    s = 0.0
    for k, pv in pn.items():
        qv = qn.get(k, eps)
        s += max(pv, eps) * math.log(max(pv, eps) / max(qv, eps))
    return s


def eig_score(candidate_evidence: dict[str, Any], hypothesis_distribution: dict[str, float]) -> float:
    """Simplified EIG. candidate_evidence may contain: outcome_probs, posteriors, likelihood, eig, targets."""
    if not hypothesis_distribution:
        return 0.0
    q = _normalize(hypothesis_distribution)

    # direct value
    if "eig" in candidate_evidence:
        return float(candidate_evidence["eig"])

    # case 1: posteriors + outcome_probs → exact E_o[KL]
    outcome_probs = candidate_evidence.get("outcome_probs")
    posteriors = candidate_evidence.get("posteriors")
    likelihood = candidate_evidence.get("likelihood") or candidate_evidence.get("likelihoods")

    if isinstance(outcome_probs, dict) and isinstance(posteriors, dict):
        eig = 0.0
        for o, po in outcome_probs.items():
            qo = posteriors.get(o)
            if isinstance(qo, dict) and qo:
                eig += float(po) * _kl(q, _normalize(qo))
        return float(eig)

    # case 2: likelihood + q → Bayes
    if isinstance(likelihood, dict):
        outcomes = list(likelihood.keys())
        marg: dict[str, float] = {}
        for o in outcomes:
            lh = likelihood[o]
            if isinstance(lh, dict):
                marg[o] = sum(q.get(h, 0) * float(lh.get(h, 0)) for h in q)
        s = sum(marg.values())
        if s > 1e-12:
            marg = {k: v / s for k, v in marg.items()}
        eig = 0.0
        for o in outcomes:
            po = marg.get(o, 0)
            if po < 1e-12:
                continue
            lh = likelihood[o]
            if not isinstance(lh, dict):
                continue
            post = {h: q[h] * float(lh.get(h, 1e-9)) for h in q}
            sp = sum(post.values())
            if sp < 1e-12:
                continue
            post = {k: v / sp for k, v in post.items()}
            eig += po * _kl(q, post)
        if eig > 0:
            return float(eig)

    # case 3: posteriors with uniform outcome prior
    if isinstance(posteriors, dict):
        outs = list(posteriors.values())
        if outs and all(isinstance(x, dict) for x in outs):
            po = 1.0 / len(outs)
            return sum(po * _kl(q, _normalize(x)) for x in outs)  # type: ignore

    # fallback: H(q)*coverage — ponytail: LLM outcome model is ceiling
    h = _entropy(q)
    targets = candidate_evidence.get("targets") or candidate_evidence.get("hypotheses") or candidate_evidence.get("hypothesis_ids") or []
    if isinstance(targets, list) and targets:
        coverage = min(1.0, max(0.0, sum(q.get(str(t), 0) for t in targets)))
        return float(h * coverage * 0.5)
    for key in ("power", "relevance", "coverage"):
        if key in candidate_evidence:
            try:
                return float(h * min(1.0, max(0.0, float(candidate_evidence[key]))) * 0.5)
            except Exception:
                pass
    hv = ((hash(str(candidate_evidence.get("id", ""))) % 100) / 100.0) * 0.4 + 0.3
    return float(h * hv * 0.5)


def score_candidates(
    candidates: list[dict[str, Any]],
    q: dict[str, float],
    cost: dict[str, float] | None = None,
    alpha: float = ALPHA,
    beta: float = BETA,
    gamma: float = GAMMA,
) -> list[tuple[str, float]]:
    cost = cost or {}
    scored: list[tuple[str, float]] = []
    for c in candidates:
        cid = str(c.get("id", ""))
        eig = eig_score(c, q)
        cc = float(cost.get(cid, c.get("cost", 0.0) or 0.0))
        # deviation: promised vs expected
        dev = c.get("deviation_from_promised", c.get("deviation", None))
        if dev is None:
            if "promised_delta" in c or "expected_delta" in c:
                try:
                    dev = abs(float(c.get("promised_delta", 0)) - float(c.get("expected_delta", 0)))
                except Exception:
                    dev = 0.0
            else:
                dev = 0.0
        dev = float(dev)
        score = float(alpha) * eig - float(beta) * cc - float(gamma) * dev
        scored.append((cid, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def gupta_test(candidates: list[dict[str, Any]], q: dict[str, float], cost: dict[str, float] | None = None) -> bool:
    """Shuffle outcomes; True=sensitive ranking, False=broken."""
    if len(candidates) < 2:
        return True
    orig = [cid for cid, _ in score_candidates(candidates, q, cost)]
    shuffled = copy.deepcopy(candidates)
    field = None
    for k in ("outcome_probs", "likelihood", "likelihoods", "posteriors", "expected_outcomes", "outcomes", "eig", "power", "relevance"):
        if any(k in c for c in candidates):
            field = k
            break
    if field is None:
        for k in ("cost", "deviation_from_promised", "deviation", "promised_delta", "targets"):
            if any(k in c for c in candidates):
                field = k
                break
    if field is None:
        return False  # ponytail: outcome-blind pipeline
    vals = [c.get(field) for c in shuffled]
    if len(vals) >= 2 and all(str(v) == str(vals[0]) for v in vals):
        return True  # identical values → shuffle cannot be detected
    random.Random(42).shuffle(vals)
    for c, v in zip(shuffled, vals):
        c[field] = v
    new = [cid for cid, _ in score_candidates(shuffled, q, cost)]
    return orig != new
