# Method report template (draft; not a completed result)

Use one immutable, dated copy per benchmark configuration. Fill no field after seeing
aggregate results without creating a replacement report that names the earlier artifact.

| Field | Required value |
| --- | --- |
| Run/configuration ID | Create-only identifier and SHA-256 |
| Source/data linkage | Acquisition, conversion, selection, bundle, corpus, and Judge-evidence hashes |
| Model boundary | `HY3_MODEL`, credential-free endpoint identity, prompt/version hashes, parameters |
| Judge boundary | Immutable Judge image reference and sandbox settings |
| Budget | Reserved, sent, cached, failed, and remaining calls; hard ceiling 500 |
| Metrics | Exact metric version, numerator/denominator, bootstrap seed/replicates |
| Review | Blind export ID, reviewer assignment, 20% delayed re-review sample/seed |
| Exceptions | Gate failures, retries, exclusions, and why the output is not formal if applicable |

This template is not evidence that the planned 30-problem or 165-sample evaluation has run.
