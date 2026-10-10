# Part 2 (Core Engine) — Roadmap & Build Spec

Source of truth for *what* to build: the team guide (README §7 contracts, PART 2). This file says *how* and
*in what order*, so a human or an agent can pick up any task cold. Tick boxes as tasks land.

**Definition of done (whole part):** `uv run pytest` green · `uv run ruff check .` clean ·
`Engine.from_config().analyse(P10001)` returns score 36 / poor on stubs · IT1–IT12 pass (IT10/IT11 skip
until P3 ships `models/`) · `docs/SCORING.md` written · fixtures regenerated.

---

## Phases and tasks

Estimates are for one focused engineer/agent. `→` = depends on.

### Phase 0 — Foundation (blocks everyone) · ~1 h
- [x] T0.1 `pyproject.toml`, `.gitignore`, `ruff.toml` — taken from P5 skeleton (origin/main)
- [x] T0.2 `greenhome/contracts.py` — §7.2 enums + §7.3 models, verbatim field names
- [x] T0.3 `config/*.yaml` — P2-owned (`global`, `score`, `engine`) + P1 placeholders marked `TODO_SOURCE`
- [x] T0.4 `greenhome/config.py` — typed cached loader (`get_config()`)
- [x] T0.5 `greenhome/format.py` — the only rounding/formatting module
- [x] T0.6 `greenhome/ml/protocols.py` — 4 model Protocols + `Models` container

### Phase 1 — Leaf modules (parallel, 4 workstreams) · ~1.5 h each
| WS | Files | Tests | → |
|---|---|---|---|
| A (done) | `core/annualise.py`, `core/validate.py` | `test_annualise.py`, `test_validate.py` | T0 |
| B (done) | `core/score.py`, `core/features.py`, `core/transitions.py` | `test_score.py` (Hypothesis + golden), `test_features.py`, `test_transitions.py` | T0 |
| C (done) | `core/feasibility.py`, `core/issues.py`, `core/carbon.py` | `test_feasibility.py`, `test_issues.py`, `test_carbon.py` | T0 |
| D (done) | `ml/stubs.py`, `core/ordering.py`, `core/value.py` | `test_stubs.py`, `test_ordering.py`, `test_value.py` | T0 |

Cross-workstream imports allowed only through the signatures below (write against the signature; the other
workstream lands the body). The one in-phase dependency: B's `insulation_sub_score` is used by C, D.

### Phase 2 — Orchestration · ~2 h
- [x] T2.1 `core/orchestrator.py` — `Engine.from_config / analyse / run_scenario / portfolio` → Phase 1
- [x] T2.2 `tests/fixtures/` — 4 `home_input_*.json` + `generate.py` → `analysis_result_*.json` → T2.1
- [x] T2.3 `tests/unit/p2/test_orchestrator.py` (ctx, budget, scenario modes) → T2.1

### Phase 3 — Integration & docs (parallel) · ~1.5 h
- [x] T3.1 `tests/integration/test_engine.py` — IT1–IT12 (README P2.9) → T2.2
- [x] T3.2 `docs/SCORING.md` — tables, 4 justifications, worked example, min-info policy, feasibility
- [x] T3.3 Review pass: ruff, dead code, every threshold in YAML, no rounding outside `format.py`

### Phase 3b — Part 5 change requests (done)
- [x] CR-1 … CR-8 implemented (see Decisions); tests in `test_diff.py`, `test_format.py`, `test_orchestrator.py`

### Phase 4 — Hand-off (when teammates deliver)
- [x] T4.1 P1's sourced `retrofit_catalogue`, `emission_factors`, `regions`, `intensity_bounds` adopted verbatim
  (still placeholder: `imputation.yaml`, `engine.yaml: peers_fallback`)
- [ ] T4.2 P3 ships `greenhome/ml/registry.py::load_models(models_dir: Path) -> Models` (container in
  `ml/protocols.py`) → set `models: real` in `global.yaml`. P5's `/v1/health` reads `engine.cfg.global_.models`
  and `engine.models.versions()`: do not rename.
- [ ] T4.3 P3 tunes `score.yaml: suitability` thresholds on val (D13)
- [ ] T4.4 P5 passes `CustomerContext` from memory (D14)

---

## Code conventions (every file, every author)

1. `from __future__ import annotations` first; module docstring says what the module owns + README section.
2. Type hints on every public function. Python 3.11 syntax (`X | None`, `list[str]`).
3. **No magic numbers.** Every threshold/factor/table comes from `get_config()`; add YAML keys (and the
   matching field in `config.py`) rather than literals. Stub constants from README P2.1 are the one exception,
   kept as named module constants at the top of `ml/stubs.py`.
4. **No rounding** anywhere except `greenhome/format.py` (`round_half_up`, `round_score`).
5. Enum values are plain strings at runtime (`use_enum_values=True`). Compare with `==` against `Enum.member`
   or the string; never `is`. Retrofit iteration order = `list(Retrofit)` (catalogue order).
6. Missing = `None`. Never `0` for unknown. Pandas uses `NaN` internally only.
7. Pure functions; no I/O except `config.py` and `Engine.portfolio()`. Determinism: no `random` without the
   config seed.
8. Flags/issues/reasons use the binding codes from README P2.2/P2.6/P2.7 exactly (constants below).
9. Tests in `tests/unit/p2/test_<module>.py`, plain pytest functions, shared builders from `tests/conftest.py`.
   Test behaviour, not internals. Import builders with `from conftest import home_input, make_clean`.
   Run tests with `.venv/bin/python -m pytest` (plain `uv run` re-resolves deps and needs network).
10. Ruff config in `ruff.toml` (P5-owned, line length 110). Comments explain *why*, sparingly.
11. Shortcuts are marked `# ponytail: <limit>, <upgrade path>`.

### Binding codes
- **DataFlag codes:** `MISSING_FIELD IMPUTED_FIELD LOW_COVERAGE_ANNUALISATION INSUFFICIENT_MONTHLY_DATA
  CONFLICT_ANNUAL_VS_MONTHLY CONFLICT_HEATING_VS_GAS CONFLICT_RATING_VS_USAGE CONFLICT_AGE_VS_INSULATION
  CONFLICT_ROOF_VS_TYPE OUTLIER_AREA_PER_BEDROOM OUTLIER_INTENSITY OUTLIER_VALUE ENERGY_FROM_TYPICAL_HOMES
  OUT_OF_SCOPE_FUEL INSUFFICIENT_INFO_SCORE INSUFFICIENT_INFO_SAVINGS INSUFFICIENT_INFO_VALUE`
- **Issue codes:** `HIGH_INTENSITY LOW_RATING POOR_ROOF_INSULATION POOR_WALL_INSULATION SINGLE_GLAZING
  OLD_HEATING NO_RENEWABLES NO_SMART_CONTROLS`
- **Reason codes:** `ALREADY_INSTALLED NO_LOFT_DWELLING_ABOVE FLAT_ROOF_INSULATION_DIFFERENT_MEASURE
  WRONG_WALL_TYPE LISTED_OR_CONSERVATION NO_SUITABLE_ROOF NEEDS_OUTDOOR_SPACE_CHECK UNKNOWN_INPUT_SURVEY
  INSULATE_FIRST HIGH_COST_LOW_SAVING HIGH_SAVING QUICK_WIN_LOW_COST ELECTRICITY_RISES_GAS_FALLS
  ASSESSORS_OFTEN_RECOMMEND CUSTOMER_EXCLUDED CUSTOMER_DECLINED_BEFORE OVER_BUDGET OUT_OF_SCOPE_FUEL
  INCOMPATIBLE_HEATING` (last one added by P2: smart thermostat with direct electric heating)

---

## Module interfaces (binding signatures)

```python
# core/annualise.py  [WS-A]
def annualise_fuel(readings: dict[str, float], shares: Sequence[float], window: int
                   ) -> tuple[float | None, float]:
    """readings: {"YYYY-MM": kWh} non-null only. Window = `window` calendar months ending at the latest
    month present. Returns (annual or None, coverage). coverage = Σ shares[month-1] of present months in
    window. annual = Σ values / coverage if coverage ≥ coverage_min else None."""
def annualise(energy: EnergyInput, region: str | None) -> tuple[AnnualEnergy, list[DataFlag]]:
    """Per-fuel monthly-vs-annual logic of README P2.2 step 2. No typical-home imputation here.
    Raises ValueError on duplicate months."""

# core/validate.py  [WS-A]
def band_for_sap(sap: float) -> str            # engine.yaml sap_bands (A..G)
def anchor_sap(raw_sap: float, band: str | None) -> float   # clip into band's SAP range; raw if band None
def validate_and_clean(home: HomeInput, rating_model: RatingModel | None = None) -> CleanHome
    # order: annualise → conflict rules → impute (floor area, features+main_fuel, energy, rating) →
    # intensity → outlier rules → sap_estimate. provenance covers every FEATURE_FIELDS name plus
    # "electricity_kwh" and "gas_kwh". Imputed values → provenance "imputed"; main_fuel inferred from
    # heating → "derived". Never mutates the input.

# core/score.py  [WS-B]
def insulation_sub_score(roof_type, roof_insulation, wall_type, wall_insulation) -> float | None
def compute_score(clean: CleanHome) -> ScoreResult
    # README P2.4 + P2.5. Unknown = provenance in {"imputed", "assumed"}. Range: enumerate every value of
    # each unknown score_feature_field (exact; ≤3 by min-info rule) and an imputed rating ±rating_band_spread.

# core/features.py  [WS-B]
FEATURE_COLUMNS: list[str]   # fixed order, exported to P3's features.json
def build_model_features(homes: list[CleanHome], packages: list[frozenset[str]] | None = None) -> pd.DataFrame

# core/transitions.py  [WS-B]
def apply_retrofits(home: HomeInput, package: Iterable[str]) -> HomeInput   # idempotent, order-free

# core/feasibility.py  [WS-C]
def feasible_set(home: HomeInput, unknown: Iterable[str] = ()) -> dict[str, tuple[str, list[str]]]
    # all 7, catalogue order. `unknown` = fields to treat as None (orchestrator passes imputed fields,
    # because a cleaned home has imputed values filled in). P1's simulator calls feasible_set(home).

# core/issues.py  [WS-C]
def detect_issues(clean: CleanHome, score: ScoreResult, feasibility: dict[str, tuple[str, list[str]]]
                  ) -> tuple[list[Issue], bool | None]                   # (issues, is_poor)

# core/carbon.py  [WS-C]
def compute_carbon(saving: FuelSaving) -> CarbonResult

# ml/stubs.py  [WS-D]
class StubEnergy, StubRating, StubRecommender, StubValue   # implement ml/protocols.py, version "stub-0"
def load_stub_models() -> Models

# core/ordering.py  [WS-D]
@dataclass(frozen=True)
class Candidate:
    retrofit: str
    feasibility: str                    # feasible | needs_survey
    p_assessor: float
    standalone: FuelSaving | None       # None when savings are unavailable
    baseline_purchased_kwh: float | None
def prerequisites_met(retrofit: str, home: HomeInput, package: Iterable[str]) -> bool
def rate_suitability(cands: list[Candidate], home: HomeInput, package: Iterable[str]
                     ) -> dict[str, tuple[float | None, str | None, list[str]]]   # r → (u, suitability, reasons)
def order_retrofits(package: Iterable[str], priority: dict[str, float]) -> list[str]
def depends_on(retrofit: str, package: Iterable[str]) -> list[str]
def budget_filter(ordered_by_u: list[str], budget_gbp: float) -> tuple[list[str], list[str]]  # (kept, dropped)

# core/value.py  [WS-D]
def assemble_value(*, current_value_gbp: float | None, rating_before: str | None, rating_after: str | None,
                   sap_before: float | None, sap_after: float | None,
                   log_prices: np.ndarray | None) -> ValueResult
    # log_prices shape (n_ensemble, 2): column 0 = before, 1 = after. None → status "insufficient".

# core/orchestrator.py  [T2.1]
class Engine:
    @classmethod
    def from_config(cls, models: Models | None = None) -> Engine
    def analyse(self, home: HomeInput, ctx: CustomerContext | None = None) -> AnalysisResult
    def run_scenario(self, home: HomeInput, scenario: Scenario, ctx: CustomerContext | None = None) -> AnalysisResult
    def portfolio(self, split: str = "test", limit: int | None = None) -> list[dict]
```

## Decisions made while building (not in the team guide)
- `config/engine.yaml` [P2] holds validation/annualise/value thresholds, SAP band ranges, area bands, stage
  order and placeholder peer percentiles; `config/imputation.yaml` [P1 values, P2 schema] holds imputation
  tables. Both are needed by "no magic numbers".
- `score.yaml` gains `score_range.rating_band_spread` and `suitability` (D13 names that block).
- Catalogue entries gain `state_field` (which field the `effect_range_frac` keys refer to).
- `contracts.py` tightens two patterns from the §7.1 conventions (`property_id` `^P\d{5,}$`, month `01–12`)
  and rejects NaN/Infinity in numeric inputs. Field names are unchanged.
- Improvement potential always refers to the full feasible package (PS definition), also inside scenarios;
  `savings.saving` refers to `savings.retrofits`.
- `CONFLICT_HEATING_VS_GAS` fires only when the user stated the heating system (an imputed boiler must not
  contradict a real all-electric home), matching the user-given rule for rating and age conflicts.
- `_E` enums are `StrEnum`s that hash like their value, so members and plain strings are interchangeable as
  dict keys (AgeBand member names differ from their values).
- Part 5 change requests CR-1…CR-8 (`P5_change_requests.md`) folded in before the freeze, still
  `CONTRACT_VERSION` 1.0.0: memory payload models + `ChatResponse.memory_proposal` (CR-1); `ResultDiff` +
  `core/diff.py::diff_results` + `ChatResponse.diff` (CR-2); `AnalysisResult.peer` (CR-3, band names match
  config: `lt50…gt200`, `property_type` nullable); `portfolio()` → `list[PortfolioRow]` (CR-4);
  `analysis_id` includes ctx (CR-5); engine applies every `CustomerContext` rule incl. `priority` →
  `score.yaml: suitability.priority_weights` (CR-6, budget uses net mid cost, not `cost_high`);
  `format.py` CR-8 names, "—" for unknown, `/year` units, `fmt_delta` (CR-8).
- P1 config compatibility: P1-generated files load with `extra="ignore"` (their extra keys are documentation);
  P2-owned files stay `extra="forbid"`. Catalogue `applies_to` (alias of README's `applies_to_end_use`);
  `state_field` derived from a fixed retrofit → field map when absent; national `hdd_factor` = 1.0 by
  definition, national PV yield/profile = regional mean; region share tolerance 1e-3 (P1 writes 5 dp).
- Retrofit costs are flat indicative ranges (P1: "typical semi"); `cost_scales_with_floor_area` is not applied
  because no reference floor area is defined.
- Stub solar = kWp(type) × regional PV yield × mid self-consumption, capped at grid import (P1 catalogue gives
  kWp, not a fractional effect).
- `tests/conftest.py` puts its own directory on `sys.path`, so `from conftest import …` works whether or not
  `tests/` has an `__init__.py`.
- `CONTRACT_VERSION` 1.1.0 (PR #1 review): `ResultDiff` adds `score_after` / `class_after` rows; `score` /
  `score_class` stay (they move only with overrides). Fixtures regenerated.
- In every result, `rank` and `incremental_saving` describe the reported package (recommended, custom or
  none), so incremental savings always sum to `savings.saving` (IT3).
