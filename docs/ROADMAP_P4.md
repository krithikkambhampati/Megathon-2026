# Part 4 (LLM Layer) — Roadmap & Build Spec

Source of truth for *what* to build: the team guide (README §2.11, §4.3, PART 4) plus P5's change requests
(`P5_change_requests.md`, CR-1/2/7/8) and P5's follow-ups (one answer budget, warm-up). This file says *how*
and *in what order*, so a human or an agent can pick up any task cold. Tick boxes as tasks land. Task IDs
are commit IDs: task `P4-05` lands as commit `P4-05: …`.

**The rule this part enforces:** the LLM only *explains*. It never calculates, scores or estimates. Every
number the user sees was computed by P2's engine, formatted by `greenhome/format.py`, and passed our number
checker. If the LLM is off, slow or wrong, the user gets a deterministic template answer built from the same
facts: never an error, never an unchecked number.

**Definition of done (whole part):**
- `uv run pytest` green with **no LLM running** (LLM behaviour is tested with a scripted client) ·
  `uv run ruff check .` clean
- `explain()` returns checked text for 4 sections × 5 fixtures with the LLM off; every template passes the checker
- `chat()` on stubs handles README §16 step 6 (turn 1 "What if I only install solar?" → `custom [solar_pv]`;
  turn 2 "and a heat pump but no loft insulation?" → `custom [solar_pv, air_source_heat_pump]`, heat pump
  `low` + `INSULATE_FIRST` in the answer) and step 8 ("We installed loft insulation last year and we don't
  want a heat pump" → intent `memory`, proposal = completed loft + exclude heat pump, nothing stored)
- `make llm-bench` run on the demo laptop, model pinned · `make eval` → `reports/llm_eval.md` from a real
  model run · `docs/LLM.md` written · P4 inputs to `evaluation.md`, `RESPONSIBLE_AI.md`, `RUN.md` delivered

---

## How the pieces fit

```
                         ┌─────────── explain(result, section, llm) ───────────┐
AnalysisResult ─► facts.py ─► FactSheet ─► prompts/*.j2 ─► client.py ─► LLM text
  (P2 engine)       │  display strings      (README P4.3 system     (Ollama / OpenAI-compat over httpx,
                    │  from format.py ONLY   prompt + FACTS lines +   temp 0, seed 42, cache, deadline)
                    │  diff from diff.py     DATA_NOTES + REASONS)              │
                    │                                                           ▼
                    │                                   checker.py: every number must match a fact the
                    │                                   model saw; banned claims and wrong directions fail
                    │                                     pass ─► answer    fail ─► retry once with feedback
                    │                                                       (if time left) ─► fail/timeout
                    └──────────────► templates/*.j2 ◄─────────────────────────────┘
                                     (deterministic fallback from the same FactSheet, also checked)

chat(req, engine, llm, ctx, base):
  message ─► router.py ─┬─ whatif  ─► whatif_parser.py (rules → LLM JSON) ─► Scenario
                        │             ─► engine.run_scenario(req.home, scenario, ctx) ─► diff_results(base, new)
                        │             ─► what-if FactSheet ─► same LLM / checker / template loop
                        ├─ explain ─► explain flow on base (or on the current scenario's result)
                        ├─ memory  ─► memory_parser.py ─► memory_proposal: list[MemoryEventIn] (NEVER stored)
                        └─ out_of_scope / unclear ─► template reply (clarifying question)
```

**Stateless:** `chat()` keeps nothing between calls. Multi-turn state is `req.current_scenario` only. P5
keeps the transcript, stores memory only after the user confirms, and passes `base = engine.analyse(req.home, ctx)`.

---

## Phases and tasks

`→` = depends on. Estimates are for one focused engineer or agent. Target hours are README §14.

### Phase 0 — Foundation · ~2.5 h
- [x] P4-01 `docs/ROADMAP_P4.md`: this file
- [x] P4-02 `config/llm.yaml`, `greenhome/llm/{settings,budget,client,fake}.py`, tests
  - `OllamaClient`, `OpenAICompatClient` (both plain httpx, streaming), `CachedClient`, `make_client()`
  - `fake.py`: `ScriptedClient` (scripted replies / delays / errors), used by tests **and** by eval dry runs
  - Tests: request bodies (temperature 0, seed 42, keep_alive, format), deadline mid-stream, `length` stop →
    error, unreachable → `None`, provider unset → `None`, cache hit/miss/LRU/thread lock, warm-up

### Phase 1 — Works with the LLM off (target H+10, deliverable D8) · ~7 h
- [x] P4-03 `greenhome/llm/{facts,_labels}.py`: fact sheets per section, what-if sheet, notes, reasons → P4-02
- [x] P4-04 `greenhome/llm/checker.py` + a ~60-sentence test table (extraction, matching, banned, direction)
  → P4-03
- [x] P4-05 `greenhome/llm/templates/{score,recommendations,savings,value}.j2` + `explainer.py` (template
  path and the guarded LLM loop, tested with `ScriptedClient`). **From this commit P5's `/v1/explain`
  switches on.** → P4-03, P4-04
  - Test: 4 templates × 5 fixtures (+ edge homes) pass the checker; insufficient/out_of_scope say so with no numbers

### Phase 2 — Chat on rules + templates (target H+16, deliverable D11) · ~8 h
- [x] P4-07 `greenhome/llm/router.py` (+ `prompts/router.j2` for the LLM fallback) + ~30 router test strings
- [x] P4-08 `greenhome/llm/whatif_parser.py` (+ `prompts/whatif_parse.j2`) and
  `evaluation/whatif_parse_gold.jsonl` (50 items, also the parser's unit-test data)
- [x] P4-10 `greenhome/llm/chat.py` + `templates/{whatif,memory_confirm,out_of_scope,unclear}.j2`, working on
  rules + templates first → P4-05, P4-07, P4-08
- [x] P4-09 `greenhome/llm/memory_parser.py` (+ `prompts/memory_parse.j2`), wired into chat → P4-10

### Phase 3 — LLM answers · ~3 h
- [x] P4-06 `prompts/{_system,explain_score,explain_recommendations,explain_savings,explain_value,
  whatif_answer}.j2` + the LLM path in explainer and chat (generate → check → retry once → template, one
  deadline) → P4-05, P4-10

### Phase 4 — Benchmark and pin the model (demo laptop) · ~2 h + run time
- [x] P4-11 `evaluation/llm_bench.py` (`make llm-bench`, target added by P5) → P4-06, P4-08
- [ ] P4-12 Run it **on the demo laptop**, commit `reports/llm_bench_<host>.md`, pin the winner and
  `min_retry_s` in `config/llm.yaml` with the reason → P4-11

### Phase 5 — Evaluation and docs (target H+26) · ~9 h
- [x] P4-13 `evaluation/llm_scenarios.jsonl` (~80 items)
- [x] P4-14 `evaluation/eval_llm.py` (`make eval`) → P4-06, P4-13
- [x] P4-15 `evaluation/annotation/` (`RUBRIC.md`, `MESSAGE.md`) + `evaluation/annotate.py` (export of the two
  shuffled sheets, Cohen's κ). Sheets are generated by the demo-laptop eval run. **Responses generated at H+20 on the best model available; sheets to P1/P2 by H+22** → P4-14
- [ ] P4-16 `reports/llm_eval.md`: all metrics, κ, failure examples, limitations → P4-14, P4-15
- [x] P4-17 `docs/LLM.md`: model, tag and why; prompts; guardrails; budget; eval approach and results → all
- [x] P4-18 Inputs for other owners (`docs/P4_INPUTS.md`, numbers TODO_BENCH): LLM section of `reports/evaluation.md` (to P3 by H+26); hallucination
  paragraph for `docs/RESPONSIBLE_AI.md`, Ollama steps for `docs/RUN.md` and before/after-checker numbers for
  the closing demo slide (to P5 by H+28)

**Cut order if late (cut the bottom first):** memory LLM fallback → router LLM fallback → number words in the
checker → annotation reduced to 20 responses. **Never cut:** checker, template fallback, rules-first parser,
answer budget, before/after-checker numbers, the bench's latency / cold-load / first-answer / JSON numbers.

---

## Demo laptop (not the dev machine)

The demo laptop has an RTX 4050 (6 GB VRAM) and 16 GB RAM. The dev machine has no GPU and no Ollama. So the
code is built and tested here against `ScriptedClient`, and everything that needs the real model is a
placeholder until it runs there.

| Placeholder | Where | Filled by |
|---|---|---|
| `model: TODO_PIN_AFTER_BENCH` (+ `candidates:` list) | `config/llm.yaml` | P4-12 |
| `min_retry_s` default 8 (`TODO_BENCH`) | `config/llm.yaml` | P4-12 (bench p95 answer time) |
| Latency, cold-load, first-answer, GPU-fit numbers | `docs/LLM.md`, `reports/llm_eval.md` (`TODO_BENCH`) | P4-12 |
| Headline eval numbers | `reports/llm_eval.md` | `make eval` on the demo laptop |

While the model says `TODO_PIN_AFTER_BENCH`, `make_client()` returns `None` and the app runs on templates.

**Checklist on the demo laptop (by H+20):**
1. Install Ollama ≥ 0.5 (`ollama --version`). Server settings: `OLLAMA_NUM_PARALLEL=1`,
   `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` (these are Ollama settings, not Python packages).
2. `ollama pull` each candidate in `config/llm.yaml: candidates`.
3. Write `.env`: `LLM_PROVIDER=ollama`, `LLM_BASE_URL=http://localhost:11434`. Leave `LLM_MODEL` empty
   (the pinned yaml model is used; a value in `.env` overrides it).
4. `make llm-bench` → read `reports/llm_bench_<host>.md` → pin the winner and `min_retry_s` (P4-12).
5. `make eval` → `reports/llm_eval.md` + the 40 annotation responses.
6. `make api` → `/v1/health` shows `llm_ok: true`; the log shows the model and its warm-up time.
7. Replace every `TODO_BENCH` / `TODO_PIN_AFTER_BENCH`.

**If the laptop is not ready by H+20:** generate the annotation responses and eval with the hosted
OpenAI-compatible endpoint (README L5), and say so in the report header and the CSVs. **If no candidate passes
the bench bar:** explanations default to templates, the LLM is used only in chat, and the pin falls back to
the best 3–4B model or the hosted endpoint, with the reason in `docs/LLM.md` (README §17).

**Candidates** (exact tags confirmed with `ollama pull`): one 7–8B instruct model at 4-bit and one 3–4B
instruct model. Pass bar, measured with no deadline: p95 answer time ≤ the 12 s answer cap, `Scenario` JSON
adherence ≥ 90 %, model fully on GPU (`/api/ps`: `size_vram == size`). Best first-attempt checker pass rate
wins among those that pass.

---

## Code conventions (P2's, plus LLM-specific ones)
1. `from __future__ import annotations` first. The module docstring says what the module owns and its README §.
2. Python 3.11 type hints. Ruff config in `ruff.toml` (line length 110).
3. **No number formatting outside `greenhome/format.py`.** Facts carry display strings; prompts and templates
   print `fact.display`, never a raw float. If a formatter is missing (intensity, floor area), the number is
   left out and P2 is asked for one; P4 never writes its own.
4. **No arithmetic on result numbers.** Deltas come from `core/diff.py`. The only numbers P4 produces are ones
   the user typed (a budget, "if my gas was 9000"), and they go into a `Scenario.overrides` or memory payload,
   and are shown back as facts. The one unit conversion is score weight fraction → percent for display.
5. No magic numbers: timeouts, caps, budgets, token limits, tolerances, model options in `config/llm.yaml`;
   score weights and class thresholds read from P2's config.
6. Enums are plain strings; compare with `==`. Missing = `None`.
7. Codes (flag, issue, reason) are P2's. Never invent one. **Never write `code="UPPER"` or `_flag("UPPER"` in
   `greenhome/**/*.py`** (P5's `test_labels.py` scans for those and checks them against FLAG_TEXT ∪
   ISSUE_TEXT). Keep code maps as dict keys.
8. **The LLM is never on the critical path.** `explain()` and `chat()` catch every LLM error and never raise
   because of the LLM.
9. Tests in `tests/unit/p4/test_llm_<module>.py` (the `llm_` prefix avoids basename clashes, since `tests/` has
   no `__init__.py`). Plain pytest functions. LLM behaviour uses `greenhome.llm.fake.ScriptedClient`. No test
   needs a network or a GPU.
10. Shortcuts carry a `# ponytail: <limit>, <upgrade path>` marker.
11. P4 adds no packages (docs/RUN.md). Already pinned and used: `httpx`, `jinja2`, `pydantic`, `pyyaml`. Both
    LLM providers are called over plain `httpx` streaming, so the `ollama` and `openai` packages stay unused
    (no hidden SDK retries, one deadline implementation).

---

## Module interfaces (binding signatures)

```python
# greenhome/llm/settings.py ─ P4-02
class LLMSettings(BaseModel):           # config/llm.yaml, then env overrides
    provider: Literal["ollama", "openai_compat"] | None  # env LLM_PROVIDER ONLY (never yaml); unset → LLM off
    model: str                          # env LLM_MODEL overrides yaml; "TODO_PIN_AFTER_BENCH" → LLM off
    base_url: str                       # env LLM_BASE_URL
    api_key: str | None                 # env LLM_API_KEY (openai_compat only; never in yaml)
    answer_budget_s: float              # env LLM_ANSWER_BUDGET_S: cap for a WHOLE answer (25)
    call_timeout_s: float               # env LLM_TIMEOUT_S: hard cap for any one call (30)
    call_cap_s: dict[str, float]        # per prompt: router 4, whatif_parse 6, memory_parse 6, answer 12
    min_call_s: float                   # don't start a call with less than this left (3)
    min_retry_s: float                  # retry only with at least this left (8, TODO_BENCH)
    warmup_timeout_s: float             # cold load (120)
    keep_alive: str                     # "2h", sent on EVERY Ollama request
    temperature: float; seed: int; num_ctx: int          # 0 · 42 · 4096
    max_tokens: dict[str, int]          # explain 300, whatif_answer 300, whatif_parse 200, memory_parse 200,
                                        # router 16, warmup 1
    candidates: list[str]; cache_max_entries: int
# Empty env values and placeholders like "<exact ollama tag>" count as unset.
def get_llm_settings() -> LLMSettings: ...   # cached; P4's own loader, P2's greenhome/config.py untouched

# greenhome/llm/budget.py ─ P4-02
class Deadline:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic): ...
    def remaining(self) -> float: ...
    def expired(self) -> bool: ...
    def call_timeout(self, cap_s: float) -> float: ...     # min(cap_s, remaining())
    def can_call(self, min_s: float) -> bool: ...          # remaining() >= min_s

# greenhome/llm/client.py ─ P4-02
class LLMError(Exception): ...          # unreachable, HTTP error, error line, cut off at max_tokens, empty
class LLMTimeout(LLMError): ...         # deadline hit (including mid-stream)
class LLMClient(Protocol):
    name: str                           # "ollama:<tag>" (docs/eval only, never shown to users)
    def generate(self, system: str, messages: list[dict], json_schema: dict | None = None,
                 max_tokens: int = 400, *, timeout_s: float | None = None) -> str: ...
    def ping(self, timeout_s: float = 2) -> bool: ...
    # README P4.1 signature + keyword-only timeout_s. `last_usage` (tokens in/out, seconds, load seconds)
    # is set after each call for the bench and eval.
class OllamaClient: ...                 # POST /api/chat, stream, options{temperature, seed, num_ctx,
                                        # num_predict}, keep_alive, format=schema; done_reason "length" → LLMError
class OpenAICompatClient: ...           # POST {base}/chat/completions, stream, temperature, seed, max_tokens,
                                        # response_format json_schema (strict false); finish_reason "length" → error
class CachedClient: ...                 # LRU + lock; key = sha256(json.dumps([name, system, messages, schema,
                                        # max_tokens], sort_keys=True)); only complete replies are cached
def make_client() -> LLMClient | None:  # CR-7. None if provider unset / model not pinned / unreachable (≤ 2 s)
                                        # / model not pulled. Otherwise starts the warm-up in a background
                                        # thread (so API start-up isn't blocked) and returns CachedClient.
                                        # Never raises. Never falsy.

# greenhome/llm/fake.py ─ P4-02
class ScriptedClient: ...               # replies: str | Exception | Slow(text, seconds) | callable; records calls

# greenhome/llm/facts.py ─ P4-03
class Fact(BaseModel):
    id: str; key: str                   # "F7", "savings.saving.electricity_kwh"
    value: float | str | None           # raw engine value: NEVER shown to the model
    display: str                        # the exact format.py string the UI shows
    unit: str                           # kwh_per_year · kwh_per_m2 · kg_per_year · t_per_year · gbp_value ·
                                        # gbp_cost · pct · pp · score · sap · count · rating · class · text
    label: str                          # what the number is, in words ("Heat pump · electricity")
    direction: Literal["up", "down"] | None   # "up" = use/emissions rise; from the sign, no arithmetic
class FactSheet(BaseModel):
    section: Literal["score", "recommendations", "savings", "value", "whatif", "memory"]
    facts: list[Fact]; notes: list[str]; reasons: dict[str, str]; statuses: dict[str, str]
    view: dict                          # nested display strings for the templates
    def lines(self) -> str: ...         # prompt form: "F7 Heat pump · electricity: 3,600 kWh/year increase"
def build_facts(result: AnalysisResult, base: AnalysisResult | None = None) -> list[Fact]: ...  # README P4.2
def build_fact_sheet(result, section, base=None, diff=None, focus: list[str] | None = None,
                     user_facts: list[Fact] | None = None) -> FactSheet: ...

# greenhome/llm/checker.py ─ P4-04
def extract_numbers(text: str) -> list[Mention]: ...   # Mention(raw, value, negative, unit_class, span)
def check(text: str, sheet: FactSheet) -> CheckReport: ...   # attempts/fallback_used filled by the caller

# greenhome/llm/explainer.py ─ P4-05 / P4-06
Section = Literal["score", "recommendations", "savings", "value"]
def explain(result: AnalysisResult, section: Section, llm: LLMClient | None) -> tuple[str, CheckReport]: ...
def explain_traced(result, section, llm, *, deadline=None, question=None, focus=None) -> ExplainTrace: ...
    # ExplainTrace: every attempt's raw text + CheckReport + seconds + tokens; the shown text + report.

# greenhome/llm/router.py ─ P4-07
def route(message: str, *, has_scenario: bool, llm=None, deadline=None) -> RouteResult: ...
    # RouteResult(intent, method: "rules" | "llm" | "default", section: Section, focus: list[Retrofit])

# greenhome/llm/whatif_parser.py ─ P4-08
def parse_whatif(message: str, home: HomeInput, base: AnalysisResult, current: Scenario | None, *,
                 llm=None, deadline=None) -> ParseResult: ...
    # ParseResult(scenario | None, method: "rules" | "llm" | "none", clarify: str | None, user_facts)
    # `home` = the user's raw HomeInput (req.home), used for overrides; `base` for the package and provenance.

# greenhome/llm/memory_parser.py ─ P4-09
def parse_memory(message: str, base: AnalysisResult, *, llm=None, deadline=None) -> list[MemoryEventIn]: ...

# greenhome/llm/chat.py ─ P4-10
def chat(req: ChatRequest, engine: Engine, llm: LLMClient | None,
         ctx: CustomerContext | None, base: AnalysisResult) -> ChatResponse: ...   # CR-7
```

### `ChatResponse` per intent (`base_result_id = base.analysis_id` always)
| intent | `scenario` | `result` | `diff` | `memory_proposal` | answer |
|---|---|---|---|---|---|
| `whatif` | parsed scenario | `engine.run_scenario(req.home, scenario, ctx)` | `diff_results(base, result)` | None | what-if sheet |
| `explain` | `req.current_scenario` | base, or the current scenario's result if one is set | None | None | section sheet |
| `memory` | `req.current_scenario` | None | None | proposed events | confirm template |
| `out_of_scope` / `unclear` | `req.current_scenario` | None | None | None | template |

`check` always describes the text actually shown. A template answer is run through `check()` too:
`numbers_found` filled, `passed=True`, `fallback_used=True`, `attempts` = LLM attempts actually made (0 if none).
An engine error on a parsed scenario (e.g. a bad override) → intent `unclear` with a clarifying question.

### Answer budget (P5 request) · 25 s per answer → UI timeouts 30 s
- `explain()` / `chat()` create one `Deadline(answer_budget_s)`. Each call gets
  `deadline.call_timeout(min(call_cap_s[prompt], call_timeout_s))`, and the client also stops reading when its
  timeout passes (`LLMTimeout`).
- No call starts with less than `min_call_s` left. **A retry starts only with at least `min_retry_s` left**,
  and in chat not at all if an LLM parse fallback already ran.
- Rough fit (7B Q4 on the RTX 4050): answer ~7–8 s, so answer + retry ~16 s; chat with LLM parse ~22 s.
  The bench confirms or tightens the caps.
- Out of budget after a scenario was parsed → template answer with the real recomputed numbers.

### Warm-up and keep_alive (P5 request)
- `make_client()`: `/api/tags` reachable (≤ 2 s) and the model pulled → start a daemon thread that sends one
  1-token request with **the same options as real calls** (a different `num_ctx` would make Ollama reload) and
  `keep_alive: "2h"`, then checks `/api/ps` and logs a warning if the model is not fully on the GPU. The client
  is returned at once, so API start-up isn't blocked; an early question simply waits for the load.
- `keep_alive` goes on **every** request (a request without it resets Ollama's unload timer to 5 min).
- OpenAI-compatible: no keep_alive; the warm-up is a 1-token request that also checks the API key.

---

## Fact sheets (P4-03)
- **Display strings only from `format.py`:** `fmt_kwh`, `fmt_kwh_saving` (negative → "… increase"), `fmt_kg`,
  `fmt_kg_saving`, `fmt_tonnes` (positive totals only; it doesn't handle negatives), `fmt_gbp_value`,
  `fmt_gbp_cost`, `fmt_pct`, `fmt_score`, `fmt_points` (sub-scores, contributions), `fmt_sap`,
  `fmt_intensity`, `fmt_range` ("a – b"), `fmt_delta`. Labels from `greenhome.labels`. Floor area via `fmt_area`.
- **Prompt form:** `F7 Heat pump · electricity: 3,600 kWh/year increase`. The raw `value` and `unit` are never
  shown to the model, so it can't copy unrounded numbers.
- **Statuses gate numbers:** an `insufficient` / `out_of_scope` section contributes a status and its flag
  text, no numbers (P90003, P90005).
- **score:** score, class, range (if unknown inputs), each component's label, weight (as %), sub-score and
  provenance if not user-given; issues (label + engine message); score after the recommended package.
- **recommendations:** feasible / needs_survey items in rank order: name, rank, suitability, reasons,
  standalone per-fuel saving, carbon, cost range, depends-on. Incremental savings and infeasible-item detail
  only for `focus` items; other infeasible items: name + reason. Fuels that round to 0 are dropped.
- **savings:** baseline, after, saving per fuel and net, improvement potential, carbon per fuel and total
  (+ tonnes when positive), emission-factor source name (URL stripped).
- **value:** current value + source, rating before → after, SAP before/after, uplift range and mid, value
  range, the `indicative_not_causal` caveat.
- **whatif** (needs `base`): the 12 diff rows from `diff_results()`. Energy and carbon rows compare *savings*,
  so their facts are labelled "estimated saving: base plan → this scenario" (`fmt_kwh_saving`), and the delta
  "change in saving vs your recommended plan" (`fmt_delta`). Class/rating rows are "E → C" text. Plus: the
  scenario's package (each item's suitability and reasons, e.g. `INSULATE_FIRST`), every `rejected` item with
  its reason text, the statuses, and the user's own stated numbers as facts. Improvement potential always
  uses the full feasible package, so it is shown only when overrides changed the home.
- **DATA_NOTES** from `result.flags` (it already contains `home.flags`), deduped by (code, field), errors
  first, as `FLAG_TEXT` + the engine message. Missing/estimated answers are grouped into one note listing
  field names, **without a count**. Engine messages with raw values (e.g. "floor_area_m2 estimated as 70.0")
  are replaced by the field's `FIELD_LABEL` name only.
- **Size:** each sheet ≲ 1.5k tokens (unit test with a char budget per sheet on the largest fixture).

## Number checker (P4-04)
1. **Extract** every numeric mention: `£350,000` · `£350k` · `£1.2m` · `2–5%` · `2 to 5 %` · `2.5% – 3.5%` ·
   `5,500 kWh` · `1.2 t` · `1,200 kg` · `36/100` · `+16` · `−2,950` (U+2212 and ASCII) · ordinals · ranges
   (both ends, unit and £ propagated). Digits touching letters are not numbers (`F7`, `CO2e`, `m2`, `P10001`).
   4-digit numbers with no unit and no £ are years and must still be allowed. Number words next to a unit
   (`two thousand kWh`, `halves`, `a third of`) are extracted; `double glazing`, `one of`, `single` are not.
2. **Normalise** to (|value|, class ∈ {gbp, pct, kwh, co2, score, plain, year}): k/m multipliers, t → kg,
   MWh → kWh. Signs are dropped for matching; direction is checked separately.
3. **Allowed set:** the display numbers of every fact on the sheet (+ unit conversions); numbers inside
   anything else the model saw (notes, reasons, labels) as `plain`; `0` in any class. Context-bound extras:
   integers 1–10 as plain only when not followed by a time or quantity unit (years, months, days, %, £,
   kWh…); score weights and class thresholds (read from `score.yaml`) only on the score sheet, near
   "weight / counts for / makes up / worth" or a component name; 12 only before "months". The user's own
   numbers count only once they are facts (overrides, memory payloads).
4. **Match:** same class (plain matches any; score ↔ plain) and `|x − v| ≤ max(0.5 × display step,
   0.005 × |v|)`. Steps: kWh/kg 10, t 0.1, £ value 500, £ cost 10, % 0.1, score/SAP 1.
5. **£ claims we never make** fail outright: a £ amount described as a value increase
   (`(add|increase|boost|raise)s? … value … £N`) and any £ bill saving (`£N a/per year`, `bills … £N`): no
   bill-saving or £-uplift fact exists.
6. **Banned phrases** (negation-aware: skipped when `not|no|never|isn't|aren't|can't|cannot|without` comes
   just before): `guarantee(d)`, `will (definitely) increase your (property) value`, `certainly save`,
   `exactly <n>`, `financial advice`, `you should (re)mortgage`. "Indicative and not guaranteed" passes.
7. **Direction:** a mention that only matches `direction="up"` facts must have an increase cue (increase, rise,
   goes up, higher, extra, additional, adds, more electricity) nearer to it (±6 tokens, same clause) than a
   saving cue (save, reduce, cut, lower, less, fall, drop). Clauses split on `.;!?` and `, but/while/whereas`.
   Failing → `unsupported` entry `"<n> (direction)"`.
8. The retry feedback lists unsupported numbers, banned phrases and direction errors.
9. Templates go through the same checker in tests: a failing template is a bug.

## Explain / chat flow (P4-06)
```
deadline = Deadline(answer_budget_s); sheet = build_fact_sheet(...)
if llm is None or not deadline.can_call(min_call_s): return template(sheet) + check (attempts=0, fallback)
text1 = llm.generate(system(sheet), msgs, timeout_s=deadline.call_timeout(cap))   # LLMError → template
r1 = check(text1, sheet);  if r1.passed: return text1, r1 (attempts=1)
if not deadline.can_call(min_retry_s): return template + check (attempts=1, fallback)
text2 = llm.generate(..., msgs + [assistant text1, user feedback(r1)])            # LLMError → template
r2 = check(text2, sheet);  if r2.passed: return text2, r2 (attempts=2)
return template + check (attempts=2, fallback)
```
- `prompts/_system.j2` holds the README P4.3 system-prompt core **verbatim** (7 rules, ≤ 170 words, no
  tables), with FACTS (as lines), DATA_NOTES and REASONS. A test checks the 7 rules are present.
- The templates carry the same guardrail sentences: savings are "estimated"; value is "indicative, not
  guaranteed or causal"; "electricity use goes up" whenever `ELECTRICITY_RISES_GAS_FALLS` applies.
- Prompt files: one per section (`explain_savings.j2` and `explain_value.j2` instead of the README's combined
  `explain_savings_value.j2`, because CR-7's `Section` treats them separately).

## Router (P4-07), in this order
1. Normalise case and quotes (’ → ').
2. **Hypothetical → whatif:** `\b(what if|suppose|imagine|if (i|we)|instead of)\b` (before memory, so
   "what if we had a heat pump" is not memory).
3. **memory:** `(we|i) (already |recently )?(installed|put in|got|had … (fitted|put in))\b … <retrofit>`,
   `(i|we) can't (have|get|fit|afford)`, `\bbudget\b`, `don't want`, `not interested`,
   `we care (most )?about`, `(we|i) (declined|said no to|turned down)`.
4. **explain:** starts with `why|how|explain|what does|what is|tell me about` **and** has a domain word.
   Section: `rating|epc|score|class` → score; `recommend|suitable|should i|which|retrofit names` →
   recommendations; `saving|carbon|co2|electricity|gas|kwh` → savings; `value|price|worth` → value; default
   score. `focus` = retrofits named. With a current scenario, "why did … go up / change / differ" explains
   the scenario result with its diff.
5. **Weak what-if cues** (`\b` on all): `only|just|without|skip|add|also|install|get|fit`, `and (a|the)? <retrofit>`.
6. **out_of_scope:** no domain word at all.
7. Otherwise → LLM classify (JSON enum) if the budget allows → else `unclear`.

## What-if parser (P4-08)
- **Synonyms** (`\b` on all): `solar|pv|panels` → solar_pv · `heat pump|ashp` → air_source_heat_pump ·
  `loft|attic|roof insulation` → loft_insulation · `cavity` → cavity_wall_insulation · `wall insulation` →
  cavity or solid by wall type (**clarify** when `base.home.provenance["wall_type"]` is imputed/assumed) ·
  `double glazing|windows|glazing` → double_glazing · `smart thermostat|thermostat|controls` →
  smart_thermostat · `\b(everything|all of them|full package)\b` → mode recommended · `nothing|no changes` → none.
- **One working list, operators applied left to right:**
  start = `current.retrofits` if the current scenario is custom, else `base.savings.retrofits`
  (`[]` for mode none). `only/just X` → replace with [X] · `add/also/and/install/get X` → append (deduped,
  order kept) · `without/except/skip/no/but no X` → remove · `X instead of Y` → replace Y with X.
  With no current scenario, `install/get/fit X` alone → `custom [X]`. Result: `Scenario(mode="custom", …)`.
- **Overrides** (validated as `HomeInput` before the engine runs):
  - `if my gas (use) was N` → `{"energy": {**home.energy, "annual_gas_kwh": N, "monthly": readings with
    gas_kwh=None}}` (built from the user's raw `req.home.energy`, so the other fuel's monthly data and its
    coverage survive; never copied from the cleaned home). Same for electricity.
  - `if my home was rated C` → `{"energy_rating": "C"}`; `if I already had X` → the field values from P2's
    `transitions.apply_retrofits` mapping, not a hand-written table.
  - A budget what-if ("if my budget was £8,000") → clarify: budgets are memory, not a `Scenario` field.
- High confidence = ≥ 1 retrofit or override and one operator matched → rules result. Otherwise the LLM
  fallback with the `Scenario` JSON schema → `Scenario.model_validate` → overrides re-validated. Failure → clarify.
- Infeasible requested items pass through: P2 puts them in `rejected` with a reason and the answer explains it.
- `Scenario.name` is a short deterministic label ("only solar_pv").
- Known limitation: a custom scenario skips P2's budget filter (`OVER_BUDGET` only exists in recommended mode).

## Memory proposals (P4-09)
- Rules first: `we (already )?installed X (in YYYY-MM | last year)` → `CompletedRetrofitPayload`
  (`completed_on` only when the user gave a month) · `don't want / can't have X` → `ExcludeConstraintPayload` ·
  `budget (of) £N` → `BudgetConstraintPayload` · `we care about carbon/bills/value` → `PreferencePayload` ·
  `we said no to X` → `ResponsePayload(declined)`. One message can give several events.
- LLM fallback: schema `{"events": [...]}` (wrapped, strict off), validated. Nothing valid → `unclear`.
- **P4 never stores anything.** `chat()` returns the proposal with a confirm template; P5's UI asks the user.

## Evaluation (P4-13 … P4-16), targets: groundedness ≥ 90 %, accuracy ≥ 90 %, unsupported < 5 %
- **`llm_scenarios.jsonl` (~80):** 20 normal explanations, 10 missing data, 10 conflicting signals,
  10 infeasible requests, 10 heat-pump electricity-rises, 8 insufficient info, 8 multi-turn what-if,
  4 adversarial. Item: `{id, category, home: <fixture id | inline HomeInput>, ctx?, turns: [{message,
  current_scenario?}], expected_intent, expected_scenario?, section?, must_mention: [codes], must_not: [...]}`.
  Homes: P2's 5 fixture inputs + documented field overrides, run live through `Engine`.
- **`whatif_parse_gold.jsonl` (50):** `{id, home, current_scenario?, message, expected: Scenario}`; exact match
  after normalising (mode, retrofit list, overrides). Includes both demo turns and the router edge cases.
- **`eval_llm.py`** uses the uncached inner client. Metrics: numeric groundedness (raw first attempt vs final
  shown), factual accuracy (numbers + `must_mention` via a code → phrase map), `must_not` violation rate,
  intent accuracy, parse accuracy rules-only vs rules + LLM, fallback rate, budget-exhausted rate, latency
  median/p95, tokens per answer, cost £0. Writes `reports/llm_eval.md` + `reports/llm_eval_raw.jsonl`.
  The report header records provider, model tag, host and date. With no real LLM it exits non-zero, unless
  `--allow-no-llm`, which writes a "PIPELINE TEST, not results" banner and never overwrites a real report.
- **`llm_bench.py`**, per candidate: unload all models (`keep_alive: 0`, `/api/ps` empty), build an uncached
  `OllamaClient` directly, then measure:
  - cold load (warm-up time + Ollama's `load_duration`) and first answer after warm-up
  - answer time p50/p95 for explain and what-if, with no deadline; tokens per second
  - `Scenario` JSON adherence on the 50 gold items
  - first-attempt checker pass rate (4 sections × 5 fixtures)
  - `/api/ps` `size_vram` / `size`
  - `num_ctx` 4096 vs 8192
  - still loaded after an idle wait (keep_alive works)
- **Human annotation (P1 + P2, P5 backup):** 40 responses, stratified by category. Each sentence is split into
  atomic claims; each claim is labelled `supported | unsupported | not_a_claim` against its fact sheet. Same
  items, a different shuffled order per annotator, labelled separately. Unsupported-claim rate =
  unsupported / (supported + unsupported); Cohen's κ on claims. The CSVs record which model wrote each answer.

---

## Requests to teammates (all done, on main)
- **P5:** `/v1/chat` calls `chat()` per CR-7 · UI timeouts 30 s · `.env` loaded by every make target ·
  `make llm-bench` · `.env.example` (blank `LLM_MODEL`, `LLM_ANSWER_BUDGET_S=25`) · `INCOMPATIBLE_HEATING`
  and `FIELD_LABEL` in `greenhome.labels` · live `llm.ping(2)` on `/v1/health`.
- **P2:** `fmt_intensity`, `fmt_points`, `fmt_area` in `format.py`; P4 uses all three.
- **Still open:** P1 + P2 annotate the 40 answers (by H+22, after the demo-laptop eval run); P3's real
  models (P4 re-runs its tests and the eval when `models: real`).

---

## Decisions made while planning (not in the team guide)
- CR-7 accepted with `llm: LLMClient | None` in all three signatures (P5 confirmed).
- `generate()` gains keyword-only `timeout_s`; the Protocol gains `ping()`. Positional signature unchanged.
- One 25 s budget per answer with per-prompt call caps; retries only with ≥ `min_retry_s` left. `num_ctx`
  4096 and `max_tokens` 300 so answer + retry fits on a 6 GB GPU.
- Warm-up in a background thread with the same options as real calls; `keep_alive: "2h"` on every request.
- Both providers over plain httpx streaming (not the `ollama`/`openai` SDKs): one deadline implementation,
  no hidden SDK retries.
- `provider` comes from the environment only, so tests and unconfigured machines run on templates.
- Router checks hypotheticals before memory (README lists what-if cues first but its memory cues catch
  "what if we had …").
- What-if operators compose left to right on one working list; "without X" is `custom` because `Scenario`
  has no exclusion field.
- Fact sheets show the model display strings only; the checker matches |value|, and direction is a separate check.
- Banned phrases are negation-aware ("not guaranteed" is required wording, not a violation).
- `explain_traced()` keeps every raw attempt for the before/after-checker numbers; `explain()` returns what is shown.
