# LLM layer evaluation

## Run

| | |
|---|---|
| date | 2026-10-10 20:35 UTC |
| host | cachyos-x8664 |
| platform | Linux-7.2.9-2-cachyos-x86_64-with-glibc2.44 |
| commit | 8c1447a |
| contract | 1.1.0 |
| llm | ollama:qwen2.5:7b-instruct-q4_K_M |
| budget_s | 25.0 |
| engine models | real |

## Summary vs targets (README P4.6)

| Metric | Value | Target |
|---|---|---|
| Numeric groundedness, raw LLM first attempt (before checker) | 84.3% | — |
| Numeric groundedness, answer shown (after checker) | 100.0% | ≥ 90% |
| Numeric accuracy (numbers in shown answers that match a fact) | 100.0% | ≥ 90% |
| `must_mention` satisfied | 63.5% | ≥ 90% |
| `must_not` violations | 1 | 0 |
| Intent accuracy (chat) | 100.0% | — |
| Scenario accuracy (what-if) | 100.0% | — |
| What-if parse, rules only | 46/50 | — |
| What-if parse, rules + LLM | 44/50 (LLM used 6) | — |
| Latency per answer, median / p95 | 3.34 s / 12.88 s | ≤ 25 s |
| Output tokens per LLM answer (mean) | 151.47 | — |
| Cost | £0 (local model) | — |
| Unsupported claim rate (human annotation) | see `reports/llm_annotation.md` | < 5% |

Answers by source: None: 64, failed_check: 5, llm_error: 10, template: 1 (`None` = LLM answer shown).

## By category

| Category | n | Shown answer passes | Raw first attempt passes | must_mention | Violations |
|---|---|---|---|---|---|
| normal | 20 | 100.0% | 88.2% | 100.0% | 0 |
| missing_data | 10 | 100.0% | 100.0% | 40.0% | 0 |
| conflict | 10 | 100.0% | 88.9% | 50.0% | 0 |
| infeasible | 10 | 100.0% | 100.0% | 40.0% | 1 |
| heat_pump | 10 | 100.0% | 62.5% | 81.8% | 0 |
| insufficient | 8 | 100.0% | 71.4% | 75.0% | 0 |
| multi_turn | 8 | 100.0% | 57.1% | 50.0% | 0 |
| adversarial | 4 | 100.0% | 100.0% | 100.0% | 0 |

## What the checker caught (raw first attempts that failed)

- **S08** (normal): unsupported ['£1,500'], banned [] → shown: failed_check
- **S18** (normal): unsupported ['72.5%'], banned [] → shown: failed_check
- **S31** (conflict): unsupported ['69'], banned [] → shown: llm_error
- **S53** (heat_pump): unsupported ['3,990 kWh (direction)'], banned [] → shown: failed_check
- **S58** (heat_pump): unsupported ['2,460 kWh (direction)'], banned [] → shown: retry
- **S60** (heat_pump): unsupported ['3,990 kWh (direction)'], banned [] → shown: retry
- **S66** (insufficient): unsupported ['200 kWh', '0.5 tonne'], banned [] → shown: failed_check
- **S68** (insufficient): unsupported ['45', '65'], banned [] → shown: failed_check
- **S69** (multi_turn): unsupported ['3,990 kWh (direction)'], banned [] → shown: retry
- **S71** (multi_turn): unsupported ['1,560 kWh (direction)'], banned [] → shown: retry

## Misses

- **S21** (missing_data) `[explain savings]`: intent None (ok=None), scenario ok=None, missing ['LOW_COVERAGE'], violations []
- **S23** (missing_data) `[explain score]`: intent None (ok=None), scenario ok=None, missing ['ESTIMATED_ANSWERS'], violations []
- **S24** (missing_data) `Why is my score what it is?`: intent explain (ok=True), scenario ok=None, missing ['ESTIMATED_ANSWERS'], violations []
- **S25** (missing_data) `[explain score]`: intent None (ok=None), scenario ok=None, missing ['ESTIMATED_ANSWERS'], violations []
- **S27** (missing_data) `[explain savings]`: intent None (ok=None), scenario ok=None, missing ['TYPICAL_HOMES'], violations []
- **S28** (missing_data) `Where did my energy use come from?`: intent explain (ok=True), scenario ok=None, missing ['TYPICAL_HOMES'], violations []
- **S32** (conflict) `Why is my rating so low when we use so little energy?`: intent explain (ok=True), scenario ok=None, missing ['RATING_VS_USAGE'], violations []
- **S33** (conflict) `[explain score]`: intent None (ok=None), scenario ok=None, missing ['HEATING_VS_GAS'], violations []
- **S35** (conflict) `[explain savings]`: intent None (ok=None), scenario ok=None, missing ['HEATING_VS_GAS'], violations []
- **S37** (conflict) `Is something wrong with my wall answer?`: intent explain (ok=True), scenario ok=None, missing ['AGE_VS_INSULATION'], violations []
- **S38** (conflict) `[explain value]`: intent None (ok=None), scenario ok=None, missing ['VALUE_OUTLIER'], violations []
- **S41** (infeasible) `What if I only install loft insulation?`: intent whatif (ok=True), scenario ok=True, missing ['REASON_NO_LOFT'], violations ['RECOMMENDS:loft_insulation']
- **S42** (infeasible) `Why can't I have solar panels?`: intent explain (ok=True), scenario ok=None, missing ['REASON_NO_ROOF'], violations []
- **S43** (infeasible) `What if I add solar?`: intent whatif (ok=True), scenario ok=True, missing ['REASON_NO_ROOF'], violations []
- **S47** (infeasible) `Why not double glazing?`: intent explain (ok=True), scenario ok=None, missing ['REASON_LISTED'], violations []

## Limitations

- Engine numbers come from the models configured at run time (`model_versions` in the raw file).
- `must_mention` uses phrase patterns, so a correct answer worded differently counts as a miss.
- Latency is measured on the machine named above; the uncached client is used.
