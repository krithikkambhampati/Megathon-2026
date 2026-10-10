"""Typed, cached loader for everything in `config/` (README §7.4). No magic numbers live in code.

Usage:
    from greenhome.config import get_config
    cfg = get_config()
    cfg.score.weights["glazing"]          # 0.10
    cfg.catalogue["loft_insulation"].cost_gbp
    cfg.peers("flat", 62.0)["p90"]

`GREENHOME_CONFIG_DIR` overrides the config directory (tests use it for alternative configs).
"""

from __future__ import annotations

import math
import os
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from greenhome.contracts import (
    CONTRACT_VERSION,
    AgeBand,
    EnergyRating,
    Retrofit,
    WallInsulation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOOR_AREA_BANDS: tuple[str, ...] = ("lt50", "50_90", "90_130", "130_200", "gt200")
# P1's peer_percentiles.parquet labels the same bands differently.
_P1_PEER_BANDS = {"<50": "lt50", "50-90": "50_90", "90-130": "90_130", "130-200": "130_200", ">200": "gt200"}
# NEED floor-area bands used by P1's typical-energy table (upper edge inclusive, as NEED's "50 or less").
_ENERGY_BANDS: tuple[tuple[float, str], ...] = (
    (50, "<50"), (100, "50-100"), (150, "100-150"), (200, "150-200"),
)
_ENERGY_BAND_ORDER = ("<50", "50-100", "100-150", "150-200", ">200")
_SHARE_TOL = 1e-3  # P1 writes shares to 5 dp, so sums can be off by ~1e-5


class _Cfg(BaseModel):
    """P2-owned config: unknown keys are errors, so typos fail loudly."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class _P1Cfg(BaseModel):
    """P1-generated config: extra keys are documentation/provenance (source_status, desnz_id, …) → ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)


# ---------- global.yaml ----------
class PathsCfg(_Cfg):
    data_processed: str
    models: str
    examples: str


class GlobalCfg(_Cfg):
    contract_version: str
    seed: int
    as_of_date: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    models: Literal["stub", "real"]
    paths: PathsCfg

    @field_validator("contract_version")
    @classmethod
    def _matches_contracts(cls, v: str) -> str:
        if v != CONTRACT_VERSION:
            raise ValueError(
                f"global.yaml contract_version {v} != contracts.CONTRACT_VERSION {CONTRACT_VERSION}"
            )
        return v


# ---------- score.yaml ----------
class ScoreClassBand(_Cfg):
    class_: str = Field(alias="class")
    min: int


class InsulationCfg(_Cfg):
    roof_weight: float
    wall_weight: float
    roof: dict[str, float]
    wall: dict[str, float | dict[str, float]]


class SuitabilityReasonsCfg(_Cfg):
    high_saving_share: float
    low_saving_share: float
    high_cost_gbp: float
    quick_win_cost_max_gbp: float
    assessor_often: float


Priority = Literal["balanced", "carbon", "bills", "value"]


class SuitabilityCfg(_Cfg):
    priority_weights: dict[Priority, dict[Literal["assessor", "saving_share", "cost_eff"], float]]
    high: float
    medium: float
    reasons: SuitabilityReasonsCfg


class ScoreCfg(_Cfg):
    method_version: str
    weights: dict[str, float]
    classes: list[ScoreClassBand]
    energy_efficiency: dict[str, float]
    intensity_bounds_file: str
    insulation: InsulationCfg
    heating: dict[str, float]
    glazing: dict[str, float]
    renewables: dict[str, float]
    smart_controls: dict[str, float]
    min_info: dict[str, int]
    score_range: dict[str, int]
    suitability: SuitabilityCfg

    @model_validator(mode="after")
    def _check(self) -> ScoreCfg:
        if not math.isclose(sum(self.weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("score weights must sum to 1.0")
        pw = self.suitability.priority_weights
        if set(pw) != set(Priority.__args__) or any(
            not math.isclose(sum(w.values()), 1.0, abs_tol=1e-9) or len(w) != 3 for w in pw.values()
        ):
            raise ValueError("suitability.priority_weights: all 4 priorities, 3 weights each summing to 1")
        mins = [c.min for c in self.classes]
        if mins != sorted(mins, reverse=True) or mins[-1] != 0:
            raise ValueError("score classes must be ordered by descending min and end at 0")
        return self


class IntensityBounds(_P1Cfg):
    i_best: float
    i_worst: float

    @model_validator(mode="after")
    def _check(self) -> IntensityBounds:
        if not self.i_worst > self.i_best >= 0:
            raise ValueError("intensity bounds need i_worst > i_best >= 0")
        return self


# ---------- engine.yaml ----------
class AnnualiseCfg(_Cfg):
    months_window: int
    coverage_ok: float
    coverage_min: float
    conflict_rel_diff: float


class ValidationCfg(_Cfg):
    score_feature_fields: list[str]
    gas_heating_min_gas_kwh: float
    non_gas_heating_max_gas_kwh: float
    area_per_bedroom_min: float
    area_per_bedroom_max: float
    intensity_min_kwh_m2: float
    intensity_max_peer_p90_multiple: float
    value_min_gbp: float
    value_max_gbp: float


class ValueCfg(_Cfg):
    quantiles: tuple[float, float, float]
    min_half_width_pct: float


class EngineCfg(_Cfg):
    sap_bands: dict[str, tuple[int, int]]
    floor_area_band_edges: tuple[float, float, float, float]
    stage_order: list[str]
    annualise: AnnualiseCfg
    validation: ValidationCfg
    value: ValueCfg
    peers_fallback: dict[str, dict[str, float]]


# ---------- retrofit_catalogue.yaml ----------
class Prerequisite(_P1Cfg):
    insulation_sub_score_min: float
    or_in_package_any: list[Retrofit] = []


# Which HomeInput field an `effect_range_frac` table is keyed by (P1's catalogue leaves it implicit).
_STATE_FIELD = {
    "loft_insulation": "roof_insulation",
    "cavity_wall_insulation": "wall_insulation",
    "solid_wall_insulation": "wall_insulation",
    "double_glazing": "glazing",
    "smart_thermostat": "smart_controls",
    "solar_pv": "renewables",
}


class RetrofitSpec(_P1Cfg):
    model_config = ConfigDict(extra="ignore", frozen=True, use_enum_values=True)
    retrofit: Retrofit
    stage: str
    # space_heating | heat_supply | grid_import (P1); README §7.4 called it applies_to_end_use
    applies_to: str = Field(validation_alias=AliasChoices("applies_to", "applies_to_end_use"))
    state_field: str | None = None
    effect_range_frac: dict[str, tuple[float, float]] | None = None
    scop_range: tuple[float, float] | None = None
    kwp_by_property_type: dict[str, float] | None = None  # solar_pv
    self_consumption_frac_range: tuple[float, float] | None = None  # solar_pv
    # Flat indicative range for a typical semi. P1's `cost_scales_with_floor_area` is not applied: no
    # reference floor area is defined and the range already spans typical homes (see SCORING.md).
    cost_gbp: tuple[float, float]
    grant_gbp: float = 0.0
    lifetime_years: int
    prerequisites: list[Prerequisite] = []
    soft_after: list[Retrofit] = []
    source: str
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_state_field(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("state_field") is None:
            data = {**data, "state_field": _STATE_FIELD.get(data.get("retrofit"))}
        return data

    @property
    def cost_mid_gbp(self) -> float:
        return (self.cost_gbp[0] + self.cost_gbp[1]) / 2

    def effect_mid_frac(self, state: str | None) -> float:
        """Midpoint of the documented effect for a starting state; 0.0 if no effect is listed for it."""
        table = self.effect_range_frac or {}
        rng = table.get(state) if state is not None else None
        rng = rng or table.get("default")
        return 0.0 if rng is None else (rng[0] + rng[1]) / 2


# ---------- emission_factors.yaml ----------
class EmissionFactor(_P1Cfg):
    fuel: Literal["electricity", "gas"]
    kg_co2e_per_kwh: float = Field(gt=0)
    source: str
    year: int
    scope: str | None = None
    basis: str | None = None


# ---------- regions.yaml ----------
class RegionCfg(_P1Cfg):
    hdd_factor: float = Field(gt=0)
    pv_yield_kwh_per_kwp: float = Field(gt=0)
    gas_monthly_share: tuple[float, ...]
    elec_monthly_share: tuple[float, ...]
    pv_monthly_share: tuple[float, ...]

    @model_validator(mode="after")
    def _check(self) -> RegionCfg:
        for name in ("gas_monthly_share", "elec_monthly_share", "pv_monthly_share"):
            shares = getattr(self, name)
            if len(shares) != 12 or abs(sum(shares) - 1.0) > _SHARE_TOL:
                raise ValueError(f"{name} must have 12 values summing to 1.0")
        return self


class RegionsFile(_P1Cfg):
    national: dict[str, Any]  # P1 omits fields that only make sense per region; completed in Config
    regions: dict[str, RegionCfg]
    local_authority_to_region: dict[str, str] = {}


# ---------- generated/imputation.yaml (P1, train split only) ----------
class EnergyTypical(_P1Cfg):
    gas_homes_need_median_kwh_by_floor_area: dict[Literal["gas", "electricity"], dict[str, float]]
    # heating_system → NEED band → {median_kwh, n}
    electric_heated_homes_synthetic_median_electricity_kwh: dict[str, dict[str, dict[str, float]]]


class ImputationTables(_P1Cfg):
    """Lookups for "not sure" answers. Every table is P1's; these methods only choose the row."""

    floor_area_by_type_bedrooms: dict[str, dict[str, dict[str, float]]]  # type → "1".."5+" → {median_m2, n}
    feature_mode_by_age_type: dict[str, dict[str, dict[str, Any]]]  # age → type → {n, field: {value, share}}
    energy_typical: EnergyTypical

    def floor_area(self, property_type: str | None, bedrooms: int) -> float | None:
        """Median floor area for (type, bedrooms); unknown type → n-weighted mean over types."""
        key = "5+" if bedrooms >= 5 else str(max(bedrooms, 1))
        table = self.floor_area_by_type_bedrooms
        rows = [table[property_type][key]] if property_type in table and key in table[property_type] else [
            t[key] for t in table.values() if key in t
        ]
        n = sum(r["n"] for r in rows)
        return sum(r["median_m2"] * r["n"] for r in rows) / n if n else None

    def feature_mode(self, age_band: str | None, property_type: str | None) -> dict[str, str]:
        """Most common value per field for the (age, type) cell; when either is unknown (or the cell is
        missing), the value covering the most homes across the matching cells (votes = n × share)."""
        cells = [
            cell for age, by_type in self.feature_mode_by_age_type.items() for pt, cell in by_type.items()
            if (age_band is None or age == age_band) and (property_type is None or pt == property_type)
        ] or [cell for by_type in self.feature_mode_by_age_type.values() for cell in by_type.values()]
        votes: dict[str, dict[str, float]] = {}
        for cell in cells:
            for field, mode in cell.items():
                if isinstance(mode, dict):
                    tally = votes.setdefault(field, {})
                    tally[mode["value"]] = tally.get(mode["value"], 0.0) + cell["n"] * mode["share"]
        return {f: max(v, key=lambda k: (v[k], k)) for f, v in votes.items()}

    def typical_energy(
        self, main_fuel: str | None, heating_system: str | None, floor_area_m2: float
    ) -> tuple[dict[str, float], str] | None:
        """({electricity_kwh, gas_kwh}, NEED band) for a typical similar home, or None (off-gas / unknown)."""
        band = next((label for edge, label in _ENERGY_BANDS if floor_area_m2 <= edge), _ENERGY_BAND_ORDER[-1])
        et = self.energy_typical
        if main_fuel == "mains_gas":
            g = et.gas_homes_need_median_kwh_by_floor_area
            return {"electricity_kwh": g["electricity"][band], "gas_kwh": g["gas"][band]}, band
        table = et.electric_heated_homes_synthetic_median_electricity_kwh.get(heating_system or "")
        if main_fuel != "electricity" or not table:
            return None
        # Sparse bands (P1 keeps n ≥ 30 only) fall back to the nearest band that exists.
        i = _ENERGY_BAND_ORDER.index(band)
        nearest = min(table, key=lambda b: abs(_ENERGY_BAND_ORDER.index(b) - i))
        return {"electricity_kwh": table[nearest]["median_kwh"], "gas_kwh": 0.0}, nearest


# ---------- root ----------
class Config:
    """All configuration, loaded once. Attribute access only; never mutate."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.global_ = GlobalCfg.model_validate(_load(root / "global.yaml"))
        self.score = ScoreCfg.model_validate(_load(root / "score.yaml"))
        self.engine = EngineCfg.model_validate(_load(root / "engine.yaml"))
        self.imputation = ImputationTables.model_validate(_load(root / "generated" / "imputation.yaml"))
        self.intensity_bounds = IntensityBounds.model_validate(
            _load(self._resolve(self.score.intensity_bounds_file))
        )
        specs = [RetrofitSpec.model_validate(x) for x in _load(root / "retrofit_catalogue.yaml")]
        self.catalogue: dict[str, RetrofitSpec] = {s.retrofit: s for s in specs}
        if set(self.catalogue) != {r.value for r in Retrofit}:
            raise ValueError("retrofit_catalogue.yaml must define exactly the 7 retrofits in §7.2")
        efs = [EmissionFactor.model_validate(x) for x in _load(root / "emission_factors.yaml")]
        self.emission_factors: dict[str, EmissionFactor] = {e.fuel: e for e in efs}
        regions = RegionsFile.model_validate(_load(root / "regions.yaml"))
        self.regions: dict[str, RegionCfg] = regions.regions
        national = _complete_national(regions.national, list(self.regions.values()))
        self.national = RegionCfg.model_validate(national)
        if set(self.engine.sap_bands) != {r.value for r in EnergyRating}:
            raise ValueError("engine.yaml sap_bands must cover bands A–G")

    def _resolve(self, rel: str) -> Path:
        """Paths in config are repo-relative (`config/...`); fall back to config-dir-relative."""
        p = REPO_ROOT / rel
        return p if p.exists() else self.root / Path(rel).name

    def region(self, region: str | None) -> RegionCfg:
        """Region block, or the national average when the region is unknown."""
        return self.regions.get(region, self.national) if region else self.national

    def floor_area_band(self, floor_area_m2: float) -> str:
        """lt50 · 50_90 · 90_130 · 130_200 · gt200 (upper edge inclusive, matching P1's pd.cut bands)."""
        for edge, band in zip(self.engine.floor_area_band_edges, FLOOR_AREA_BANDS, strict=False):
            if floor_area_m2 <= edge:
                return band
        return FLOOR_AREA_BANDS[-1]

    def peers(self, property_type: str | None, floor_area_m2: float) -> dict[str, float]:
        """Peer intensity percentiles {p10, p50, p75, p90} for (property_type, floor-area band).

        Reads P1's train-split `config/generated/peer_percentiles.parquet` when it exists (P1 commits it);
        otherwise the placeholder `engine.yaml: peers_fallback`, keyed by area band only.
        """
        band = self.floor_area_band(floor_area_m2)
        row = self._peer_table.get((property_type, band)) if property_type else None
        return row or self.engine.peers_fallback[band]

    @cached_property
    def _peer_table(self) -> dict[tuple[str, str], dict[str, float]]:
        path = self.root / "generated" / "peer_percentiles.parquet"
        if not path.exists():
            return {}
        import pandas as pd

        df = pd.read_parquet(path)
        cols = [c for c in ("p10", "p50", "p75", "p90") if c in df.columns]
        table = {}
        for _, r in df.iterrows():
            band = str(r["floor_area_band"])
            table[(str(r["property_type"]), _P1_PEER_BANDS.get(band, band))] = {c: float(r[c]) for c in cols}
        return table

    def quality_order(self, field: str) -> list[str]:
        """Enum values of a quality-ordered field, worst → best (used for ordinals and monotonicity).

        Order comes from the score tables, so features, tests and docs can never disagree with the score.
        """
        if field == "wall_insulation":
            return [w.value for w in WallInsulation]
        if field == "age_band":
            return [a.value for a in AgeBand]
        table = {
            "energy_rating": self.score.energy_efficiency,
            "roof_insulation": self.score.insulation.roof,
            "heating_system": self.score.heating,
            "glazing": self.score.glazing,
            "renewables": self.score.renewables,
            "smart_controls": self.score.smart_controls,
        }[field]
        return sorted(table, key=lambda k: (table[k], k))

    @property
    def models_dir(self) -> Path:
        return REPO_ROOT / self.global_.paths.models

    @property
    def data_dir(self) -> Path:
        return REPO_ROOT / self.global_.paths.data_processed

    @property
    def examples_dir(self) -> Path:
        return REPO_ROOT / self.global_.paths.examples


def _complete_national(national: dict[str, Any], regions: list[RegionCfg]) -> dict[str, Any]:
    """Fill national fields P1 does not write: hdd_factor is 1.0 by definition (regional factors are relative
    to the national mean); PV yield and monthly profile are the mean over regions."""
    n = len(regions)
    pv_share = [sum(r.pv_monthly_share[m] for r in regions) / n for m in range(12)]
    return {
        "hdd_factor": 1.0,
        "pv_yield_kwh_per_kwp": sum(r.pv_yield_kwh_per_kwp for r in regions) / n,
        "pv_monthly_share": pv_share,
        **national,
    }


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=4)
def _cached(root: str) -> Config:
    return Config(Path(root))


def get_config(root: str | Path | None = None) -> Config:
    """Cached config for `root` (default: $GREENHOME_CONFIG_DIR or <repo>/config)."""
    root = root or os.environ.get("GREENHOME_CONFIG_DIR") or REPO_ROOT / "config"
    return _cached(str(Path(root).resolve()))
