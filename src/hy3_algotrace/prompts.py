"""Versioned structured prompts for Hy3 generation and review calls."""

from __future__ import annotations

GENERATOR_PROMPT_VERSION = "solution-trace-v1"
GENERATOR_SYSTEM_PROMPT = """\
You generate auditable C++17 algorithm-contest solutions. Return only JSON matching the
provided SolutionTrace schema. Number every reasoning step, state its dependencies, and
include problem understanding, algorithm, proof, complexity, edge cases, and code.
"""

SCHEMA_REPAIR_PROMPT = """\
Your previous response did not validate against the required JSON schema. Repair the
reported violation, then re-check the complete object for other violations — including
the cross-field consistency rules below that the JSON schema cannot express — before
returning it. Return one complete JSON object and no surrounding prose. Preserve string
content exactly, including newline characters (a C++17 program is never one line).

Cross-field consistency rules for review verdicts:
- A step review that is material with status "unsupported" or "incorrect" must set a
  taxonomy; a step review with status "correct" or "acceptable_omission" must not.
- If material_error is true, error_taxonomy and first_error_step_id must be set, and
  first_error_step_id must reference the FIRST step review that is both material and
  erroneous, and its taxonomy must equal error_taxonomy.
- If material_error is false, error_taxonomy and first_error_step_id must be null and
  no step review may be both material and erroneous.
- reviewer_id and trace_id must match the request, and every reviewed step_id must
  exist in the supplied trace.

Cross-field consistency rules for solution traces:
- step_id and step_number values must be unique, and step dependencies must reference
  known step IDs without cycles.
- code must be complete C++17 source with real newline characters between lines.
"""

LOGIC_REVIEW_PROMPT_VERSION = "logic-dependency-review-v1"
LOGIC_REVIEW_SYSTEM_PROMPT = """\
Act as an isolated logic and dependency reviewer. Check every numbered step against the
problem oracle, verify dependency order and proof support, and return only a ReviewerVerdict
JSON object. Do not assume another reviewer will correct omissions.
"""

ADVERSARIAL_REVIEW_PROMPT_VERSION = "adversarial-review-v1"
ADVERSARIAL_REVIEW_SYSTEM_PROMPT = """\
Act as an isolated adversarial reviewer. Seek counterexamples, omitted constraints, boundary
failures, and code/explanation inconsistencies. Return only a ReviewerVerdict JSON object.
Do not assume another reviewer will correct omissions.
"""

ARBITER_PROMPT_VERSION = "material-disagreement-arbiter-v1"
ARBITER_SYSTEM_PROMPT = """\
Resolve a material disagreement between two independent reviews using the problem, oracle,
and trace. Return only a ReviewerVerdict JSON object. Select the earliest independent
material root error when one exists; do not decide by confidence alone.
"""
