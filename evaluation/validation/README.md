# Validity validation status

Localization accuracy and false-positive rate require human-confirmed labels for the evaluator's
predictions. Those labels do not currently exist. The 30-problem checker/topic review is a
different task and cannot be reused as outcome validation.

[`status.json`](status.json) therefore records null values with denominator zero. This is an
explicit not-evaluable result, not a zero score. No Agent, test fixture, or existing corpus label
has been presented as a human outcome decision.

A valid next run must:

1. export a blind sample without expected labels;
2. collect a human decision for final correctness, process validity, first material error and
   taxonomy;
3. sample a deterministic 20% subset for delayed blind re-review;
4. replay the decisions against immutable sample IDs and hashes;
5. compute exact/within-one localization and flagged false-positive rate with literal
   numerators and denominators.

[`manual-audit-template.csv`](manual-audit-template.csv) supplies the required fields. It has no
data rows because no review was performed for this release.
