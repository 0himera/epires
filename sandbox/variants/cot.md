# Reasoning before verdict

Think through three questions IN ORDER before answering:
Q1: What exactly did the anomaly refute? (Remember: an observation refutes the
whole bundle <hypothesis + auxiliary assumptions>, never the hypothesis alone.)
Q2: Which auxiliary assumption is LEAST independently verified so far?
That one is the prime suspect — blame falls where prior support is weakest.
Q3: Is there at least one plausible suspect? If yes, attribute; do not kill the hypothesis yet.

After answering Q1-Q3 to yourself, OUTPUT ONLY:
{"action": "attribute", "assumption_ids": [...]}   (if any suspect exists)
{"action": "falsify"}                              (only if none)
