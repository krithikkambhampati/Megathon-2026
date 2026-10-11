# LLM layer (Part 4)

Deliverable E: prompts, model and API details, guardrails, evaluation approach and results.
Code: `greenhome/llm/`. Config: `config/llm.yaml`. Evaluation: `evaluation/`. Build plan: `docs/archive/ROADMAP_P4.md`.

> **Current setup (2026-10-11).** Hosted open-weight model on Groq: `openai/gpt-oss-120b`, failing over to
> `openai/gpt-oss-20b` when rate limited. Local Ollama is an optional offline alternative (§10). The guardrails
> were loosened a little on 2026-10-11 (§1, §4, §6): friendlier prompt, off-topic chat answered by the LLM,
> hedged roundings of a fact accepted. §8 reports the evaluation rerun on gpt-oss-120b after these changes.

## 1. What the LLM does, and what it never does

The Green Home Score, savings, carbon and value numbers all come from P2's engine and P3's models. The LLM
**only explains** them in plain English and turns what-if questions into scenarios. It never calculates,
scores or estimates a number.

Four guardrails enforce this:
1. **Fact sheet.** The model only sees pre-formatted numbers, the exact strings the screens show.
2. **Number checker.** Every number in every reply is checked against that fact sheet. A hedged rounding of a
   fact is accepted ("about 4,000 kWh" for 3,990 kWh); a nearby number that only looks precise is not.
3. **One retry, then a template.** A failed check gets one retry with feedback, then a deterministic
   template answer built from the same facts. The user never sees an unchecked number.
4. **The LLM is never on the critical path.** With the LLM off, slow or failing, every endpoint still
   answers, from templates.

```mermaid
flowchart LR
  R[AnalysisResult\nP2 engine] --> F[facts.py\nfact sheet:\nformat.py strings]
  F --> P[prompts/*.j2\nREADME P4.3 rules\n+ FACTS + DATA_NOTES + REASONS]
  P --> L[client.py\nGroq gpt-oss-120b\n(Ollama offline)\ntemp 0 · seed 42]
  L --> C{checker.py\nevery number\nin FACTS?}
  C -- pass --> A[answer shown\n✓ verified]
  C -- fail, time left --> L
  C -- fail twice / timeout / no LLM --> T[templates/*.j2\ndeterministic, also checked]
  T --> A
  Q[chat message] --> RT[router.py\nrules → LLM JSON]
  RT -- whatif --> WP[whatif_parser.py\nrules → LLM JSON\n→ valid Scenario]
  WP --> E[engine.run_scenario\nmodels rerun first]
  E --> D[core/diff.py] --> F
  RT -- memory --> M[memory_parser.py\n→ proposal, never stored]
  RT -- off-topic / unclear --> G[general.j2\nLLM answers or redirects\nsame checker, template fallback] --> C
```

## 2. Model and runtime

| Item | Value |
|---|---|
| Runtime | Groq's OpenAI-compatible API (`LLM_PROVIDER=openai_compat`). Ollama ≥ 0.5 works offline with the same code (§10) |
| Model | **`openai/gpt-oss-120b`** (open-weight, Apache-2.0), pinned in `config/llm.yaml`. Picked in a live probe: correct routing in ~0.3–0.7 s and reliable JSON; `gpt-oss-20b` misrouted a what-if and `qwen/qwen3.8-27b` misclassified one |
| Failover | On HTTP 429 the client waits out `retry-after` for that model and sends the request to `fallback_models` (`openai/gpt-oss-20b`, its own quota). If every model is limited, the user gets the checked template |
| Quota | Groq free tier per model: 1000 requests/day, 8000 tokens/min. `/v1/health` pings are cached for 30 s |
| Reasoning | gpt-oss is a reasoning model: requests send `reasoning_effort: low`, `include_reasoning: false` (`request_extra`); hidden reasoning counts toward `max_tokens` |
| Determinism | `temperature 0`, `seed 42` on every request; identical requests are cached (in-memory LRU) |
| Output | `max_tokens` 900 for answers (the prompt asks for ≤ 250 words; the rest is room for reasoning), 400 for JSON parses, 256 for routing. A reply cut at the cap is never shown |
| Time budget | **25 s per answer** for all LLM calls together (router + parser + answer + retry). Per-call caps: router 4 s, parse 6 s, answer 12 s. A retry starts only with ≥ `min_retry_s` left (7 s). UI timeouts: 30 s |
| Privacy | Only the fact sheet (engine numbers and labels, no address or personal data) and the user's message are sent |
| Cost | £0 on the free tier |

Both providers are called over plain `httpx` streaming. Our own deadline stops reading mid-stream, and no
SDK retries in the background. A reply cut off at `max_tokens` is treated as a failure, never shown.

**Settings** (`config/llm.yaml`, environment variables override):

| Env var | Meaning |
|---|---|
| `LLM_PROVIDER` | `ollama` or `openai_compat`. **Env only**: unset means LLM off, so tests and unconfigured machines run on templates |
| `LLM_MODEL` | overrides the pinned model; leave empty to use the pin |
| `LLM_BASE_URL` | `https://api.groq.com/openai/v1` (or `http://localhost:11434` for Ollama) |
| `LLM_API_KEY` | hosted endpoint only; lives in `.env`, never committed |
| `LLM_TIMEOUT_S` | hard cap for one call (30) |
| `LLM_ANSWER_BUDGET_S` | budget for a whole answer (25) |

## 3. Interfaces (CR-7, used by P5's API)

```python
explain(result: AnalysisResult, section: "score"|"recommendations"|"savings"|"value", llm: LLMClient | None)
    -> tuple[str, CheckReport]          # never raises; LLM off/timeout → template, fallback_used=True
chat(req: ChatRequest, engine: Engine, llm: LLMClient | None, ctx: CustomerContext | None,
     base: AnalysisResult) -> ChatResponse   # stateless; multi-turn state = req.current_scenario
make_client() -> LLMClient | None       # None if not configured / unreachable / model not pulled
```

`CheckReport` always describes the text actually shown: `passed`, `numbers_found`, `unsupported`,
`banned_phrases`, `attempts` (LLM calls made), `fallback_used` (template). The web app labels a checked LLM
answer "Every figure checked against your report" and a template "Standard summary of your report" (the
Streamlit dashboard: "✓ all N numbers verified" / "Template answer").

| Chat intent | `scenario` | `result` | `diff` | `memory_proposal` |
|---|---|---|---|---|
| `whatif` | parsed scenario | `engine.run_scenario(...)` | `diff_results(base, result)` | — |
| `explain` | current scenario | base, or the current scenario's result | only for "why did it change?" | — |
| `memory` | current scenario | — | — | proposed events, **not stored** |
| `out_of_scope` / `unclear` | current scenario | — | — | — (the LLM answers general home-energy questions or redirects; template if off or failing) |

## 4. Prompts (`greenhome/llm/prompts/`)

| File | Used for |
|---|---|
| `_system.j2` | shared system prompt: README P4.3 core verbatim + FACTS, DATA_NOTES, REASONS, statuses |
| `explain_score.j2`, `explain_recommendations.j2`, `explain_savings.j2`, `explain_value.j2` | the task for each explain section |
| `whatif_answer.j2` | explaining a what-if result against the recommended plan |
| `whatif_parse.j2` | LLM fallback: message → `{"mode", "retrofits"}` (JSON schema; never numbers) |
| `memory_parse.j2` | LLM fallback: message → `{"events": [...]}` (budgets kept only if the user typed them) |
| `router.j2` | LLM fallback: message → one intent (JSON enum) |
| `general.j2` | off-topic or unclear messages: answer general home-energy questions, or redirect in a sentence or two |

The system prompt's rules (a unit test checks they are present):
```
1. Numbers about this home (scores, kWh, carbon, £, %) must come from FACTS, copied as their "display" text.
   Don't calculate new figures yourself. Light approximation of a FACTS number is fine ("about 4,000 kWh").
2. You may add general, widely known context and practical tips (how a heat pump works, why draughts
   matter, what to ask an installer), as long as you don't attach new numbers to them.
3. If the user asks for a figure that isn't in FACTS, say this tool doesn't estimate it, then help as best
   you can without inventing one.
4. Savings are "estimated". Property value changes are "indicative" and not guaranteed or causal.
5. If DATA_NOTES list missing, estimated, assumed or conflicting data, mention each one that relates to
   your answer in a short sentence, so the homeowner knows which figures rest on it.
6. Never recommend a retrofit marked infeasible or not possible, and never say it is in the plan.
   Say plainly that it isn't possible for this home and give its REASON.
7. If electricity use goes up while gas goes down, say so explicitly.
8. No personal financial or mortgage advice. Plain, warm English, at most 250 words, no tables.
```
Before 2026-10-11 the prompt was stricter (exact copies only, no general context, ≤ 170 words) and every
off-topic message got a fixed reply without calling the LLM. Rules 5 and 6 were tightened after the eval
below, which found data notes and infeasibility reasons often left out (§8). Rules 5 and 6 were tightened after the eval
below, which found data notes and infeasibility reasons often left out (§8). Rules 5 and 6 were tightened after the eval
below, which found data notes and infeasibility reasons often left out (§8). Rules 5 and 6 were tightened after the eval
below, which found data notes and infeasibility reasons often left out (§8). Rules 5 and 6 were tightened after the eval
below, which found data notes and infeasibility reasons often left out (§8).

## 5. Fact sheet (`facts.py`)

The model sees each fact's label and display string. It never sees the raw value, so it can't copy an
unrounded number. Example, the savings sheet for the PS example home P10001 on stub models:
```
F7 All recommended retrofits · estimated saving · electricity: 1,240 kWh/year increase
F8 All recommended retrofits · estimated saving · gas: 11,130 kWh/year
F10 Improvement potential (share of today's bought energy saved): 58.8%
F15 All recommended retrofits · estimated carbon saving (tonnes): 1.9 t CO2e/year
```
- **Display strings come only from `greenhome/format.py`** (`fmt_kwh_saving`, `fmt_points`, `fmt_range`, …),
  so the chat and the screens print identical strings.
- **No arithmetic in P4.** Diff facts (what-ifs) come from P2's `core/diff.py`.
- **Statuses gate numbers.** An `insufficient` or `out_of_scope` section contributes no numbers, only the
  reason (e.g. the no-info home P90003, the off-gas home P90005).
- **Score sheet** also carries floor area (`fmt_area`) and energy use per m² against similar homes
  (`fmt_intensity`); data notes use `FIELD_LABEL` names.
- **Size.** One section is ≲ 2.4k characters (≈ 600 tokens). Incremental savings and infeasible-item details
  are added only for retrofits the user names.

## 6. Number checker (`checker.py`)

1. **Extract** every numeric mention: £350,000 · £350k · £1.2m · 2–5% · 2.5% – 3.5% · 5,500 kWh · 1.2 t ·
   36/100 · −2,950 · years · number words next to a unit ("two thousand kWh", "halves"). Digits inside words
   are ignored (`CO2e`, `F7`, `P10001`).
2. **Match** against the display numbers of the sheet's facts, numbers in the notes and reasons, and a few
   context-bound structural numbers (0, small counts not followed by a time unit, "/100", "12 months").
   Same unit class, tolerance `max(½ display step, 0.5 %)`. After a hedge word ("about", "around",
   "roughly", "nearly", "over", "~" …) the number may also be the fact rounded to 1 or 2 significant figures.
3. **£ claims with no fact fail outright**: £-per-year bill savings and "adds £N to your value".
4. **Banned phrases, negation-aware.** "guarantee", "will increase your value", "certainly save",
   "exactly N", "financial advice", "you should remortgage" fail, but "indicative and not guaranteed" passes.
5. **Direction.** A number that is only ever an *increase* (e.g. a heat pump's extra electricity) fails when
   it is described as a saving.
6. **Infeasible retrofits.** A sentence that names a retrofit the engine marked not possible (or rejected in
   a what-if) together with "recommend…", "you should" or "plan includes", and no negation ("isn't
   possible", "instead of"), fails; the retry tells the model to give the REASON instead.
6. **Infeasible retrofits.** A sentence that names a retrofit the engine marked not possible (or rejected in
   a what-if) together with "recommend…", "you should" or "plan includes", and no negation ("isn't
   possible", "instead of"), fails; the retry tells the model to give the REASON instead.
6. **Infeasible retrofits.** A sentence that names a retrofit the engine marked not possible (or rejected in
   a what-if) together with "recommend…", "you should" or "plan includes", and no negation ("isn't
   possible", "instead of"), fails; the retry tells the model to give the REASON instead.
6. **Infeasible retrofits.** A sentence that names a retrofit the engine marked not possible (or rejected in
   a what-if) together with "recommend…", "you should" or "plan includes", and no negation ("isn't
   possible", "instead of"), fails; the retry tells the model to give the REASON instead.
6. **Infeasible retrofits.** A sentence that names a retrofit the engine marked not possible (or rejected in
   a what-if) together with "recommend…", "you should" or "plan includes", and no negation ("isn't
   possible", "instead of"), fails; the retry tells the model to give the REASON instead.

| Reply | Result |
|---|---|
| "Gas falls by 11,130 kWh/year, but electricity use goes up by 1,240 kWh/year." | pass |
| "You would save 1,240 kWh/year of electricity." | fail (direction) |
| "You'd save around 12,500 kWh of gas." (fact: 12,000) | fail (not a rounding of a fact) |
| "Gas use drops to about 900 kWh/year." (fact: 870) | pass (hedged 2-significant-figure rounding) |
| "That would save £400 a year on bills." | fail (no such figure) |
| "This is indicative and not guaranteed." | pass |
| "The recommended plan includes loft insulation." (flat under another flat) | fail (not possible) |
| "Loft insulation isn't possible because another home is above." | pass |
| "The recommended plan includes loft insulation." (flat under another flat) | fail (not possible) |
| "Loft insulation isn't possible because another home is above." | pass |
| "The recommended plan includes loft insulation." (flat under another flat) | fail (not possible) |
| "Loft insulation isn't possible because another home is above." | pass |
| "The recommended plan includes loft insulation." (flat under another flat) | fail (not possible) |
| "Loft insulation isn't possible because another home is above." | pass |
| "The recommended plan includes loft insulation." (flat under another flat) | fail (not possible) |
| "Loft insulation isn't possible because another home is above." | pass |

The templates go through the same checker in the tests. All 4 sections × 5 fixtures pass.

## 7. Router, what-if parser, memory

- **Router** (`router.py`), rules first in this order: hypotheticals ("what if", "suppose") → what-if;
  memory statements ("we installed", "our budget is", "we don't want") → memory; questions with a home-energy
  word → explain (section picked from the words); retrofit names with "only / without / add" → what-if; no
  domain word → out of scope; otherwise the LLM classifies (JSON enum) or the answer is "unclear". Out of
  scope and unclear messages then go to the LLM with `general.j2` (checked like any answer).
- **What-if parser** (`whatif_parser.py`): synonyms → retrofit ids, then operators applied **left to right on
  one working list**, so follow-ups build on the current scenario (README §16 step 6: "only solar", then
  "and a heat pump but no loft insulation", gives `[solar_pv, air_source_heat_pump]`; the engine then caps the
  heat pump at low with `INSULATE_FIRST`). Overrides use only numbers the user typed ("if my gas was 9,000
  kWh"), built from the user's raw input so the other fuel's monthly readings survive. Every scenario is
  validated with Pydantic before the engine runs. A budget or "wall insulation" with an unknown wall type
  gets a clarifying question. Infeasible requests are passed on and P2's engine rejects them with a reason.
- **Memory** (`memory_parser.py`): "We installed loft insulation last year and we don't want a heat pump"
  becomes `completed_retrofit(loft_insulation)` + `exclude(air_source_heat_pump)`. P4 **never stores**
  anything; the reply confirms what it heard. Storing these and feeding them back into the analysis (the
  optional customer-memory extension) is **not wired up yet**: the engine accepts a `CustomerContext`, but the
  API always passes none (`TODO(P5-23)` in `api/routes/analyse.py` and `chat.py`).

## 8. Evaluation

Run with the Groq key in `.env`: `make eval` (`python -m evaluation.eval_llm --tpm 6000`). `--tpm` paces the
scenarios to stay under the free tier's 8,000 tokens per minute (≈35 min for 80 scenarios); `make eval
EVAL_TPM=0` turns pacing off for a local model. Without an LLM it exits with an error.
`--allow-no-llm` writes a clearly marked pipeline test (`reports/llm_eval_dryrun.md`) instead.

| Set | Size | What |
|---|---|---|
| `evaluation/llm_scenarios.jsonl` | 80 | 20 normal · 10 missing data · 10 conflicting signals · 10 infeasible requests · 10 heat pump · 8 insufficient info · 8 multi-turn what-if · 4 adversarial. Each item: home (fixture + overrides), turns, expected intent/scenario, `must_mention`, `must_not`. Built by `evaluation/build_llm_scenarios.py` |
| `evaluation/whatif_parse_gold.jsonl` | 50 | labelled utterances → expected `Scenario`; 44 for the rules, 6 left to the LLM fallback |
| Human annotation | 40 answers | stratified sample from the eval run, labelled claim by claim by P1 and P2 independently (`evaluation/annotation/RUBRIC.md`) |

**Metrics** (targets from README P4.6):
- **Numeric groundedness** (target ≥ 90%): % of answers with 0 unsupported numbers, **before** the checker
  (raw first LLM attempt) and **after** it (the answer shown).
- **Factual accuracy** (target ≥ 90%): % of numbers matching facts, plus `must_mention` satisfied.
- **Unsupported claim rate** (target < 5%): from the human annotation, with Cohen's κ.
- **Also:** `must_not` violations, intent and scenario accuracy, what-if parse accuracy (rules only vs
  rules + LLM), fallback rate by reason, latency median/p95, tokens per answer.

**Results** (`make eval` on 2026-10-11 with `openai/gpt-oss-120b` on Groq, real engine models, commit
`192cbe5`; full report `reports/llm_eval.md`, every answer in `reports/llm_eval_raw.jsonl`):

| Metric | Before checker (raw first attempt) | After checker (answer shown) | Target |
|---|---|---|---|
| Numeric groundedness | 70.5% | **100.0%** | ≥ 90% |
| Factual accuracy (numbers matching a fact) | — | **100.0%** | ≥ 90% |
| Unsupported claim rate (human) | — | pending human annotation | < 5% |
| `must_mention` satisfied (automatic phrase match) | — | 79.4% (50 of 63) | ≥ 90% |
| `must_mention` satisfied (misses read by hand) | — | 93.7% (59 of 63) | ≥ 90% |
| `must_not` violations | — | 1 of 80 | 0 |
| Intent / scenario accuracy | — | 100% / 100% | — |
| What-if parse accuracy | rules only 46/50 | rules + LLM 45/50 | — |
| Latency median / p95 | — | 1.8 s / 3.6 s | ≤ 25 s |
| Output tokens per answer (mean, incl. hidden reasoning) | — | 593 | — |

How to read it:
- **The checker does its job.** Three in ten raw drafts had a number that isn't in the facts, most often an
  invented percentage ("9 %", "71 %") or a count added to general advice; every one was rewritten on retry
  or replaced by the template, so every number a user sees matches a fact. Raw groundedness is lower than in
  the earlier local-model run (84.3%) because the loosened prompt invites general context, and the model
  sometimes attaches a number to it. Answers by source: 70 LLM, 8 template after a failed check, 2 template
  after an LLM error (two long answers that hit the time or token cap).
- **`must_mention` is a phrase match, and it undercounts.** Of the 13 misses, 9 are correct answers worded
  differently: "the tool doesn't have enough information" or "can't be calculated" for a home with too
  little data (7), and "would cause an increase of about 3,990 kWh" for a heat pump's extra electricity (2).
  The 4 real misses are data notes or reasons left out: similar-homes energy estimate (S27), unusual value
  (S38), solar already installed (S50), and "indicative" in a one-line refusal (S77). We report the
  automatic figure as the headline and the hand-checked one beside it.
- **The infeasible-retrofit fix worked.** The earlier violation (S41, "the recommended plan includes loft
  insulation" for a flat under another flat) is gone: no answer recommended an impossible retrofit, and 9 of
  the 10 infeasible-request answers gave the reason (S50 left out that solar is already installed).
- **The one `must_not` violation** (S68): asked to explain the score of a home with too little information,
  the answer correctly said no score can be given, then listed the home's problem areas with a peer
  percentile (a real fact, hence the `NUMBERS` flag) and described the seven score parts wrongly (it named
  "hot water" and "ventilation"). The numbers were all right; the wording was not. This kind of non-numeric
  error is what the human annotation measures.
- **The LLM fallback hurts parsing slightly** (45/50 vs 46/50 rules only), so the rules-first design is right.
- **Fast and free.** Median answer 1.8 s, p95 3.6 s; the whole run used the free tier.

Pipeline test with templates only (dev machine, no LLM, stub models; this shows the pipeline works, not
model quality): the shown answers were 100% grounded, `must_mention` was 100% satisfied, there were 0
`must_not` violations, and intent accuracy was 100%. The rules alone parsed 46 of the 50 what-if items: all
44 rules items, plus the 2 LLM items whose expected answer is a clarifying question.

## 9. Limitations

- Any LLM will make mistakes. The checker stops wrong numbers, not clumsy wording. A sentence
  with correct numbers can still be unhelpful, so the human annotation measures that separately.
- `must_mention` uses phrase patterns, so a correct answer worded differently counts as a miss.
- The direction check uses nearby cue words. An unusual phrasing can slip past it or be flagged wrongly
  (flagged answers fall back to the template, which is safe).
- A custom what-if scenario skips P2's budget filter (`OVER_BUDGET` exists only in recommended mode).
- General advice the LLM adds (rule 2) has no numbers but is not fact-checked; it is limited to widely
  known context, and the human annotation is where unhelpful or wrong advice would show up.
- The hosted model depends on Groq's free-tier quota; when it runs out, answers fall back to templates.
- Answers sometimes cite internal fact ids such as "(F13)" (6 of 70 LLM answers in the eval). Harmless for
  accuracy, but visible to the user.
- When a section can't be estimated, the LLM may still add general advice around the "not enough
  information" message, and that advice can be wrong (S68). Sending such sections straight to the template
  would remove the risk.

## 10. Offline alternative: a local model with Ollama

The hosted setup needs only `LLM_API_KEY` in `.env` (docs/RUN.md §2). To run without internet:

1. Install Ollama ≥ 0.5. For a 6 GB GPU, set `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=1` and
   `OLLAMA_KV_CACHE_TYPE=q8_0`.
2. `ollama pull qwen2.5:7b-instruct-q4_K_M`.
3. In `.env`, set `LLM_PROVIDER=ollama`, `LLM_BASE_URL=http://localhost:11434` and
   `LLM_MODEL=qwen2.5:7b-instruct-q4_K_M` (the demo-laptop benchmark winner).
4. Optional: `make llm-bench` compares local candidates (`reports/llm_bench_<host>.md`).
5. Run `uv run --env-file .env python -m evaluation.eval_llm`. This writes `reports/llm_eval.md` and the
   annotation pack (`evaluation/annotation/`).
6. Send P1 and P2 `MESSAGE.md`. When both sheets are back, run `uv run python -m evaluation.annotate score`
   to write `reports/llm_annotation.md`.
7. Run `make api`. `/v1/health` should show `llm_ok: true`.
