"""Shared contracts: every enum and pydantic model exchanged between parts (README §7.2, §7.3).

Field names are binding. Any change after the H+2 freeze needs a CONTRACT_VERSION bump, regenerated
fixtures (`uv run python tests/fixtures/generate.py`) and an announcement in the team channel.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0.0"


class _E(StrEnum):
    """String enum base: members compare equal to their lower_snake_case value."""

    def __hash__(self) -> int:
        # Hash like the plain string so members and values are interchangeable as dict keys
        # (AgeBand member names differ from their values, e.g. b1950_1966 / "1950_1966").
        return hash(self.value)


# ---------- ENUMS (§7.2) ----------
class PropertyType(_E):
    detached = "detached"
    semi_detached = "semi_detached"
    terraced = "terraced"
    flat = "flat"
    bungalow = "bungalow"
    maisonette = "maisonette"


class AgeBand(_E):
    pre_1900 = "pre_1900"
    b1900_1929 = "1900_1929"
    b1930_1949 = "1930_1949"
    b1950_1966 = "1950_1966"
    b1967_1982 = "1967_1982"
    b1983_1995 = "1983_1995"
    b1996_2006 = "1996_2006"
    b2007_onwards = "2007_onwards"


class Region(_E):
    north_east = "north_east"
    north_west = "north_west"
    yorkshire_humber = "yorkshire_humber"
    east_midlands = "east_midlands"
    west_midlands = "west_midlands"
    east_of_england = "east_of_england"
    london = "london"
    south_east = "south_east"
    south_west = "south_west"
    wales = "wales"


class EnergyRating(_E):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class RoofType(_E):
    pitched_loft = "pitched_loft"
    flat_roof = "flat_roof"
    room_in_roof = "room_in_roof"
    dwelling_above = "dwelling_above"


class RoofInsulation(_E):
    none = "none"
    low = "low"
    medium = "medium"
    full = "full"


class WallType(_E):
    cavity = "cavity"
    solid = "solid"
    timber_or_system = "timber_or_system"


class WallInsulation(_E):
    none = "none"
    partial = "partial"
    full = "full"


class Glazing(_E):
    single = "single"
    partial_double = "partial_double"
    secondary = "secondary"
    double = "double"
    triple = "triple"


class HeatingSystem(_E):
    heat_pump = "heat_pump"
    gas_boiler_condensing = "gas_boiler_condensing"
    gas_boiler_old = "gas_boiler_old"
    electric_storage = "electric_storage"
    electric_direct = "electric_direct"
    other_fuel_boiler = "other_fuel_boiler"


class MainFuel(_E):
    mains_gas = "mains_gas"
    electricity = "electricity"
    other = "other"


class Renewables(_E):
    none = "none"
    solar_thermal = "solar_thermal"
    solar_pv = "solar_pv"
    solar_pv_battery = "solar_pv_battery"


class SmartControls(_E):
    none = "none"
    timer_only = "timer_only"
    programmer_thermostat = "programmer_thermostat"
    programmer_thermostat_trvs = "programmer_thermostat_trvs"
    smart_thermostat = "smart_thermostat"
    smart_zoned = "smart_zoned"


class Retrofit(_E):
    loft_insulation = "loft_insulation"
    cavity_wall_insulation = "cavity_wall_insulation"
    solid_wall_insulation = "solid_wall_insulation"
    double_glazing = "double_glazing"
    air_source_heat_pump = "air_source_heat_pump"
    solar_pv = "solar_pv"
    smart_thermostat = "smart_thermostat"


class Feasibility(_E):
    feasible = "feasible"
    needs_survey = "needs_survey"
    infeasible = "infeasible"


class Suitability(_E):
    high = "high"
    medium = "medium"
    low = "low"


class ScoreClass(_E):
    highly_efficient = "highly_efficient"
    good = "good"
    moderate = "moderate"
    poor = "poor"
    very_poor = "very_poor"


class Provenance(_E):
    user = "user"
    example = "example"
    imputed = "imputed"
    assumed = "assumed"
    derived = "derived"


class FlagSeverity(_E):
    info = "info"
    warning = "warning"
    error = "error"


class Split(_E):
    train = "train"
    val = "val"
    test = "test"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, use_enum_values=True)


# ---------- INPUT ----------
class MonthlyReading(Strict):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    electricity_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    gas_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class EnergyInput(Strict):
    annual_electricity_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    annual_gas_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    monthly: list[MonthlyReading] | None = None  # if given, takes precedence when coverage ok


class HomeInput(Strict):
    property_id: str | None = Field(default=None, pattern=r"^P\d{5,}$")  # set when loaded from examples
    customer_id: str | None = Field(default=None, pattern=r"^C\d{5,}$")
    property_type: PropertyType | None = None
    age_band: AgeBand | None = None
    floor_area_m2: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    region: Region | None = None
    current_value_gbp: float | None = Field(default=None, gt=0, allow_inf_nan=False)  # user's estimate
    energy_rating: EnergyRating | None = None
    roof_type: RoofType | None = None
    roof_insulation: RoofInsulation | None = None
    wall_type: WallType | None = None
    wall_insulation: WallInsulation | None = None
    glazing: Glazing | None = None
    heating_system: HeatingSystem | None = None
    main_fuel: MainFuel | None = None
    renewables: Renewables | None = None
    smart_controls: SmartControls | None = None
    listed_or_conservation: Literal["yes", "no"] | None = None
    outdoor_space: Literal["yes", "no"] | None = None  # heat pump unit siting
    energy: EnergyInput = EnergyInput()


# ---------- CLEANED ----------
class DataFlag(Strict):
    code: str  # from the flag code list in README P2.2
    severity: FlagSeverity
    field: str | None = None
    message: str  # short human text (UI + LLM DATA_NOTES)
    evidence: dict[str, Any] = {}


class AnnualEnergy(Strict):
    electricity_kwh: float | None
    gas_kwh: float | None
    purchased_kwh: float | None  # None if either component unavailable
    electricity_coverage: float | None  # 0–1 seasonal-share coverage
    gas_coverage: float | None
    source: Literal["monthly", "annual", "imputed", "none"]


class CleanHome(Strict):
    home: HomeInput  # post-cleaning values (imputed values filled in)
    provenance: dict[str, Provenance]  # field name → provenance
    energy: AnnualEnergy
    intensity_kwh_m2: float | None
    sap_estimate: float | None  # from M4 (anchored to band if given)
    flags: list[DataFlag]
    in_savings_scope: bool  # False for main_fuel == other


# ---------- SCORE ----------
ScoreKey = Literal[
    "energy_efficiency", "consumption_intensity", "insulation", "heating",
    "glazing", "renewables", "smart_controls",
]


class ScoreComponent(Strict):
    key: ScoreKey
    weight: float  # fraction
    sub_score: float  # 0–100, unrounded
    contribution: float  # weight * sub_score, unrounded
    inputs: dict[str, Any]  # e.g. {"energy_rating": "E"}
    provenance: Provenance  # worst provenance among its inputs
    sub_score_range: tuple[float, float] | None = None  # if inputs unknown


class ScoreResult(Strict):
    status: Literal["ok", "insufficient"]
    score: int | None
    score_raw: float | None
    score_class: ScoreClass | None
    score_range: tuple[int, int] | None
    components: list[ScoreComponent]
    method_version: str  # from config/score.yaml


# ---------- ISSUES ----------
class Issue(Strict):
    code: str  # e.g. SINGLE_GLAZING
    severity: Literal["high", "medium", "low"]
    component: str | None
    message: str
    evidence: dict[str, Any] = {}


# ---------- ENERGY / SAVINGS ----------
class FuelEnergy(Strict):
    electricity_kwh: float
    gas_kwh: float
    purchased_kwh: float


class FuelSaving(Strict):  # positive = reduction
    electricity_kwh: float
    gas_kwh: float
    net_kwh: float  # electricity + gas


class RetrofitRecommendation(Strict):
    retrofit: Retrofit
    rank: int | None  # None if not in the reported package
    feasibility: Feasibility
    suitability: Suitability | None
    reasons: list[str]  # reason codes, see README P2.7
    depends_on: list[Retrofit]
    standalone_saving: FuelSaving | None
    incremental_saving: FuelSaving | None  # in recommended order; sums to package
    standalone_carbon_kg: float | None
    cost_low_gbp: float | None
    cost_high_gbp: float | None
    assessor_likelihood: float | None  # M2 probability 0–1


class SavingsResult(Strict):
    status: Literal["ok", "insufficient", "out_of_scope"]
    retrofits: list[Retrofit]
    baseline: FuelEnergy | None
    after: FuelEnergy | None
    saving: FuelSaving | None
    improvement_potential_pct: float | None
    saving_low: FuelSaving | None = None  # STRETCH: quantile models
    saving_high: FuelSaving | None = None


class CarbonResult(Strict):
    electricity_kg: float  # ΔE_elec * EF_elec
    gas_kg: float
    total_kg: float
    ef_electricity: float  # kg CO2e/kWh
    ef_gas: float
    ef_source: str  # e.g. "DESNZ GHG conversion factors 2025"


class ValueResult(Strict):
    status: Literal["ok", "insufficient"]
    current_value_gbp: float | None
    current_value_source: Literal["user", "model"] | None
    rating_before: EnergyRating | None
    rating_after: EnergyRating | None
    sap_before: float | None
    sap_after: float | None
    uplift_pct_low: float | None
    uplift_pct_mid: float | None
    uplift_pct_high: float | None
    value_low_gbp: float | None
    value_high_gbp: float | None
    caveat_code: Literal["indicative_not_causal"] = "indicative_not_causal"


class Scenario(Strict):
    name: str = "recommended"
    mode: Literal["recommended", "custom", "none"] = "recommended"
    retrofits: list[Retrofit] = []  # used when mode == custom
    overrides: dict[str, Any] = {}  # HomeInput field → value (e.g. {"glazing": "double"})


class RejectedRetrofit(Strict):
    retrofit: Retrofit
    reason: str  # reason code


FloorAreaBand = Literal["lt50", "50_90", "90_130", "130_200", "gt200"]


class PeerComparison(Strict):  # CR-3
    intensity_kwh_m2: float
    property_type: PropertyType | None  # None → peer group is the floor-area band only
    floor_area_band: FloorAreaBand
    p50_kwh_m2: float
    p75_kwh_m2: float
    p90_kwh_m2: float


class AnalysisResult(Strict):
    contract_version: str
    analysis_id: str  # sha256 of canonical input + scenario + model versions
    model_versions: dict[str, str]
    home: CleanHome
    score: ScoreResult
    issues: list[Issue]
    is_poor: bool | None
    recommendations: list[RetrofitRecommendation]  # all 7, infeasible ones at the end
    scenario: Scenario
    rejected: list[RejectedRetrofit]  # scenario items that were infeasible
    savings: SavingsResult
    carbon: CarbonResult | None
    value: ValueResult
    score_after: ScoreResult | None
    flags: list[DataFlag]  # all flags (cleaning + model-stage)
    peer: PeerComparison | None = None  # None if intensity is unavailable or energy was imputed


# ---------- DIFF (CR-2) ----------
DiffKey = Literal[
    "score", "score_class", "electricity_kwh", "gas_kwh", "net_kwh", "improvement_potential_pct",
    "carbon_total_kg", "value_uplift_pct_mid", "rating_after", "sap_after",
]


class DiffRow(Strict):
    key: DiffKey
    unit: Literal["score", "class", "kwh_per_year", "pct", "kg_per_year", "rating", "sap"]
    base: float | str | None
    new: float | str | None
    delta: float | None  # new − base for numeric keys; None for class/rating or if either side is None


class ResultDiff(Strict):
    base_analysis_id: str
    new_analysis_id: str
    rows: list[DiffRow]  # always all 10 keys, in DiffKey order
    retrofits_added: list[Retrofit]  # in new.savings.retrofits, not in base
    retrofits_removed: list[Retrofit]


# ---------- PORTFOLIO (CR-4) ----------
class PortfolioRow(Strict):
    rank: int  # 1 = highest improvement potential
    property_id: str
    customer_id: str | None
    region: Region | None
    property_type: PropertyType | None
    score: int | None
    score_class: ScoreClass | None
    is_poor: bool | None
    improvement_potential_pct: float | None  # None sorts last
    key_issues: list[str]  # up to 3 issue codes, high → low severity
    savings_status: Literal["ok", "insufficient", "out_of_scope"]


class PortfolioResponse(Strict):
    split: Split
    generated_at: str
    model_versions: dict[str, str]
    total: int
    rows: list[PortfolioRow]


# ---------- CHAT / MEMORY ----------
class CompletedRetrofitPayload(Strict):  # CR-1
    kind: Literal["completed_retrofit"] = "completed_retrofit"
    retrofit: Retrofit
    completed_on: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class ExcludeConstraintPayload(Strict):
    kind: Literal["exclude"] = "exclude"
    retrofit: Retrofit


class BudgetConstraintPayload(Strict):
    kind: Literal["budget"] = "budget"
    max_budget_gbp: float = Field(gt=0, allow_inf_nan=False)


class PreferencePayload(Strict):
    kind: Literal["preference"] = "preference"
    priority: Literal["carbon", "bills", "value", "balanced"]


class RecommendationShownPayload(Strict):
    kind: Literal["recommendation_shown"] = "recommendation_shown"
    analysis_id: str
    ranked_retrofits: list[Retrofit]  # feasible ones, in rank order, as shown


class ResponsePayload(Strict):
    kind: Literal["response"] = "response"
    retrofit: Retrofit
    response: Literal["accepted", "declined"]


MemoryPayload = Annotated[
    CompletedRetrofitPayload | ExcludeConstraintPayload | BudgetConstraintPayload
    | PreferencePayload | RecommendationShownPayload | ResponsePayload,
    Field(discriminator="kind"),
]


class MemoryEventIn(Strict):
    payload: MemoryPayload


class MemoryEvent(Strict):
    id: int
    customer_id: str
    ts: str  # ISO 8601 UTC, e.g. 2026-10-10T14:03:00Z
    payload: MemoryPayload


class CustomerContext(Strict):
    customer_id: str
    completed_retrofits: list[Retrofit] = []
    excluded_retrofits: list[Retrofit] = []
    declined_retrofits: list[Retrofit] = []
    max_budget_gbp: float | None = None
    priority: Literal["carbon", "bills", "value", "balanced"] = "balanced"


class CheckReport(Strict):
    passed: bool
    numbers_found: list[str]
    unsupported: list[str]
    banned_phrases: list[str]
    attempts: int
    fallback_used: bool


class ChatRequest(Strict):
    session_id: str
    home: HomeInput
    message: str
    current_scenario: Scenario | None = None
    customer_id: str | None = None


class ChatResponse(Strict):
    answer: str
    intent: Literal["whatif", "explain", "memory", "out_of_scope", "unclear"]
    scenario: Scenario | None
    result: AnalysisResult | None
    base_result_id: str | None
    check: CheckReport
    memory_proposal: list[MemoryEventIn] | None = None  # set only when intent == "memory" (CR-1)
    diff: ResultDiff | None = None  # CR-2


# Ordered list of HomeInput fields that describe the dwelling (not ids, value or energy).
FEATURE_FIELDS: tuple[str, ...] = (
    "property_type", "age_band", "floor_area_m2", "bedrooms", "region", "energy_rating",
    "roof_type", "roof_insulation", "wall_type", "wall_insulation", "glazing", "heating_system",
    "main_fuel", "renewables", "smart_controls", "listed_or_conservation", "outdoor_space",
)
