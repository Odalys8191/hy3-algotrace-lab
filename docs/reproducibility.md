# Reproducibility and formal-run protocol

## Immutable inputs

Use the Task 7 tooling to record external acquisition URL, byte length, SHA-256, split,
licence/attribution, converter identity, candidate/review decisions, quota report, and frozen
selection hash. Do not expand CodeContests validation/test data to train or synthetic rows.
The formal selection remains invalid until its full source and review linkage is verified.

Before any benchmark freeze the ordered sample IDs, corpus/selection hashes, model name,
credential-free endpoint identity, prompt version/hash, parameters, code revision, Judge
image digest, metric/chart versions, random seed, bootstrap replicates, and remote-call budget.
Reserve each outbound Hy3 attempt before sending it. Cache hits cost zero; a budget-exhausted
run is immutable partial evidence, not a complete formal result.

## Reporting

Persist only deterministic, create-only JSON artifacts and chart specifications. Do not
overwrite reports or replace screenshots after seeing metrics. Human review must export a
blinded public package; keep mapping, decisions, and replay artifacts separate and immutable.

The intended 30/60/15/60 formal corpus and 500-attempt benchmark ceiling are not completed on
this release branch. Do not state completion, publish aggregate metrics, or claim a stable
breakpoint until all gates—including source provenance, human checks, Judge evidence, and
natural-output materialization—have passed.

## Clean verification commands

```sh
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m hy3_algotrace.release_validation --root .
```

Use the task-specific dataset, benchmark, and Docker smoke commands only after the matching
modules and verified external inputs are present. Their absence must be reported as pending,
not bypassed with dummy data.
