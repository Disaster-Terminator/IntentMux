# Router Data Pipeline Research

This document records the current research baseline for improving IntentMux
routing quality without losing the project's lightweight local-first shape.

## Current Reality

IntentMux currently stores semantic assets as YAML:

- tracked examples:
  - `examples/route_bank.sample.yaml`
  - `examples/eval_bank.sample.yaml`
- generated local or production assets, ignored by git:
  - `data/semantic_sets/route_bank.yaml`
  - `data/semantic_sets/eval_bank.yaml`
  - runtime-mounted `/data/semantic_sets/route_bank.yaml`

Runtime behavior is simple:

1. `router.config.merge_route_bank()` loads YAML route-bank utterances into the
   configured `lite` / `deep` routes.
2. The first embedding route request calls `Router._ensure_route_vectors()`.
3. `_ensure_route_vectors()` embeds all loaded route utterances once and stores
   vectors in process memory.
4. Later requests embed only the incoming request text and compare it with the
   in-memory route vectors.

There is no persistent embedding cache, vector database, SQLite store, FAISS
index, Chroma, Qdrant, Milvus, or Postgres vector table. A process restart
re-embeds the route bank.

Current authoritative local route bank size is 280 examples:

| route | source | count |
| --- | --- | ---: |
| lite | MASSIVE zh-CN general | 80 |
| lite | MASSIVE zh-TW general | 40 |
| deep | SWE-bench issue resolution | 80 |
| deep | MBPP code generation | 40 |
| deep | HumanEval code generation | 40 |

This is a useful bootstrap, but it is not a serious quality baseline.

## User Direction

The desired product shape is:

- Chinese-first routing quality;
- learnable from real usage;
- lightweight deployment and runtime;
- rigorous enough that route quality is not sacrificed.

The important distinction is:

```text
lightweight runtime != toy dataset
```

IntentMux should not become a large training platform, but it does need a real
data pipeline: upstream dataset ingestion, persisted derived artifacts,
repeatable evals, slice metrics, and route-change gates.

## Mature Project Lessons

### Semantic Router

Semantic Router's useful pattern is route examples plus encoders plus an index.
Routes are defined by example utterances, encoded into vectors, and selected by
similarity over an index. It also treats thresholds as something to fit and
evaluate rather than guess manually.

Lessons to borrow:

- route examples are a first-class asset;
- route vectors are an index, not just loose strings;
- threshold optimization needs labeled examples;
- in-memory indexes are acceptable at small scale;
- vector DBs are a scale option, not a default requirement.

Relevant references:

- https://docs.aurelio.ai/semantic-router/user-guide/concepts/architecture
- https://docs.aurelio.ai/semantic-router/user-guide/features/threshold-optimization

### RouteLLM

RouteLLM frames routing as a strong/weak model-pair cost-quality decision. It
supports calibration by target strong-model call rate and evaluates routers
against benchmarks. Its trained routers and preference-data pipeline are heavier
than IntentMux should adopt now, but the evaluation discipline is directly
relevant.

Lessons to borrow:

- keep two-tier model semantics explicit;
- measure `deep` call rate against quality;
- calibrate thresholds from representative queries;
- compare against simple baselines before claiming improvement.

Relevant references:

- https://github.com/lm-sys/RouteLLM
- https://arxiv.org/abs/2406.18665

### RouterBench, LLMRouterBench, RouterEval

Router benchmark projects make the same point at larger scale: router quality
needs structured evaluation data, repeated model outcomes, cost metrics, and
baseline comparisons. They are not a direct runtime dependency for IntentMux,
but they define what "not a toy" means.

Relevant reported scales:

- RouterBench: over 405k inference outcomes for multi-LLM routing evaluation.
- LLMRouterBench: over 400k instances from 21 datasets and 33 models, plus
  performance and performance-cost metrics.
- RouterEval: over 200M performance records across many LLM evaluations.

Lessons to borrow:

- route quality should be judged by baseline comparisons, not only pass/fail
  smoke tests;
- cost-quality tradeoff metrics are core, not optional;
- a simple baseline can be hard to beat, so reports must include
  `always-lite`, `always-deep`, and rule-only baselines;
- dataset slices matter because global accuracy hides bad routing behavior.

Relevant references:

- https://arxiv.org/abs/2403.12031
- https://github.com/withmartian/routerbench
- https://arxiv.org/abs/2601.07206
- https://github.com/ynulihao/LLMRouterBench
- https://arxiv.org/abs/2503.10657
- https://github.com/MilkThink-Lab/RouterEval

## Gap Analysis

Current IntentMux is strong enough as a protocol sidecar, but weak as a data
pipeline.

Implemented:

- route-bank YAML with source metadata;
- generated local route bank and eval bank;
- metadata audit logs;
- review candidate selection;
- AI review packet generation and summary validation;
- quality reports with route distribution and baseline eval outputs;
- match provenance for embedding decisions.

Missing or incomplete:

- persistent embedding cache keyed by route-bank content and embedding model;
- source manifest with artifact hashes and build provenance for every generated
  semantic asset;
- larger Chinese-first route/eval corpora;
- slice metadata for all eval cases;
- threshold and margin calibration workflow;
- clear separation between route-bank examples, eval cases, calibration cases,
  and production review samples;
- data pipeline commands that can refresh artifacts reproducibly;
- CI or local gate that compares v1 and v2 route banks before rollout.

## Data Pipeline Direction

The next design should introduce a pipeline with explicit artifact layers:

```text
source manifests
  -> raw dataset cache
  -> normalized candidate records
  -> route bank
  -> eval/calibration bank
  -> embedding cache / route-vector index
  -> quality report
  -> rollout gate
```

Recommended artifact boundaries:

| artifact | purpose | git policy |
| --- | --- | --- |
| `examples/*.sample.yaml` | public shape and smoke examples | tracked |
| `config/*sources*.yaml` | source declarations and policy | tracked |
| `data/downloads/` | raw upstream cache | ignored |
| `data/semantic_sets/*.yaml` | generated route/eval/calibration assets | ignored by default |
| `/data/cache/route_embeddings.*` | persistent local embedding cache | ignored |
| `/data/logs/quality/` | daily quality outputs | ignored |
| curated redacted examples | public examples only | tracked case by case |

Recommended slices for the next baseline:

- `lite_general_zh`
- `lite_short_task_zh`
- `lite_translation_summary`
- `deep_code_generation`
- `deep_debug_issue`
- `deep_security_risk`
- `deep_long_context_zh`
- `borderline_code_light`
- `agent_workflow`

The first serious baseline should target thousands of records, not hundreds,
but should stay generated-local by default. The public repository should not
commit the full generated dataset unless a license and distribution decision is
made deliberately.

## Candidate Source Expansion

The next source expansion should separate route-bank data from eval/calibration
data.

Good route-bank candidates:

- MASSIVE zh-CN / zh-TW assistant utterances for `lite` general and short-task
  slices.
- SWE-bench, MBPP, HumanEval, and similar coding tasks for `deep_code` and
  `deep_debug_issue` slices.
- Curated, redacted production review samples after AI review and human audit
  when needed.

Potential eval/calibration candidates:

- C-Eval: Chinese multi-level, multi-discipline questions. Useful for Chinese
  reasoning and knowledge slices, but subject categories are not automatically
  `deep`; mapping must be reviewed.
- CMMLU: Chinese multitask understanding. Useful for measuring Chinese
  knowledge and reasoning difficulty; not all categories should become route
  examples.
- LongBench: bilingual long-context benchmark with Chinese tasks. Useful for
  `deep_long_context_zh`, context-length stress tests, and calibration.
- CS-Eval or similar cybersecurity benchmarks: possible source for
  `deep_security_risk`, but non-commercial or share-alike licenses may restrict
  redistribution.
- RouterBench, LLMRouterBench, RouterEval: methodology and metric references
  first. Their model-output tables may be useful for offline experiments, but
  they should not be mixed into the default route bank without a specific
  mapping decision.

Do not treat benchmark category names as route labels by default. A benchmark
can be excellent eval evidence while being a poor route-bank source.

References:

- C-Eval: https://github.com/hkust-nlp/ceval
- CMMLU: https://github.com/haonan-li/CMMLU
- LongBench: https://arxiv.org/abs/2308.14508
- LongBench repository: https://github.com/THUDM/LongBench
- CS-Eval: https://github.com/CS-EVAL/CS-Eval

## Persistence Strategy

Do not add a vector database first.

Prometheus is not a semantic asset store. The local `litellm_prometheus`
container is useful for metrics such as latency, request counts, error rate,
token usage, and possibly route distribution. It should not store route banks,
eval sets, embedding vectors, or nearest-neighbor indexes. Prometheus TSDB is a
time-series metrics database, not a vector search system.

For the current product shape, the first persistence layer should be a local
embedding cache:

```text
cache key = embedding_model + normalized_text_sha256
manifest key = route_bank_sha256 + embedding_model + builder_version
```

Suggested storage:

- JSONL for inspectability, or NPZ/Parquet if vector size becomes a bottleneck;
- stored under runtime `/data/cache/`;
- never tracked by git;
- invalidated when route-bank content, embedding model, or embedding dimensions
  change.

This keeps runtime lightweight while avoiding repeated route-bank embedding
after restarts.

Vector DBs become reasonable only if:

- route-bank size grows to tens of thousands of examples;
- approximate nearest neighbor search is needed;
- multiple services share the same index;
- online updates/hot reload become a hard requirement.

Mature projects use vector databases as a scale option, not as the first step.
Semantic Router supports local indexes and remote indexes such as Qdrant or
Pinecone. That maps well to IntentMux: keep local cache/index as the default,
and only introduce FAISS, Qdrant, pgvector, or a similar index when scale or
sharing requirements justify the dependency.

## Open Questions

These need more research before implementation:

1. Which Chinese datasets can be mapped to `lite` / `deep` without subjective
   labels?
2. Which datasets are suitable for route-bank examples, and which should remain
   eval-only?
3. How large should v2 be before embedding cache becomes mandatory?
4. Should threshold calibration use a global threshold/margin or per-route
   thresholds?
5. How should local learning artifacts be filtered before they are eligible for
   upstream contribution?
6. Which storage format is best for a lightweight embedding cache in Python:
   JSONL, SQLite, NPZ, or Parquet?

## Current Recommendation

Treat the current 280-example route bank as `bootstrap-v1`.

The next major quality milestone should be `dataset-pipeline-v2`:

- expand upstream sources and slices;
- generate local route/eval/calibration assets reproducibly;
- add persistent embedding cache;
- add slice-aware quality reports and before/after comparison;
- do not change production routing thresholds until reports show an actionable
  improvement.

This keeps IntentMux aligned with mature router projects while preserving its
own niche: Chinese-first, learnable, auditable, and lightweight to deploy.
