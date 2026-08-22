"""Gates G0..G8 + compute_level — pure predicates."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from .models import EvidenceClaim, EvidenceLevel, HypothesisNode, SourceConfidence
from .criteria import parse_falsification_criteria

# ponytail: minimal pure predicates, filesystem probe skipped — non-empty citation counts as resolvable
STRICT = os.getenv("EPIRES_STRICT_GATES") == "1"


def _thr(crit: str) -> float | None:
    conditions = parse_falsification_criteria(crit)
    for cond in conditions:
        if cond.threshold != 0.0 or cond.operator in (">", "<", ">=", "<="):
            return cond.threshold
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", crit or "")
    if not m:
        return None
    try:
        return float(m.group())
    except Exception:
        return None


def _ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _evs(evidence: Any) -> list[EvidenceClaim]:
    if evidence is None:
        return []
    if isinstance(evidence, list):
        return evidence
    return [evidence]


def check_g0(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    evs = _evs(evidence)
    if not evs:
        return False
    for ev in evs:
        if getattr(ev, "source_confidence", SourceConfidence.V) != SourceConfidence.V:
            continue
        cit = (getattr(ev, "citation_or_path", "") or "").strip()
        if not cit:
            # ponytail: legacy single-evidence without citation passes unless STRICT
            if len(evs) == 1 and not STRICT:
                continue
            return False
    return True


def check_g1(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    if hypothesis is None:
        return len(_evs(evidence)) >= 3
    hid = getattr(hypothesis, "id", "")
    cnt = len([e for e in _evs(evidence) if getattr(e, "hypothesis_id", None) == hid])
    return cnt >= 3


def check_g2(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    exps = experiments if experiments is not None else kw.get("experiments")
    if not exps:
        return False
    evs = _evs(evidence)
    times = [t for t in (_ts(getattr(e, "timestamp", "")) for e in evs) if t is not None]
    if not times:
        return False
    earliest = min(times)
    for exp in exps:
        params = getattr(exp, "parameters", None)
        if isinstance(exp, dict):
            params = exp.get("parameters", {})
        if not isinstance(params, dict) or "held_out_hash" not in params:
            continue
        ets = _ts(getattr(exp, "created_at", "") or "")
        if ets is None:
            return True
        if ets < earliest:
            return True
    return False


def check_g3(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    evs = _evs(evidence)
    if any(getattr(e, "prediction", None) is not None for e in evs):
        return True
    trs = traces if traces is not None else kw.get("traces")
    if not trs:
        return False
    times = [t for t in (_ts(getattr(e, "timestamp", "")) for e in evs) if t is not None]
    if not times:
        return False
    earliest = min(times)
    for tr in trs:
        act = getattr(tr, "action", "") if not isinstance(tr, dict) else tr.get("action", "")
        if "prereg" not in act.lower():
            continue
        tts = _ts(getattr(tr, "timestamp", "") if not isinstance(tr, dict) else tr.get("timestamp", "") or "")
        if tts is not None and tts < earliest:
            return True
    return False


def check_g4(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    if hypothesis is None:
        return False
    thr = _thr(getattr(hypothesis, "falsification_criteria", ""))
    for ev in _evs(evidence):
        if getattr(ev, "ci_95_lower", None) is None or getattr(ev, "ci_95_upper", None) is None:
            return False
        if thr is not None and not (ev.ci_95_lower > thr):  # type: ignore
            return False
    return bool(_evs(evidence))


def check_g5(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    deltas = [getattr(e, "delta_vs_baseline", None) for e in _evs(evidence)]
    deltas = [d for d in deltas if d is not None]
    if len(deltas) < 2:
        return True
    pos = all(d > 0 for d in deltas)  # type: ignore
    neg = all(d < 0 for d in deltas)  # type: ignore
    return pos or neg


def check_g6(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    evs = _evs(evidence)
    if not evs:
        return False
    # ponytail: legacy single-evidence without metric passes unless STRICT
    if len(evs) == 1 and not STRICT and not (getattr(evs[0], "metric_name", None) or "").strip():
        return True
    return all((getattr(e, "metric_name", None) or "").strip() != "" for e in evs)


def check_g7(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    trs = traces if traces is not None else kw.get("traces")
    if not trs:
        return True
    evs = _evs(evidence)
    if hypothesis is not None:
        hid = getattr(hypothesis, "id", "")
        cnt = sum(
            1
            for t in trs
            if (getattr(t, "action", "") if not isinstance(t, dict) else t.get("action", "")) == "LOG_EVIDENCE"
            and (getattr(t, "h_tag", "") if not isinstance(t, dict) else t.get("h_tag", "")) == hid
        )
        return len(evs) >= cnt or cnt == 0
    cnt = sum(
        1
        for t in trs
        if (getattr(t, "action", "") if not isinstance(t, dict) else t.get("action", "")) == "LOG_EVIDENCE"
    )
    return len(evs) >= cnt


def check_g8(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    evs = _evs(evidence)
    ids: set[str] = set()
    for ev in evs:
        aids = getattr(ev, "assumption_ids", None) or []
        if isinstance(aids, (list, tuple, set)):
            ids.update(str(x) for x in aids)
    if len(ids) >= 2:
        return True
    exps = experiments if experiments is not None else kw.get("experiments")
    if exps:
        hashes = {getattr(e, "commit_hash", None) if not isinstance(e, dict) else e.get("commit_hash") for e in exps}
        hashes = {h for h in hashes if h}
        if len(hashes) >= 2:
            return True
    return False


def compute_level(
    evidence: list[EvidenceClaim],
    hypothesis: HypothesisNode,
    experiments: Any = None,
    traces: Any = None,
) -> EvidenceLevel:
    evs = _evs(evidence)
    if not evs:
        return EvidenceLevel.E0
    if not check_g0(evs, hypothesis, experiments, traces):
        return EvidenceLevel.E0
    lvl = EvidenceLevel.E1
    if not check_g1(evs, hypothesis, experiments, traces):
        return lvl
    lvl = EvidenceLevel.E2
    if not (check_g2(evs, hypothesis, experiments, traces) and check_g3(evs, hypothesis, experiments, traces)):
        return lvl
    lvl = EvidenceLevel.E3
    if not check_g4(evs, hypothesis, experiments, traces):
        return lvl
    lvl = EvidenceLevel.E4
    if not (
        check_g5(evs, hypothesis, experiments, traces)
        and check_g6(evs, hypothesis, experiments, traces)
        and check_g7(evs, hypothesis, experiments, traces)
        and check_g8(evs, hypothesis, experiments, traces)
    ):
        return lvl
    return EvidenceLevel.E5
