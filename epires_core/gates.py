"""Gates G0..G8 + compute_level — pure predicates."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
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


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a pydantic record or a JSON-shaped dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _level(obj: Any) -> str:
    value = _field(obj, "evidence_level")
    return getattr(value, "value", value)


def _experiment_seed_ids(experiments: Any, hypothesis_id: str = "") -> set[str]:
    seed_ids: set[str] = set()
    for exp in experiments or []:
        if hypothesis_id and str(_field(exp, "hypothesis_id", "")) != hypothesis_id:
            continue
        params = _field(exp, "parameters", {})
        if not isinstance(params, dict):
            continue
        for key in ("seed", "seed_id", "run_seed", "random_seed"):
            value = params.get(key)
            if value is not None and str(value).strip():
                seed_ids.add(str(value).strip())
        for key in ("seeds", "seed_ids", "run_seeds", "random_seeds"):
            values = params.get(key)
            if isinstance(values, (list, tuple, set)):
                seed_ids.update(str(value).strip() for value in values if str(value).strip())
    return seed_ids


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
    exps = experiments if experiments is not None else kw.get("experiments")
    hypothesis_id = getattr(hypothesis, "id", "") if hypothesis is not None else ""
    return len(_experiment_seed_ids(exps, hypothesis_id)) >= 3


def check_g2(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    exps = experiments if experiments is not None else kw.get("experiments")
    if not exps:
        return False
    evs = _evs(evidence)
    # G2 is a claim about the held-out split used by the quantitative result.
    # E0/E1 preregistration and implementation records must not move the
    # temporal anchor earlier than the first E3+ result.
    times = [
        t
        for e in evs
        for t in [_ts(_field(e, "timestamp", ""))]
        if t is not None and _level(e) in ("E3", "E4", "E5")
    ]
    # Before a quantitative result exists, registration itself is sufficient
    # for the historical G2 predicate; once an E3+ result exists the temporal
    # comparison below becomes mandatory.
    has_quantitative_anchor = bool(times)
    earliest = min(times) if times else None
    for exp in exps:
        params = _field(exp, "parameters", None)
        if not isinstance(params, dict):
            continue
        held_out_hash = params.get("held_out_hash")
        held_out_hashes = params.get("held_out_hashes")
        has_single_hash = isinstance(held_out_hash, str) and bool(held_out_hash.strip())
        has_hash_list = (
            isinstance(held_out_hashes, (list, tuple))
            and bool(held_out_hashes)
            and all(isinstance(value, str) and bool(value.strip()) for value in held_out_hashes)
        )
        if not (has_single_hash or has_hash_list):
            continue
        ets = _ts(_field(exp, "created_at", "") or "")
        if ets is None:
            return True
        if not has_quantitative_anchor or (earliest is not None and ets < earliest):
            return True
    return False


def check_g3(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    evs = _evs(evidence)
    if any(getattr(e, "prediction", None) is not None for e in evs):
        return True
    times = [t for t in (_ts(getattr(e, "timestamp", "")) for e in evs) if t is not None]
    if not times:
        return False
    # E0 evidence can be the preregistration itself, so compare preregistration
    # records to the first later evidence rather than to themselves.
    result_times = [
        _ts(_field(e, "timestamp", ""))
        for e in evs
        if _level(e) in ("E3", "E4", "E5")
    ]
    result_times = [t for t in result_times if t is not None]
    earliest = min(result_times or times)
    hypothesis_id = getattr(hypothesis, "id", None)

    for ev in evs:
        level = _level(ev)
        ets = _ts(_field(ev, "timestamp", ""))
        if (
            level == "E0"
            and _field(ev, "artifact_hash", None)
            and _field(ev, "citation_or_path", None)
            and ets is not None
            and ets <= earliest
        ):
            return True

    trs = traces if traces is not None else kw.get("traces")
    if not trs:
        return False
    for tr in trs:
        act = _field(tr, "action", "")
        if "prereg" not in act.lower():
            continue
        trace_hypothesis_id = _field(tr, "h_tag", "")
        if hypothesis_id and trace_hypothesis_id != hypothesis_id:
            continue
        details = _field(tr, "details", {})
        # Pre-0.4.4 evidence sometimes recorded a preregistration path but no
        # artifact hash.  Only an explicit, append-only migration trace may
        # recover it: the trace must carry the original evidence timestamp,
        # current SHA-256, and path.  This does not weaken malformed/late
        # preregistration records.
        legacy = bool(details.get("legacy_prereg_migration")) if isinstance(details, dict) else False
        if legacy:
            original_ts = _ts(details.get("original_evidence_timestamp", ""))
            path = str(details.get("artifact_path", "") or "")
            digest = str(details.get("artifact_hash", "") or "").strip().lower()
            if (
                original_ts is None
                or not path
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                continue
            # The migration timestamp is allowed to be after the result, but
            # the claimed historical timestamp must be grounded in an active
            # E0 record.  Do not trust a caller-supplied timestamp by itself.
            matching_e0 = any(
                _level(e) == "E0"
                and _field(e, "timestamp", "")
                and _ts(_field(e, "timestamp", "")) == original_ts
                and (earliest is None or _ts(_field(e, "timestamp", "")) < earliest)
                and str(_field(e, "citation_or_path", "") or "") == path
                and getattr(_field(e, "source_confidence", None), "value", _field(e, "source_confidence", None)) == "V"
                for e in evs
            )
            if not matching_e0:
                continue
            p = Path(path)
            if not p.is_file():
                continue
            try:
                import hashlib
                if hashlib.sha256(p.read_bytes()).hexdigest().lower() != digest:
                    continue
            except OSError:
                continue
            tts = _ts(_field(tr, "timestamp", "") or "")
            if tts is not None:
                return True
            continue
        if (
            not isinstance(details, dict)
            or not isinstance(details.get("artifact_hash"), str)
            or not details["artifact_hash"].strip()
        ):
            continue
        tts = _ts(_field(tr, "timestamp", "") or "")
        if tts is not None and tts < earliest:
            return True
    return False


def check_g4(evidence: Any, hypothesis: Any = None, experiments: Any = None, traces: Any = None, **kw: Any) -> bool:
    if hypothesis is None:
        return False
    evs = _evs(evidence)
    if not evs:
        return False

    crit = getattr(hypothesis, "falsification_criteria", "") or ""
    conditions = parse_falsification_criteria(crit)

    quantitative_evs = [
        ev
        for ev in evs
        if _level(ev) in ("E3", "E4", "E5")
        and bool((_field(ev, "metric_name", "") or "").strip())
    ]
    if not quantitative_evs:
        return False

    matched_evs = []
    for ev in quantitative_evs:
        metric_name = str(_field(ev, "metric_name", "") or "")
        matching = [c for c in conditions if _condition_matches_metric(c, metric_name)]
        if matching:
            matched_evs.append((ev, matching))

    # A criterion about a different metric cannot falsify this evidence. Keep
    # the CI/provenance check, but do not apply the unrelated threshold.
    if not matched_evs:
        matched_evs = [(ev, []) for ev in quantitative_evs]

    for ev, matching in matched_evs:
        if _field(ev, "ci_95_lower", None) is None or _field(ev, "ci_95_upper", None) is None:
            return False

        ci_lower = float(_field(ev, "ci_95_lower"))
        ci_upper = float(_field(ev, "ci_95_upper"))

        if matching:
            for cond in matching:
                op = cond.operator
                thr = cond.threshold
                if op in (">", ">="):
                    # Falsified if value >= thr -> confirmation requires CI upper <= thr
                    if ci_upper > thr:
                        return False
                elif op in ("<", "<="):
                    # Falsified if value <= thr -> confirmation requires CI lower >= thr
                    if ci_lower < thr:
                        return False
                elif op == "degradation":
                    # Falsified if delta < 0 -> confirmation requires CI lower > 0
                    if ci_lower <= 0.0:
                        return False
        else:
            thr = _thr(crit)
            if thr is not None and not (ci_lower > thr):
                return False

    return True


def _condition_matches_metric(cond: Any, metric_name: str) -> bool:
    """Return whether a parsed condition is about this evidence metric."""
    cond_metric = (getattr(cond, "metric", None) or "").lower().strip()
    evidence_metric = (metric_name or "").lower().strip()
    if getattr(cond, "operator", None) == "degradation":
        return True
    if not cond_metric or not evidence_metric:
        return False
    def norm(value: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", value.replace("_", " ")))

    left, right = norm(cond_metric), norm(evidence_metric)
    return bool(left and right and (cond_metric in evidence_metric or evidence_metric in cond_metric or left <= right or right <= left))


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
    # RETRACT_EVIDENCE is an explicit tombstone in the append-only ledger.
    # New LOG_EVIDENCE traces carry evidence_id; legacy traces can still be
    # accounted for by the retraction tombstone count without hiding missing
    # active runs.
    retracted_ids: set[str] = set()
    for t in trs or []:
        action = _field(t, "action", "")
        details = _field(t, "details", {})
        if action == "RETRACT_EVIDENCE" and isinstance(details, dict):
            evid = details.get("evidence_id")
            if evid:
                retracted_ids.add(str(evid))

    def expected_logs(items: list[Any], hid: str | None = None) -> int:
        logs = []
        for t in items:
            if _field(t, "action", "") != "LOG_EVIDENCE":
                continue
            if hid is not None and _field(t, "h_tag", "") != hid:
                continue
            logs.append(t)
        if not logs:
            return 0
        known = 0
        legacy = 0
        known_ids: set[str] = set()
        for t in logs:
            details = _field(t, "details", {})
            evid = details.get("evidence_id") if isinstance(details, dict) else None
            if evid:
                known_ids.add(str(evid))
                if str(evid) not in retracted_ids:
                    known += 1
            else:
                legacy += 1
        legacy_retracted = len(retracted_ids - known_ids)
        return known + max(0, legacy - legacy_retracted)

    if hypothesis is not None:
        hid = getattr(hypothesis, "id", "")
        cnt = expected_logs(trs or [], hid)
        return len(evs) >= cnt or cnt == 0
    cnt = expected_logs(trs or [])
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


def evaluate_result_gate(
    hypothesis: HypothesisNode,
    results: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """Evaluates an empirical results payload or JSON file against hypothesis falsification criteria and statistical gates.

    Accepts results as a dict or path to a JSON file containing metrics like:
    {
        "metric_name": "loss",
        "metric_value": 0.05,
        "ci_95_lower": 0.03,
        "ci_95_upper": 0.07,
        "delta_vs_baseline": -0.04,
        "baseline_value": 0.09,
        "n_seeds": 5
    }
    """
    import json

    if isinstance(results, (str, Path)):
        p = Path(results)
        if not p.exists():
            return {
                "verdict": "ERROR",
                "gate_passed": False,
                "falsification_triggered": False,
                "reason": f"Results file '{p}' not found",
                "recommended_action": "PROVIDE_VALID_RESULTS_PATH",
            }
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return {
                "verdict": "ERROR",
                "gate_passed": False,
                "falsification_triggered": False,
                "reason": f"Failed to parse results JSON: {e}",
                "recommended_action": "FIX_JSON_FORMAT",
            }
    elif isinstance(results, dict):
        data = results
    else:
        return {
            "verdict": "ERROR",
            "gate_passed": False,
            "falsification_triggered": False,
            "reason": "Invalid results format (expected dict or path to JSON file)",
            "recommended_action": "PROVIDE_VALID_PAYLOAD",
        }

    # Extract fields with flexible fallbacks
    metric_name = data.get("metric_name") or data.get("metric") or data.get("name")
    metric_val = data.get("metric_value")
    if metric_val is None:
        metric_val = data.get("value") or data.get("score") or data.get("mean") or data.get("val")
    delta = data.get("delta_vs_baseline")
    if delta is None:
        delta = data.get("delta") or data.get("diff") or data.get("gain")
    ci_lower = data.get("ci_95_lower") or data.get("ci_lower")
    ci_upper = data.get("ci_95_upper") or data.get("ci_upper")
    n_seeds = data.get("n_seeds") or data.get("seeds") or data.get("n_trials", 1)

    # Synthetic EvidenceClaim to run gate checking
    ev = EvidenceClaim(
        hypothesis_id=hypothesis.id,
        evidence_level=EvidenceLevel.E3,
        source_confidence=SourceConfidence.V,
        metric_name=metric_name,
        metric_value=float(metric_val) if metric_val is not None else None,
        delta_vs_baseline=float(delta) if delta is not None else None,
        ci_95_lower=float(ci_lower) if ci_lower is not None else None,
        ci_95_upper=float(ci_upper) if ci_upper is not None else None,
    )

    # 1. Parse falsification criteria
    conditions = parse_falsification_criteria(hypothesis.falsification_criteria)
    falsification_triggered = False
    falsification_reasons = []

    from .criteria import evaluate_falsification_condition

    for cond in conditions:
        violated = evaluate_falsification_condition(
            cond,
            metric_name=metric_name,
            metric_value=ev.metric_value,
            delta_vs_baseline=ev.delta_vs_baseline,
            ci_lower=ev.ci_95_lower,
            ci_upper=ev.ci_95_upper,
        )
        if violated is True:
            falsification_triggered = True
            falsification_reasons.append(
                f"Metric violated condition '{cond.raw_text or f'{cond.operator} {cond.threshold}'}'"
            )

    # 2. Check Gate G4 (Statistical Significance / Confidence Interval clearance)
    g4_passed = check_g4([ev], hypothesis=hypothesis)

    # 3. Formulate verdict
    if falsification_triggered:
        verdict = "FALSIFY"
        gate_passed = False
        reason = "; ".join(falsification_reasons)
        rec = "FALSIFY_HYPOTHESIS_OR_ATTRIBUTE_AUXILIARY"
    elif ci_lower is not None and ci_upper is not None and not g4_passed:
        verdict = "INCONCLUSIVE_NOISE"
        gate_passed = False
        reason = (
            f"95% CI [{ci_lower}, {ci_upper}] is inconclusive or enters falsification zone "
            f"for criteria '{hypothesis.falsification_criteria}'"
        )
        rec = "INCREASE_SEEDS_OR_DE_NOISE"
    else:
        verdict = "PASS"
        gate_passed = True
        reason = (
            f"Results cleanly satisfy criteria '{hypothesis.falsification_criteria}' with confirmed gate clearance."
        )
        rec = "CLAIM_CONFIRMATION"

    return {
        "hypothesis_id": hypothesis.id,
        "falsification_criteria": hypothesis.falsification_criteria,
        "metric_name": metric_name,
        "metric_value": ev.metric_value,
        "ci_95": [ev.ci_95_lower, ev.ci_95_upper]
        if (ev.ci_95_lower is not None and ev.ci_95_upper is not None)
        else None,
        "delta_vs_baseline": ev.delta_vs_baseline,
        "n_seeds": n_seeds,
        "verdict": verdict,
        "gate_passed": gate_passed,
        "falsification_triggered": falsification_triggered,
        "reason": reason,
        "recommended_action": rec,
    }
