# Skill: epistemic_verdict — research decision protocol

Decide verdicts for research observations. Apply this protocol to every task.

## Iron Laws
1. An observation NEVER refutes a hypothesis alone. It refutes the bundle
   <hypothesis + auxiliary assumptions> (tools, datasets, configs, seeds).
2. Never confirm on the number that looks best. Check WHICH metric is primary
   and WHERE it was measured (train vs holdout, 1 seed vs many).
3. When configs differ in more than one dimension, the cause of any delta is
   UNKNOWN until confounds are controlled. Do not attribute to architecture.
4. A claim built by selecting the best of N trials (post-hoc) carries selection
   bias: downgrade it; do not accept at face value.
5. If an experiment's baseline was not rerun or its code has fixed parameters,
   its "confirmation" is vacuous: treat as invalid evidence.
6. Early support does not survive a later anomaly unexamined: revise prior
   verdicts when new evidence contradicts them.
7. Do not fabricate. If information needed for a decision is absent, choose
   the conservative action.

## Decision table (apply in order)

| Observation kind | Condition | Action |
|---|---|---|
| anomaly | suspects non-empty | {"action":"attribute","assumption_ids":[ALL suspects verbatim]} |
| anomaly | suspects empty | {"action":"falsify"} |
| result | primary metric regressed | {"action":"falsify"} — ignore secondary metrics that improved |
| result | train score high, holdout low | {"action":"falsify"} — leakage suspected |
| result | n_seeds=1 or delta within stated noise | {"action":"attribute","assumption_ids":["AUX_EVAL_NOISE"]} or {"action":"verify_level"} |
| result | configs_differ has >1 item | {"action":"attribute","assumption_ids":[<the NON-architecture difference>]} |
| result | delta large, single config pair | {"action":"verify_level"} before claiming |
| claim | trials_available > 1 mentioned | {"action":"verify_level"} — selection bias check |
| supporting_result | modest effect | {"action":"claim","level":"E2"} — never above E2 on one run |
| conflict | two opposing results | {"action":"discuss"} — confirm neither side |

## Output contract
Return ONE JSON object, nothing else:
{"action":"<attribute|falsify|claim|verify_level|confirm|discuss>", "assumption_ids":[...], "level":"E<n>"}
Include assumption_ids only for attribute. Include level only for claim.


{"kind": "result", "finding": "e-fold outperforms k-fold", "experiment_id": "X1", "baseline_rerun": false}