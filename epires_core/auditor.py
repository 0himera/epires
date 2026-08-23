"""S3* independent auditor: another model re-verifies CONFIRMED hypotheses."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from .models import AuditVerdict, TraceEntry
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
- id: {getattr(h, "id", "?")}
- title: {getattr(h, "title", "?")}
- falsification_criteria: {getattr(h, "falsification_criteria", "?")}

Evidence ({len(evidence_list)}):
{_fmt_evidence(evidence_list)}

Experiments ({len(experiments)}):
{_fmt_experiments(experiments)}

Check for: insufficient/misleading evidence, missing CIs, train-vs-holdout leakage,
selection bias, unfalsifiable criteria, claims not supported by experiments.
Return ONLY valid JSON matching this schema:
{{
  "verdict": "pass" | "flag" | "fail",
  "reason": "summary explanation",
  "violations": ["violation 1", "violation 2"]
}}
"""


def parse_audit_verdict(content: str) -> AuditVerdict:
    """Robustly parses an LLM response into an AuditVerdict instance.

    Handles markdown fences, extraneous text, and missing keys.
    """
    cleaned = (content or "").strip()
    # Strip markdown code blocks
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()

    # Extract JSON between outermost braces
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        raw_obj = json.loads(cleaned[start:end])
    except Exception as e:
        return AuditVerdict(
            verdict="inconclusive",
            reason=f"Failed to parse JSON from auditor output: {e}",
            violations=[],
            source="llm",
        )

    if not isinstance(raw_obj, dict):
        return AuditVerdict(
            verdict="inconclusive",
            reason="Auditor response is not a JSON object",
            violations=[],
            source="llm",
        )

    raw_verdict = str(raw_obj.get("verdict", "")).lower().strip()
    if raw_verdict not in ("pass", "flag", "fail", "inconclusive"):
        raw_verdict = "inconclusive"

    raw_violations = raw_obj.get("violations", [])
    if isinstance(raw_violations, str):
        raw_violations = [raw_violations]
    elif not isinstance(raw_violations, list):
        raw_violations = []

    return AuditVerdict(
        verdict=raw_verdict,
        reason=str(raw_obj.get("reason", "")) if raw_obj.get("reason") else None,
        violations=[str(v) for v in raw_violations if v],
        source="llm",
    )


def _parse_json(content: str) -> Dict[str, Any]:
    """Backwards-compatible dict extraction delegating to parse_audit_verdict."""
    return parse_audit_verdict(content).model_dump()


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
        store.log_trace(
            TraceEntry(
                timestamp=store._now(),
                action="S3_AUDIT",
                h_tag=h_id,
                summary="S3 audit fail (deterministic)",
                details=result,
            )
        )
        return result

    model = model or os.environ.get("EPIRES_AUDIT_MODEL") or os.environ.get("EPIRES_EVAL_MODEL", "gpt-4o-mini")
    base_url = (
        base_url
        or os.environ.get("EPIRES_AUDIT_BASE_URL")
        or os.environ.get("EPIRES_EVAL_BASE_URL", "https://api.openai.com/v1")
    )
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

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a skeptical independent auditor. Return only valid JSON."},
                {"role": "user", "content": audit_prompt(h, evs, exps)},
            ],
            "response_format": {"type": "json_object"},
        }

        try:
            r = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=120,
            )
            r.raise_for_status()
        except Exception:
            # Fallback without response_format if provider does not support it
            payload.pop("response_format", None)
            r = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=120,
            )
            r.raise_for_status()

        content = r.json()["choices"][0]["message"]["content"]
        audit_obj = parse_audit_verdict(content)
        result = {
            "h_id": h_id,
            "verdict": audit_obj.verdict,
            "source": audit_obj.source or "llm",
            "reason": audit_obj.reason,
            "violations": audit_obj.violations,
        }
    except Exception as e:  # ponytail: never let the auditor crash the caller
        result = {"h_id": h_id, "verdict": "inconclusive", "error": str(e)}

    store.log_trace(
        TraceEntry(
            timestamp=store._now(),
            action="S3_AUDIT",
            h_tag=h_id,
            summary=f"S3 audit: {result['verdict']}",
            details=result,
        )
    )
    return result


def audit_confirmed(store: Any, model: str | None = None) -> List[Dict[str, Any]]:
    """Run independent_audit over all CONFIRMED hypotheses."""
    from .models import HypothesisStatus

    return [
        independent_audit(h.id, store, model=model) for h in store.list_hypotheses(status=HypothesisStatus.CONFIRMED)
    ]
