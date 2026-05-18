# Chinese Route Eval Plan Status

This historical note has been superseded.

Use the current dataset-pipeline execution baseline instead:

```text
docs/router_data_pipeline_research.md
```

Older versions of this note assumed Chinese benchmark categories could become
route labels more directly. Current policy is stricter: benchmarks such as
C-Eval, CMMLU, LongBench, DataCLUE, and SuperCLUE-Code3 are eval/calibration
candidates unless a `lite` / `deep` mapping is natural, auditable, and
reviewable.
