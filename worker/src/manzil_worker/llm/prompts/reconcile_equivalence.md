---
id: reconcile_equivalence
version: 2
---
You normalize already-extracted rental facts for deterministic reconciliation.

Return every supplied item_id exactly once. Compare claims only within the same
target_key. Give two claims the same equivalence_key only when their values have
the same ordinary meaning in that Criterion context (for example, "W/D in unit"
and "in-unit laundry"). Do not choose a winner, change numeric values, infer
applicability, or infer that Floor Plans from different Sources are the same.
When uncertain, use distinct keys.
