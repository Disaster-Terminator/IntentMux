# Chinese Route Eval Plan

IntentMux does not try to become a general API gateway or a large router
platform. The next quality milestone is a Chinese-first fast/strong routing
eval bank.

## Principle

- Chinese-native data is the primary benchmark source.
- English router benchmarks are methodology references.
- Translated English samples are at most a small supplement.
- Full generated eval banks are deployment assets unless curated for public
  release.

## Slices

| slice | expected route | source family |
| --- | --- | --- |
| fast_general_zh | fast | MASSIVE zh, CLUE/DataCLUE general text |
| fast_intent_zh | fast | DataCLUE CIC-like intent data |
| strong_code_zh | strong | SuperCLUE-Code3, HumanEval-X/XL supplement |
| strong_reasoning_zh | strong | C-Eval, CMMLU, AGIEval/Gaokao-like data |
| strong_long_context_zh | strong | LongBench Chinese |
| high_risk_zh | strong | curated public/manual and redacted production review |
| borderline_zh | reviewed fast or strong | curated Chinese engineering boundary prompts |

## Metrics

- strong_recall_high_risk
- strong_recall_code
- fast_general_keep_rate
- fast_precision
- low_confidence_rate
- near_margin_rate
- hard_rule_hit_rate
- strong_call_rate
