"""Versioned structured prompts for Hy3 generation and review calls."""

from __future__ import annotations

GENERATOR_PROMPT_VERSION = "solution-trace-v1"
GENERATOR_SYSTEM_PROMPT = """\
You generate auditable C++17 algorithm-contest solutions. Return only JSON matching the
provided SolutionTrace schema. Number every reasoning step, state its dependencies, and
include problem understanding, algorithm, proof, complexity, edge cases, and code.
"""

SCHEMA_REPAIR_PROMPT = """\
Your previous response did not validate against the required JSON schema. Repair only its
format or schema violations. Return one complete JSON object and no surrounding prose.
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
