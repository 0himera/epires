"""S3* independent auditor: another model re-verifies CONFIRMED hypotheses."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .models import TraceEntry
from .audit import audit_hypothesis


def _fmt_evidence(evs: List[Any]) -> str:
    lines = []
    for e in evs:
        ci = ""
        lo, hi = getattr(e, "ci_95_lower", None), getattr(e, "ci_95_upper", None)
        if lo is not None and hi is not None:
            ci = f" CI95=[{lo}, {hi}]"
        lines.append(
            f"- {getattr(e, 'id', '?')} [{getattr(e, 'evidence_level', '?')}]"
            f" {getattr(e, 'claim', '')}{ci}"
            f" source_confidence={getattr(e, 'source_confidence', '?')}"
            f" citation={getattr(e, 'citation_or_path', '')!r}"
        )
    return "\n".join(lines) or "(no evidence)"


def _fmt_experiments(exps: List[Any]) -> str:
    lines = []
    for x in exps:
        m = getattr(x, "metrics", None)
        lines.append(f"- {getattr(x, 'id', '?')} {getattr(x, 'name', '')} metrics={json.dumps(m)}")
    return "\n".join(lines) or "(no experiments)"


def audit_prompt(h: Any, evidence_list: List[Any], experiments: List[Any]) -> str:
    """Build the audit prompt for an independent model review."""
    return f"""You are an INDEPENDENT auditor (S3*). A hypothesis has been CONFIRMED by another system.
Re-verify it skeptically. Do not trust the confirming side.

Hypothesis:
- id: {getattr(h, 'id', '?')}
- title: {getattr(h, 'title', '?')}
- falsification_criteria: {getattr(h, 'falsification_criteria', '?')}

Evidence ({len(evidence_list)}):
{_fmt_evidence(evidence_list)}

Experiments ({len(experiments)}):
{_fmt_experiments(experiments)}

Check for: insufficient/misleading evidence, missing CIs, train-vs-holdout leakage,
selection bias, unfalsifiable criteria, claims not supported by experiments.
Return ONLY JSON: {{"verdict": "pass|flag|fail", "reason": "...", "violations": ["..."]}}
"""


def _parse_json(content: str) -> Dict[str, Any]:
    # ponytail: naive brace slice like LLMAgent; structured outputs if this breaks
    return json.loads(content[content.index("{") : content.rindex("}") + 1])


def independent_audit(
    h_id: str,
    store: Any,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> Dict[str, Any]:
    """Deterministic pre-test, then LLM re-verification. Never raises."""
    det = audit_hypothesis(h_id, store)
    if not det["passed"]:
        result = {"h_id": h_id, "verdict": "fail", "source": "deterministic", "violations": det["violations"]}
        store.log_trace(TraceEntry(timestamp=store._now(), action="S3_AUDIT", h_tag=h_id, summary="S3 audit fail (deterministic)", details=result))
        return result

    model = model or os.environ.get("EPIRES_AUDIT_MODEL", "opencode/x-preview-f-free")
    base_url = base_url or os.environ.get("EPIRES_AUDIT_BASE_URL") or os.environ.get("EPIRES_EVAL_BASE_URL", "https://api.openai.com/v1")
    api_key = api_key or os.environ.get("EPIRES_AUDIT_API_KEY") or os.environ.get("EPIRES_EVAL_API_KEY", "")

    h = store.get_hypothesis(h_id)
    evs = store.get_evidence_for_hypothesis(h_id)
    try:
        try:
            exps = store.list_experiments(h_id)
        except TypeError:
            exps = store.list_experiments(hypothesis_id=h_id)
    except Exception:
        exps = []

    try:
        import httpx

        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a skeptical independent auditor. Return only JSON."},
                    {"role": "user", "content": audit_prompt(h, evs, exps)},
                ],
            },
            timeout=120,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        verdict = _parse_json(content)
        result = {"h_id": h_id, "verdict": verdict.get("verdict", "inconclusive"), "source": "llm",
                  "reason": verdict.get("reason"), "violations": verdict.get("violations", [])}
    except Exception as e:  # ponytail: never let the auditor crash the caller
        result = {"h_id": h_id, "verdict": "inconclusive", "error": str(e)}

    store.log_trace(TraceEntry(timestamp=store._now(), action="S3_AUDIT", h_tag=h_id,
                               summary=f"S3 audit: {result['verdict']}", details=result))
    return result


def audit_confirmed(store: Any, model: str | None = None) -> List[Dict[str, Any]]:
    """Run independent_audit over all CONFIRMED hypotheses."""
    from .models import HypothesisStatus

    return [independent_audit(h.id, store, model=model) for h in store.list_hypotheses(status=HypothesisStatus.CONFIRMED)]
