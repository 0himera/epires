# Adversarial self-check — assume YOUR first instinct is wrong

Known bias: agents rush to falsify hypotheses because it looks decisive.
Reality: instruments, datasets and configs break far more often than theories.
The CHEAP explanation is almost always the true one.

Before answering ask yourself: "Am about to destroy months of downstream work
(H2, H3 depend on this!) just to look decisive? Did I even CHECK the suspect?"

If obs.suspects is non-empty, the only defensible answer is to attribute.

OUTPUT: single JSON line
{"action": "attribute", "assumption_ids": [...]}  or  {"action": "falsify"}
