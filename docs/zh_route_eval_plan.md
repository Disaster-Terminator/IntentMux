# Chinese Route Eval Plan

IntentMux does not try to become a general API gateway or a large router
platform. The next quality milestone is a Chinese-first lite/deep routing
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
| fast_general_zh | lite | MASSIVE zh, CLUE/DataCLUE general text |
| fast_intent_zh | lite | DataCLUE CIC-like intent data |
| strong_code_zh | deep | SuperCLUE-Code3, HumanEval-X/XL supplement |
| strong_reasoning_zh | deep | C-Eval, CMMLU, AGIEval/Gaokao-like data |
| strong_long_context_zh | deep | LongBench Chinese |
| high_risk_zh | deep | curated public/manual and redacted production review |
| borderline_zh | reviewed lite or deep | curated Chinese engineering boundary prompts |

## Metrics

- strong_recall_high_risk
- strong_recall_code
- fast_general_keep_rate
- fast_precision
- low_confidence_rate
- near_margin_rate
- hard_rule_hit_rate
- strong_call_rate
