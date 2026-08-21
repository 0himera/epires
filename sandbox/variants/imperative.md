# Imperative protocol — follow steps EXACTLY, no deviation

STEP 1: Read obs.suspects — these are auxiliary assumptions (tools, datasets, configs).
STEP 2: A single anomaly NEVER proves the hypothesis false. It only refutes the
conjunction <hypothesis AND assumptions>. You must decide WHO is guilty.
STEP 3: If ANY suspect exists, you MUST choose "attribute" and list ALL suspect ids.
Falsifying without recording assumption_ids is a protocol violation.
STEP 4: Choose "falsify" ONLY when suspects list is empty.

OUTPUT: one line of JSON, nothing else.
{"action": "attribute", "assumption_ids": ["<id1>", "<id2>"]}
or
{"action": "falsify"}
