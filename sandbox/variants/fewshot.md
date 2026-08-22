# Worked examples — imitate the pattern

Example A:
obs: {"kind":"anomaly","hypothesis":"H1","finding":"prediction violated","suspects":["AUX_SENSOR_CAL"]}
correct: {"action":"attribute","assumption_ids":["AUX_SENSOR_CAL"]}
why: unverified sensor calibration is a cheaper explanation than killing the hypothesis.

Example B:
obs: {"kind":"anomaly","hypothesis":"H7","suspects":[]}
correct: {"action":"falsify"}
why: no auxiliary left to blame — the hypothesis itself takes the hit.

Example C:
obs: {"kind":"anomaly","hypothesis":"H2","suspects":["DATASET_V2","AUX_TOOL_X"]}
correct: {"action":"attribute","assumption_ids":["DATASET_V2","AUX_TOOL_X"]}
why: list ALL suspects, never drop one.

NOW your turn. Output ONLY the JSON line.
