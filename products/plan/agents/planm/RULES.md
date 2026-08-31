# PLANM Rules

1. Check installed skills before acting and use the most specific matching skill.
2. Read and persist `planm-state.json` at every workflow boundary.
3. Accept only `skill-result/v1` stage results.
4. Never override geometry, egress, render, regulatory, or BIM hard gates.
5. Pass structured violations unchanged into bounded repair attempts.
6. Do not re-evaluate a repeated canonical candidate fingerprint.
7. Report missing regulatory facts as `needs_input` or `not_checked`.
8. Do not claim BIM or Revit completion without the required external verification.
9. Deliver only canonical artifacts with hashes and provenance.
10. Stop when the configured attempt or turn limit is exhausted.
