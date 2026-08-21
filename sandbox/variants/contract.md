# Decision contract

INPUT: obs with fields kind, hypothesis, finding, suspects.
DECISION TABLE:
| suspects non-empty | -> {"action":"attribute","assumption_ids":[<ALL suspects verbatim>]} |
| suspects empty     | -> {"action":"falsify"} |

HARD CONSTRAINTS:
- Copy suspect ids VERBATIM into assumption_ids.
- Output MUST be a single JSON object. No prose, no markdown, no explanations.
- Choosing "falsify" while suspects exist = contract breach.
