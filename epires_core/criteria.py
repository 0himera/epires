"""Structured parsing and evaluation of hypothesis falsification criteria."""

from __future__ import annotations

import re
from typing import List, Optional
from .models import FalsificationCondition


# Matches comparison patterns: [metric/text] [operator] [signed number] [optional unit]
_OP_REGEX = re.compile(
    r"(?P<metric>[a-zA-Z0-9_\-\s]+?)?\s*"
    r"(?P<operator>>=|<=|==|!=|>|<)\s*"
    r"(?P<value>[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*"
    r"(?P<unit>%|pp|ms|s|kb|mb|gb)?",
    re.IGNORECASE,
)

_DEGRADATION_KEYWORDS = ("degradation", "regression", "drop", "drift", "loss")


def parse_falsification_criteria(text: str | None) -> List[FalsificationCondition]:
    """Parses free-text or structured falsification criteria into typed FalsificationCondition list.

    Handles compound criteria (separated by 'or', 'and', semicolons, or newlines).
    Supports comparisons (>, <, >=, <=, ==, !=), percentages (%), percentage points (pp),
    and descriptive degradation clauses.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    conditions: List[FalsificationCondition] = []

    # Split compound clauses by "or", "and", semicolons, newlines, or commas (outside parens)
    clauses = [c.strip() for c in re.split(r"\s+(?:or|and)\s+|[;\n]+", raw, flags=re.IGNORECASE) if c.strip()]

    for clause in clauses:
        # Match explicit operator + threshold pattern
        matched = False
        for m in _OP_REGEX.finditer(clause):
            metric = (m.group("metric") or "").strip()
            operator = m.group("operator").strip()
            val_str = m.group("value").strip()
            unit = m.group("unit")
            try:
                threshold = float(val_str)
                conditions.append(
                    FalsificationCondition(
                        metric=metric if metric else None,
                        operator=operator,
                        threshold=threshold,
                        unit=unit,
                        raw_text=clause,
                    )
                )
                matched = True
            except ValueError:
                continue

        if not matched:
            # Check for pure numerical threshold without operator
            num_match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", clause)
            if num_match:
                try:
                    val = float(num_match.group())
                    conditions.append(
                        FalsificationCondition(
                            metric=None,
                            operator=">",
                            threshold=val,
                            raw_text=clause,
                        )
                    )
                    continue
                except ValueError:
                    pass

            # Check for qualitative degradation clause
            if any(k in clause.lower() for k in _DEGRADATION_KEYWORDS):
                conditions.append(
                    FalsificationCondition(
                        metric=None,
                        operator="degradation",
                        threshold=0.0,
                        raw_text=clause,
                    )
                )
            else:
                # Store unparsed text condition as raw condition
                conditions.append(
                    FalsificationCondition(
                        metric=None,
                        operator="text_match",
                        threshold=0.0,
                        raw_text=clause,
                    )
                )

    return conditions


def evaluate_falsification_condition(
    cond: FalsificationCondition,
    metric_name: Optional[str] = None,
    metric_value: Optional[float] = None,
    delta_vs_baseline: Optional[float] = None,
    ci_lower: Optional[float] = None,
    ci_upper: Optional[float] = None,
) -> Optional[bool]:
    """Evaluates whether an observed evidence metric triggers the given falsification condition.

    Returns:
        True: condition met (falsification triggered)
        False: condition evaluated and NOT met
        None: condition cannot be evaluated against provided evidence values
    """
    if cond.operator == "degradation":
        if delta_vs_baseline is not None:
            return delta_vs_baseline < 0.0
        return None

    # Determine which target value to check: delta_vs_baseline, metric_value, or CI
    target_val: Optional[float] = None

    cond_metric = (cond.metric or "").lower().strip()
    if "delta" in cond_metric or "gain" in cond_metric or "increase" in cond_metric or "diff" in cond_metric:
        target_val = delta_vs_baseline
    elif cond_metric and metric_name:
        # Check if condition metric matches evidence metric
        m_name = metric_name.lower().strip()
        if m_name in cond_metric or cond_metric in m_name:
            target_val = metric_value if metric_value is not None else delta_vs_baseline
        else:
            # Specific metric mismatch
            return None
    else:
        # Default priority: delta if available, else metric_value, else ci_lower
        target_val = delta_vs_baseline if delta_vs_baseline is not None else metric_value

    if target_val is None:
        return None

    # Apply operator comparison
    op = cond.operator
    thr = cond.threshold

    if op == ">":
        return target_val > thr
    if op == ">=":
        return target_val >= thr
    if op == "<":
        return target_val < thr
    if op == "<=":
        return target_val <= thr
    if op == "==":
        return abs(target_val - thr) < 1e-9
    if op == "!=":
        return abs(target_val - thr) >= 1e-9

    return None
