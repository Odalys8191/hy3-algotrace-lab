# Audit record template (draft; not a completed review)

| Field | Required value |
| --- | --- |
| Audit ID/time | Create-only ID, UTC timestamp, artifact hash |
| Scope | Exact run/configuration hashes and public/blind package hashes |
| Reviewer | Pseudonymous reviewer ID; no model/API credentials |
| Blinding | Evidence withheld, mapping artifact ID, and replay command/version |
| Decision | Pass/fail/needs-rework with first material issue only |
| Delayed re-review | 20% blind sample seed, due date, independent result, disagreement resolution |
| Contamination | Historical exposure, same-model involvement, or single-reviewer limitation |
| Replay | Read-only input hashes and resulting output hashes |

Protected internal dataset artifacts may exist under access control for Judge and provenance
replay. They must never be copied into a model prompt, public/UI response, or run artifact.
