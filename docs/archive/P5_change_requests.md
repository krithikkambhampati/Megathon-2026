# P5 → P2: contract change requests (CR-1 … CR-8)

> **Archived build log (2026-10-11).** Written during the hackathon to plan and track the build. Some of it is
> out of date (for example local Ollama instead of the hosted Groq model, Streamlit as the only UI, the
> stricter LLM prompt). For how the system works now, see `README.md` and `docs/` (RUN, ARCHITECTURE, LLM,
> SCORING, DATA, MODELS, RESPONSIBLE_AI).

**To:** P2 (contract owner). CR-6 also concerns P2's orchestrator. CR-7 concerns **P4**.
**From:** P5 (API, UI, memory)
**Reply needed by:** H+2 (contract freeze). If these go into `contracts.py` v1.0.0, nobody needs a version bump or regenerated fixtures later.

## P2 reply (2026-10-10)
All 8 answered in the table below and implemented in `contracts.py` v1.0.0.
**Update (PR #1 review):** bumped to **v1.1.0**: `DiffKey` gains `score_after` and `class_after` (12 rows), because
`score` / `score_class` only move when a scenario overrides home fields.
Fixtures: `tests/fixtures/analysis_result_*.json` (4 homes, stub models), regenerate with
`.venv/bin/python tests/fixtures/generate.py`.

## Status (updated 2026-10-10)
- **No replies yet** (superseded by the P2 reply above). P2 has started on the contracts but hasn't pushed them yet. Please fold in the accepted CRs
  before the H+2 freeze.
- **P5 isn't waiting.** Until you reply, P5 builds against the code in this document **exactly as written**,
  treating it as a placeholder. If you edit or reject a CR, P5 adapts its code to your version (or to that CR's
  "If rejected" fallback). Nothing on your side is blocked by this.
- **Where P5's code is:** branch `p5/main` in the team repository. Already there:
  - the API shell (`api/`): error envelope `{"error": {"code", "message"}}`, NaN → `null` on every response,
    and `GET /v1/health`
  - the UI shell (`ui/`) with 9 placeholder pages
- **What P5 needs from you next, besides the replies:** `greenhome/contracts.py` and
  `tests/fixtures/analysis_result_P10001.json` (README D1/D2). Until they land, P5 uses a temporary stand-in
  built from BUILD_GUIDE §7.3 plus these CRs. Your real files replace it, and the stand-in is never merged to `main`.

## Why
The README contract (§7.3 / §7.7 / §7.8) leaves out some things the UI and API need. P5 isn't allowed to compute
numbers (BUILD_GUIDE P5 hazard 1), so a missing value can't be worked out in the UI. It has to come from P2. Each
CR below gives exact code, then says what P5 does if you reject it.

## How to reply
Copy this table back, fill in the "Your answer" column, and edit the code however you like. Your version
wins. "P5 status" shows what P5 is building against right now.

| CR | Summary | Your answer (Accept / Edit / Reject) | P5 status |
|---|---|---|---|
| CR-1 | Memory event models in `contracts.py` + `ChatResponse.memory_proposal` | **Accept** | Done, as written (month pattern also rejects `2025-13`) |
| CR-2 | `ResultDiff` + `core/diff.py: diff_results()` + `ChatResponse.diff` | **Accept** | Done: `greenhome/core/diff.py::diff_results` |
| CR-3 | `PeerComparison` + `AnalysisResult.peer` | **Edit**: band names `lt50 / 50_90 / 90_130 / 130_200 / gt200` (match config); `property_type` nullable; `None` also when energy is typical-home imputed | Done |
| CR-4 | `PortfolioRow` / `PortfolioResponse`; `engine.portfolio()` returns typed rows | **Accept**: `customer_id` is `str \| None`. Not batched across homes: ~5 ms/home on stubs (9k homes ≈ 45 s); revisit with real models | Done |
| CR-5 | `analysis_id` hash includes the customer context | **Accept** (was already implemented) | Done |
| CR-6 | Engine applies all `CustomerContext` rules (incl. `priority`) | **Edit**: budget uses net mid cost (cost midpoint − grant, floored at 0), not `cost_high`, to match BUILD_GUIDE P2.8 cost-efficiency. Weights live at `score.yaml: suitability.priority_weights` with keys `assessor / saving_share / cost_eff`. `carbon` re-weights the kWh share (no separate carbon share yet) | Done |
| CR-7 | Fixed signatures for P4's `explain`, `chat`, `make_client` | P4: (P2 confirms `Engine` is `greenhome.core.orchestrator.Engine`) | Waiting on P4 |
| CR-8 | Minimum function list for `format.py` | **Accept**: names as listed + `fmt_kg_saving`; `fmt_delta` units = `DiffRow.unit` (`score`, `sap`, `kwh_per_year`, `kg_per_year`, `pct` → `pp`); minus sign is U+2212 | Done |

---

## CR-1: Memory events + memory proposal on `ChatResponse`
**Gap:** BUILD_GUIDE P4.5 says P4 extracts a memory change from chat and the UI asks the user to confirm it.
`ChatResponse` has no field to carry it, and the event schema exists only in P5's SQLite table. P4 produces
this type, so it has to live in the shared contract.

```python
# greenhome/contracts.py — additions (add `Annotated` to the typing import)
class CompletedRetrofitPayload(Strict):
    kind: Literal["completed_retrofit"] = "completed_retrofit"
    retrofit: Retrofit
    completed_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")

class ExcludeConstraintPayload(Strict):
    kind: Literal["exclude"] = "exclude"
    retrofit: Retrofit

class BudgetConstraintPayload(Strict):
    kind: Literal["budget"] = "budget"
    max_budget_gbp: float = Field(gt=0)

class PreferencePayload(Strict):
    kind: Literal["preference"] = "preference"
    priority: Literal["carbon", "bills", "value", "balanced"]

class RecommendationShownPayload(Strict):
    kind: Literal["recommendation_shown"] = "recommendation_shown"
    analysis_id: str
    ranked_retrofits: list[Retrofit]          # feasible ones, in rank order, as shown

class ResponsePayload(Strict):
    kind: Literal["response"] = "response"
    retrofit: Retrofit
    response: Literal["accepted", "declined"]

MemoryPayload = Annotated[
    CompletedRetrofitPayload | ExcludeConstraintPayload | BudgetConstraintPayload
    | PreferencePayload | RecommendationShownPayload | ResponsePayload,
    Field(discriminator="kind")]

class MemoryEventIn(Strict):
    payload: MemoryPayload

class MemoryEvent(Strict):
    id: int
    customer_id: str
    ts: str                                    # ISO 8601 UTC, e.g. 2026-10-10T14:03:00Z
    payload: MemoryPayload

# ChatResponse gains:
    memory_proposal: list[MemoryEventIn] | None = None   # set only when intent == "memory"
```
**If rejected:** chat can't propose memory. Memory is entered only through the UI's Memory panel.

## CR-2: `ResultDiff`, computed by P2 code
**Gap:** the what-if screen shows a before/after diff table, and the score card shows "36 → 61 (+16)". The UI
may not subtract. BUILD_GUIDE P4.2 already needs diff facts "computed by code" for the LLM, so one P2 function
should serve both the UI and P4.

```python
# greenhome/contracts.py
class DiffRow(Strict):
    key: Literal["score", "score_class", "electricity_kwh", "gas_kwh", "net_kwh",
                 "improvement_potential_pct", "carbon_total_kg", "value_uplift_pct_mid",
                 "rating_after", "sap_after"]
    unit: Literal["score", "class", "kwh_per_year", "pct", "kg_per_year", "rating", "sap"]
    base: float | str | None
    new: float | str | None
    delta: float | None        # new − base for numeric keys; None for class/rating or if either side is None

class ResultDiff(Strict):
    base_analysis_id: str
    new_analysis_id: str
    rows: list[DiffRow]        # always all 10 keys, in the order above
    retrofits_added: list[Retrofit]     # in new.savings.retrofits, not in base
    retrofits_removed: list[Retrofit]

# ChatResponse gains:
    diff: ResultDiff | None = None
```
- New P2 module: `greenhome/core/diff.py: diff_results(base: AnalysisResult, new: AnalysisResult) -> ResultDiff`.
- The `electricity_kwh`, `gas_kwh` and `net_kwh` rows compare **`savings.saving`**, keeping the README sign
  convention (positive = reduction).
- P4's `facts.py` builds its diff facts from this. P5 exposes it as `POST /v1/diff`.

**If rejected:** the UI shows base and scenario values side by side with no delta column.

## CR-3: Peer comparison on `AnalysisResult`
**Gap:** the Problem-areas screen says "You use X kWh/m²; similar-sized semis use Y". The engine already reads
`peer_percentiles.parquet` for issues, but it doesn't expose the values.

```python
class PeerComparison(Strict):
    intensity_kwh_m2: float
    property_type: PropertyType
    floor_area_band: Literal["lt_50", "50_90", "90_130", "130_200", "gt_200"]
    p50_kwh_m2: float
    p75_kwh_m2: float
    p90_kwh_m2: float

# AnalysisResult gains:
    peer: PeerComparison | None = None      # None if intensity or peer group unavailable
```
**If rejected:** the UI reads `evidence` from a `HIGH_INTENSITY` issue when there is one, and hides the
gauge otherwise.

## CR-4: Typed portfolio rows + precomputed portfolio
**Gap:** `engine.portfolio()` returns `list[dict]`, so its columns are undefined. Computing it live is also
too slow. The test split is ~4.5k–9k homes, and at the BUILD_GUIDE's 500 ms per `analyse()` that's 40–75 minutes.

```python
class PortfolioRow(Strict):
    rank: int                               # 1 = highest improvement potential
    property_id: str
    customer_id: str
    region: Region | None
    property_type: PropertyType | None
    score: int | None
    score_class: ScoreClass | None
    is_poor: bool | None
    improvement_potential_pct: float | None # None sorts last
    key_issues: list[str]                   # up to 3 issue codes, high → low severity
    savings_status: Literal["ok", "insufficient", "out_of_scope"]

class PortfolioResponse(Strict):
    split: Literal["train", "val", "test"]
    generated_at: str
    model_versions: dict[str, str]
    total: int
    rows: list[PortfolioRow]
```
- `engine.portfolio(split, limit=None) -> list[PortfolioRow]` (batched internally, as fast as you can make it).
- P5 runs it **offline** via `make portfolio` → `outputs/portfolio/portfolio_test.json`. The API only serves
  that file and never calls `portfolio()` per request.

**If rejected:** P5 maps your dicts to `PortfolioRow` in the API. Please post the dict keys in writing.

## CR-5: `analysis_id` includes the customer context
**Gap:** BUILD_GUIDE §7.3 hashes "canonical input + scenario + model versions". With memory, the same home gives
different results for different customer contexts, so the API's result cache would serve stale results.

**Change:**
`analysis_id = sha256(canonical(home) + canonical(scenario) + canonical(ctx or null) + model_versions + CONTRACT_VERSION)`

**If rejected:** P5 keys its cache on `(analysis_id, sha256(ctx))`. That works, but duplicates logic.

## CR-6: The engine applies all `CustomerContext` rules
**Gap:** BUILD_GUIDE P5.4 has P5's `context.py` applying completed retrofits to the home, while BUILD_GUIDE P2.8 step 6
has the engine handling exclusions and budget. Split across two places, they'll drift apart.
**Proposal:** P5 only turns memory events into a `CustomerContext`. `engine.analyse(home, ctx)` and
`run_scenario(home, scenario, ctx)` apply **every** rule:

| ctx field | Engine behaviour | Reason code |
|---|---|---|
| `completed_retrofits` | `home = apply_retrofits(home, completed)` **before** validation; those retrofits then show as already installed | `ALREADY_INSTALLED` |
| `excluded_retrofits` | Removed from the package and from ranking; still listed in `recommendations` with `rank=None` | `CUSTOMER_EXCLUDED` |
| `declined_retrofits` | Suitability demoted one level (high→medium→low; low stays low) | `CUSTOMER_DECLINED_BEFORE` |
| `max_budget_gbp` | Greedy by `u_r` using `cost_high_gbp`; items that don't fit are left out of the package | `OVER_BUDGET` |
| `priority` | Selects the suitability weights (below). Changes ranking and suitability only, never a number | — |

The PS (§10) explicitly lists "stated constraints **or preferences**" as memory that should adapt
recommendations, so `priority` should do something. Proposed addition to `config/score.yaml`:
```yaml
# u_r = w_p * p_r + w_save * norm(save_r) + w_cost * norm(cost_eff_r)      (BUILD_GUIDE P2.8 step 3)
priority_weights:
  balanced: {w_p: 0.4, w_save: 0.4, w_cost: 0.2}   # = README default
  carbon:   {w_p: 0.3, w_save: 0.5, w_cost: 0.2}   # save_r = standalone CARBON saving share, not net kWh share
  bills:    {w_p: 0.3, w_save: 0.3, w_cost: 0.4}
  value:    {w_p: 0.4, w_save: 0.4, w_cost: 0.2}   # = balanced; no per-retrofit value model (documented limitation)
```
Improvement potential still uses the full feasible package minus completed retrofits (BUILD_GUIDE P2.8 step 6).

For reference, P5 builds the context from events like this (`greenhome/memory/context.py`). Events are
processed in `(ts, id)` order:
- `completed_retrofit`: add the retrofit to `completed_retrofits` and remove it from `declined_retrofits`.
- `exclude`: add to `excluded_retrofits`.
- `budget` and `preference`: the latest one wins.
- `response: declined`: add to `declined_retrofits`. `response: accepted`: remove from `declined_retrofits`.
- `recommendation_shown`: no effect on the context (it's only used for the UI's "then vs now" view).
- Lists are deduplicated and kept in retrofit-enum order.

**If rejected:** P5 applies completed retrofits itself (via your `apply_retrofits`), and the engine handles the rest.

## CR-7 (for P4): Function signatures P5 calls
P5 builds `/v1/explain` and `/v1/chat` against these from H+3:
```python
# greenhome/llm/explainer.py
Section = Literal["score", "recommendations", "savings", "value"]
def explain(result: AnalysisResult, section: Section, llm: LLMClient | None) -> tuple[str, CheckReport]:
    """Never raises for LLM failures: llm None/timeout → template text, CheckReport.fallback_used = True."""

# greenhome/llm/chat.py
def chat(req: ChatRequest, engine: Engine, llm: LLMClient | None,
         ctx: CustomerContext | None, base: AnalysisResult) -> ChatResponse:
    """Stateless. `base` = engine.analyse(req.home, ctx), computed by the API and passed in.
    Multi-turn state = req.current_scenario only; P5 keeps the transcript."""

# greenhome/llm/client.py
def make_client() -> LLMClient | None:   # None if LLM_PROVIDER unset/unreachable at start-up
```
**If rejected:** P4 posts their actual signatures by H+3, and P5 adapts.

## CR-8: Functions `format.py` must provide
P2 chooses the names. P5 needs at least these, following the BUILD_GUIDE §7.1 rounding rules. Each one accepts
`None` and returns `"—"`:

| Function | Example output |
|---|---|
| `fmt_kwh(x)` | `"12,000 kWh/year"` |
| `fmt_kwh_saving(x)` | `"2,520 kWh/year"`; negative → `"2,950 kWh/year increase"` |
| `fmt_kg(x)` / `fmt_tonnes(kg)` | `"1,230 kg CO2e/year"` / `"1.2 t CO2e/year"` |
| `fmt_gbp_value(x)` | nearest £500: `"£357,000"` |
| `fmt_gbp_cost(x)` | nearest £10: `"£1,490"` |
| `fmt_pct(x)` | 1 dp: `"3.5%"` |
| `fmt_score(x)` / `fmt_sap(x)` | `"36"` |
| `fmt_range(lo, hi, fn)` | `"£357,000 – £367,500"` |
| `fmt_delta(x, unit)` | always signed: `"+16"`, `"−2,950 kWh/year"` |

**If rejected:** P5 uses whatever you ship and never writes its own formatter.
