"""Epistemic Synthesis Report generator for Epires Research Graphs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List
from .models import HypothesisStatus
from .audit import posiwid_report
from .algedonic import check_triggers


def generate_synthesis_report(store: Any, project_name: str = "Research Project") -> str:
    """Generates a structured Markdown Epistemic Synthesis Report for the project."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    hyps = store.list_hypotheses() if hasattr(store, "list_hypotheses") else []
    evidence = store.list_evidence() if hasattr(store, "list_evidence") else []
    relations = store.list_relations() if hasattr(store, "list_relations") else []

    posiwid = posiwid_report(store)
    algedonic_alerts = check_triggers(store)

    confirmed_core: List[Any] = []
    in_progress: List[Any] = []
    falsified: List[Any] = []
    blocked: List[Any] = []
    proposed: List[Any] = []

    for h in hyps:
        st = getattr(getattr(h, "status", ""), "value", str(getattr(h, "status", "")))
        if st == HypothesisStatus.CONFIRMED.value:
            confirmed_core.append(h)
        elif st == HypothesisStatus.FALSIFIED.value:
            falsified.append(h)
        elif st == HypothesisStatus.BLOCKED.value:
            blocked.append(h)
        elif st == HypothesisStatus.IN_PROGRESS.value:
            in_progress.append(h)
        else:
            proposed.append(h)

    lines: List[str] = []
    lines.append(f"# Epistemic Synthesis Report — {project_name}")
    lines.append(
        f"\n> **Generated**: `{now_iso}` | **Total Hypotheses**: `{len(hyps)}` | **Evidence**: `{len(evidence)}` | **Relations**: `{len(relations)}`\n"
    )

    # 1. Executive Metrics & POSIWID
    lines.append("## 1. Executive Summary & POSIWID Integrity")
    lines.append("")
    integrity_gap_pct = posiwid.get("integrity_gap", 0.0) * 100.0
    lines.append(f"- **POSIWID Integrity Gap**: `{integrity_gap_pct:.1f}%` (violated confirmed / total confirmed)")
    lines.append(f"- **Confirmed (Lakatos Core)**: `{len(confirmed_core)}`")
    lines.append(f"- **Falsified (Popperian Filter)**: `{len(falsified)}`")
    lines.append(f"- **Blocked (Cascaded Invalidation)**: `{len(blocked)}`")
    lines.append(f"- **Active In-Progress**: `{len(in_progress)}`")
    lines.append(f"- **Proposed**: `{len(proposed)}`")
    lines.append("")

    # Status Distribution Table
    lines.append("| Status | Count | Share |")
    lines.append("|---|---|---|")
    for st, count in sorted(posiwid.get("status_distribution", {}).items(), key=lambda x: -x[1]):
        share = (count / len(hyps) * 100.0) if hyps else 0.0
        lines.append(f"| **{st}** | {count} | {share:.1f}% |")
    lines.append("")

    # 2. Algedonic Alerts
    lines.append("## 2. Active Algedonic Alerts & Pain Signals")
    if not algedonic_alerts:
        lines.append("\n🟢 *No active algedonic alerts detected. Graph operates in stable regime.*")
    else:
        lines.append("\n| Severity | Trigger | Node / Target |")
        lines.append("|---|---|---|")
        for alert in algedonic_alerts:
            sev_icon = (
                "🔴" if alert.get("severity") == "critical" else "🟠" if alert.get("severity") == "high" else "🟡"
            )
            lines.append(
                f"| {sev_icon} {alert.get('severity', '').upper()} | `{alert.get('trigger')}` | `{alert.get('node_id')}` |"
            )
    lines.append("")

    # 3. Lakatos Hard Core (Confirmed Hypotheses)
    lines.append("## 3. Lakatos Hard Core (Confirmed Knowledge)")
    if not confirmed_core:
        lines.append("\n*No hypotheses confirmed at this time.*")
    else:
        for h in confirmed_core:
            hid = getattr(h, "id", "")
            title = getattr(h, "title", "")
            lvl = getattr(
                getattr(h, "current_evidence_level", ""), "value", str(getattr(h, "current_evidence_level", ""))
            )
            crit = getattr(h, "falsification_criteria", "")
            h_evs = store.get_evidence_for_hypothesis(hid) if hasattr(store, "get_evidence_for_hypothesis") else []
            lines.append(f"\n### 🟢 `[{hid}]` {title}")
            lines.append(f"- **Level**: `{lvl}` | **Evidence Claims**: `{len(h_evs)}`")
            lines.append(f"- **Mechanism**: {getattr(h, 'a_priori_mechanism', '')}")
            lines.append(f"- **Falsification Boundary**: `{crit}`")
            if h_evs:
                lines.append("- **Supporting Evidence**:")
                for e in h_evs:
                    if not getattr(e, "falsification_triggered", False):
                        ci_str = (
                            f" (CI95: [{e.ci_95_lower}, {e.ci_95_upper}])"
                            if getattr(e, "ci_95_lower", None) is not None
                            else ""
                        )
                        lines.append(f"  - `[{e.evidence_level.value}]` {e.claim}{ci_str}")
    lines.append("")

    # 4. Duhem-Quine Falsifications & Anomalies
    lines.append("## 4. Duhem-Quine Falsifications & Search Space Pruning")
    refuted_or_anomalous = [
        h
        for h in hyps
        if getattr(getattr(h, "status", ""), "value", str(getattr(h, "status", "")))
        in (HypothesisStatus.FALSIFIED.value, HypothesisStatus.BLOCKED.value)
        or any(
            getattr(e, "falsification_triggered", False)
            for e in (
                store.get_evidence_for_hypothesis(getattr(h, "id", ""))
                if hasattr(store, "get_evidence_for_hypothesis")
                else []
            )
        )
    ]

    if not refuted_or_anomalous:
        lines.append("\n*No hypotheses falsified or blocked by anomalies yet.*")
    else:
        for h in refuted_or_anomalous:
            hid = getattr(h, "id", "")
            title = getattr(h, "title", "")
            st = getattr(getattr(h, "status", ""), "value", str(getattr(h, "status", "")))
            icon = "🔴" if st == "FALSIFIED" else "⚫"
            crit = getattr(h, "falsification_criteria", "")
            h_evs = store.get_evidence_for_hypothesis(hid) if hasattr(store, "get_evidence_for_hypothesis") else []
            lines.append(f"\n### {icon} `[{hid}]` {title} (Status: `{st}`)")
            if crit:
                lines.append(f"- **Falsification Boundary**: `{crit}`")
            fals_evs = [e for e in h_evs if getattr(e, "falsification_triggered", False)]
            if fals_evs:
                lines.append("- **Refutation Evidence & Suspect Assumptions**:")
                for e in fals_evs:
                    aids = getattr(e, "assumption_ids", []) or []
                    aux_str = f" *(Suspects: `{', '.join(aids)}`)*" if aids else ""
                    lines.append(f"  - {e.claim}{aux_str}")
    lines.append("")

    # 5. Cascaded Blocked Subtrees
    if blocked:
        lines.append("## 5. Cascaded Blocked Subtrees")
        for h in blocked:
            hid = getattr(h, "id", "")
            parents = getattr(h, "parent_ids", []) or []
            p_str = f" (depends on `{', '.join(parents)}`)" if parents else ""
            lines.append(f"- ⚫ `[{hid}]` {getattr(h, 'title', '')}{p_str}")
        lines.append("")

    return "\n".join(lines)
