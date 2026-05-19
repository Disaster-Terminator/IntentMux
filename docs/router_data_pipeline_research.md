# Dataset Pipeline v2

This is the execution baseline for `dataset-pipeline-v2`. It replaces the older
research-note shape: the goal is not to collect more references, but to define
the artifacts, scoring inputs, persistence, and rollout gates needed to improve
IntentMux routing quality without making the runtime heavy.

IntentMux is Chinese-first, not Chinese-only. Chinese route quality is the
product differentiator, while English datasets and mature router methodology
are required to keep the default two-tier router credible.

## Current Baseline

Runtime behavior is still lightweight:

1. `router.config.merge_route_bank()` loads YAML route-bank utterances into
   configured `lite` / `deep` routes.
2. The first embedding route request calls `Router._ensure_route_vectors()`.
3. Loaded route utterances are restored from the persistent route embedding
   cache when its manifest matches the route bank and embedding model.
4. On a cache miss, route utterances are embedded once, stored in process
   memory, and written back to the runtime cache.
5. Later requests embed only the incoming request and compare it with route
   vectors.

The runtime has a lightweight JSON cache, not a vector database, SQLite store,
FAISS index, Chroma, Qdrant, Milvus, or Postgres vector table. The cache lives
under the runtime home by default and is invalidated by route-bank fingerprint
or embedding-model changes.

Current generated local route bank is a bootstrap asset, not a quality
baseline. The tracked manifest now uses Simplified Chinese plus English by
default; Traditional Chinese is intentionally excluded from the default
baseline unless a user opts into it locally.

The pipeline has two separate scales:

- full ingest: authoritative upstream rows are normalized into ignored local
  records when `ingest_all: true`;
- online selection: `limit` caps how many records from each source enter
  route/eval/calibration outputs.

This keeps provenance-rich local assets broad without forcing every upstream
row into the runtime embedding index.

| route | source | count |
| --- | --- | ---: |
| `lite` | MASSIVE zh-CN train split, all scenarios | 80 online route examples |
| `lite` | MASSIVE en-US train split, all scenarios | 40 online route examples |
| `deep` | curated Simplified-Chinese debug/security/long-context seed | small |
| `deep` | SWE-bench issue resolution | 80 |
| `deep` | MBPP code generation | 40 |
| `deep` | HumanEval code generation | 40 |

MASSIVE dev/test splits are ingested separately as eval/calibration candidates
instead of being mixed into the online route bank.

This proves that the asset path works. It does not prove Chinese semantic
routing quality.

## Borrowed Principles

From Semantic Router:

- route examples are first-class assets;
- examples should be encoded into an index;
- thresholds should be fit or calibrated from labeled examples, not guessed.

From RouteLLM and routing benchmarks:

- keep the strong/weak, here `deep`/`lite`, cost-quality tradeoff explicit;
- judge router changes by quality and `deep` call rate together;
- compare every improvement against simple baselines;
- slice-level metrics matter because global accuracy hides failures.

These principles fit IntentMux. Heavy trained routers, large labeling
platforms, and vector databases are out of scope for the default runtime.

## Default Routing Standard

The default route decision should remain simple:

```text
explicit route
  -> high-precision hard escalation
  -> embedded route-bank similarity
  -> threshold and margin
  -> fallback to lite when confidence is low
```

The scoring mechanism should be evaluated as:

- accepted route: top route score passes threshold;
- ambiguous route: top score passes threshold but margin is too small;
- low-confidence route: no route passes threshold, fallback to `lite`;
- policy escalation: high-precision hard rule chooses `deep`;
- quality metric: expected route accuracy by slice;
- cost metric: `deep` call rate by slice;
- regression metric: change versus `always-lite`, `always-deep`, and
  `hard-rule-only`.

Do not make request structure, agent identity, local model group name, or
deployment cost bucket a product route label. Those are audit or deployment
signals. Product routes remain `lite` and `deep`.

## Artifact Contract

`dataset-pipeline-v2` must keep generated assets separated by role:

| artifact | input | output | git policy | required fields |
| --- | --- | --- | --- | --- |
| source manifest | tracked config | source declarations | tracked | `name`, `kind`, `license`, `language`, `intended_use`, `ingest_all`, `limit` |
| raw cache | public datasets | `data/downloads/*` | ignored | source name, source version, download hash |
| normalized records | raw cache | `data/semantic_sets/normalized/*.jsonl` | ignored | `id`, `text`, `source`, `license`, `language`, `slice`, `proposed_use` |
| route bank | normalized route records | `data/semantic_sets/route_bank.yaml` | ignored | `route_id`, `text`, `source`, `slice`, `language` |
| eval bank | held-out records and reviewed samples | `data/semantic_sets/eval_bank.yaml` | ignored | `id`, `text`, `expect`, `source`, `slice`, `language` |
| calibration bank | eval subset | `data/semantic_sets/calibration_bank.yaml` | ignored | `id`, `text`, `expect`, `slice`, `weight` |
| embedding cache | route bank | `.intentmux-home/cache/route-embeddings.json` or `$INTENTMUX_HOME/cache/route-embeddings.json` | ignored | embedding model, route-bank hash, text hash, source, index, vector |
| quality report | eval outputs and logs | `data/logs/quality/*` | ignored | baseline results, slice metrics, recommendation |

Tracked files should stay examples and contracts:

- `examples/*.sample.yaml`;
- `config/*sources*.yaml`;
- documentation of schemas and commands.

Generated local or production assets stay ignored unless a deliberate license
and redistribution decision promotes a small public example.

## Source Admission Matrix

Do not load every available dataset into the online route bank. Ingest
authoritative upstream data broadly into local normalized artifacts, then split
and cap by use.

The default baseline should be large enough to avoid a toy route bank while
remaining small enough for a lightweight sidecar without ANN/vector database
infrastructure. IntentMux therefore keeps the full normalized corpus as an
ignored local artifact and selects a bounded runtime route bank from it. Inspect
the current split with:

```bash
uv run python scripts/inspect_semantic_assets.py
```

Use this distinction in reports:

- `normalized corpus`: broad local source material, not scored per request.
- `runtime route bank`: selected utterances embedded and scored in the hot path.
- `eval/calibration bank`: held-out evidence, not route-bank seed material.
- `prompt/review logs`: local feedback evidence, not redistributable upstream
  corpus unless explicitly redacted and promoted.

| source family | default use | route bank | eval/calibration | notes |
| --- | --- | --- | --- | --- |
| Chinese general utterances | `lite` bootstrap | yes | limited | useful for short low-risk requests |
| English general utterances | `lite` coverage | yes | limited | keeps English default behavior from drifting |
| SWE-bench-like issues | `deep_debug_issue` | yes | yes | good for realistic debug intent |
| MBPP/HumanEval-like tasks | `deep_code_generation` | yes | yes | short code intent, not full agent work |
| LongBench | long-context stress | limited | yes | bilingual, useful for `deep_long_context` |
| C-Eval/CMMLU | Chinese reasoning evidence | no by default | yes after mapping | subject category is not a route label |
| RouterBench/LLMRouterBench | router methodology | no by default | offline experiments | useful for cost-quality evaluation design |
| redacted production review | regression and drift | after review | yes | local-first, privacy-gated |

Initial v2 scale target:

- online route bank: thousands, not tens of thousands;
- eval/calibration: larger than route bank and held out from route examples;
- raw cache: as large as license and local storage allow.

## Split Rules

Route-bank-derived eval cases are smoke evidence only. They prove that samples
are loaded and reachable; they do not prove general routing quality.

Quality eval and calibration cases should be held out from route-bank examples
unless the report explicitly labels the run as route-bank recall smoke. In the
source manifest this is expressed by `proposed_use`: only `route` records enter
the online route bank, `eval` records enter eval assets, and `calibration`
records enter calibration assets. Row-level `proposed_use` in curated YAML wins
over the source default so one audited file can contain separate route, eval,
and calibration candidates without mixing their generated outputs.

Production samples may enter generated assets only after:

1. selection from audit or prompt review logs;
2. AI review packet output;
3. human audit for subjective, risky, or privacy-sensitive cases;
4. rewrite into private-content-free representative prompts;
5. `redacted: true`;
6. validation against product route ids;
7. import into eval or route-bank assets before a route policy change.

## Embedding Cache v2

Persistent embedding cache is part of the runtime baseline before expanding
route-bank scale.

Initial backend: compact JSON with an embedded manifest. Avoid SQLite, Parquet,
FAISS, or vector databases until scale forces the choice.

Cache key:

```text
embedding_model + normalized_text_sha256
```

Manifest key:

```text
route_bank_sha256 + embedding_model + cache_schema_version
```

Invalidate and rebuild when route-bank content, utterance source, route-local
index, embedding model, or cache schema version changes.

Vector databases become reasonable only when route-bank size reaches tens of
thousands of examples, approximate nearest-neighbor search is needed, multiple
services share the same index, or online updates become a hard requirement.

## Implementation Order

Do not change production routing thresholds during this sequence.

1. Define source manifest and normalized record schema.
2. Build normalized candidates from allowed upstream data.
3. Split candidates into route, eval, and calibration assets.
4. Extend embedding cache metrics and optional offline prebuild command.
5. Extend quality reports with slice metrics and before/after comparison.
6. Use production logs and AI review packets to import redacted regression
   samples through a gate.

Rollout-ready changes must include:

- `current-router` eval;
- `always-lite` eval;
- `always-deep` eval;
- `hard-rule-only` eval;
- slice-level results;
- current-day or post-migration log summary;
- quality report recommendation;
- rollback note.

## Current Command

The first v2 builder is:

```bash
uv sync --group assets
uv run python scripts/build_semantic_assets.py
```

It reads `config/route_sources.yaml`, loads each allowed source, writes
normalized records, and then writes route/eval/calibration assets according to
each record's `proposed_use` and each source's selection `limit`. For
authoritative sources with `ingest_all: true`, normalized records are full local
ingest; generated route/eval/calibration YAMLs remain capped runtime artifacts.

Default outputs:

```text
data/semantic_sets/normalized/semantic_records.jsonl
data/semantic_sets/route_bank.yaml
data/semantic_sets/eval_bank.yaml
data/semantic_sets/calibration_bank.yaml
```

These files are local artifacts and stay ignored by git.

## Open Decisions

These decisions must be resolved by evidence or implementation constraints:

1. exact v2 source list and per-source limits;
2. per-route versus global threshold and margin calibration;
3. JSONL versus compact binary storage once cache size is measured;
4. rules for promoting local learning artifacts into public upstream examples.

The next milestone is not "more data". The next milestone is a reproducible
asset lifecycle where every route-quality change can be traced from source
records to generated artifacts, eval baselines, slice metrics, and rollout
decision.
