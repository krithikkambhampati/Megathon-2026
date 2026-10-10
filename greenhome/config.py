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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from greenhome.contracts import (
    CONTRACT_VERSION,
    AgeBand,
    EnergyRating,
    Retrofit,
    WallInsulation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOOR_AREA_BANDS: tuple[str, ...] = ("lt50", "50_90", "90_130", "130_200", "gt200")
_SHARE_TOL = 1e-6


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


class IntensityBounds(_Cfg):
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
class Prerequisite(_Cfg):
    insulation_sub_score_min: float
    or_in_package_any: list[Retrofit] = []


class RetrofitSpec(_Cfg):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)
    retrofit: Retrofit
    stage: str
    applies_to_end_use: str
    state_field: str | None = None
    effect_range_frac: dict[str, tuple[float, float]] | None = None
    scop_range: tuple[float, float] | None = None
    cost_gbp: tuple[float, float]
    grant_gbp: float = 0.0
    lifetime_years: int
    prerequisites: list[Prerequisite] = []
    soft_after: list[Retrofit] = []
    source: str
    notes: str | None = None

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
class EmissionFactor(_Cfg):
    fuel: Literal["electricity", "gas"]
    kg_co2e_per_kwh: float = Field(gt=0)
    source: str
    year: int
    scope: str | None = None
    basis: str | None = None


# ---------- regions.yaml ----------
class RegionCfg(_Cfg):
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


class RegionsFile(_Cfg):
    model_config = ConfigDict(extra="ignore", frozen=True)  # allows YAML anchor blocks like `_shares`
    national: RegionCfg
    regions: dict[str, RegionCfg]
    local_authority_to_region: dict[str, str] = {}


# ---------- imputation.yaml ----------
class FeatureModeCfg(_Cfg):
    default: dict[str, str] = Field(alias="_default")
    by_age_band: dict[AgeBand, dict[str, str]] = {}
    by_property_type: dict[str, dict[str, str]] = {}


class ImputationCfg(_Cfg):
    floor_area_m2: dict[str, list[float]]
    feature_mode: FeatureModeCfg
    typical_energy_kwh: dict[str, dict[str, dict[Literal["electricity_kwh", "gas_kwh"], float]]]


# ---------- root ----------
class Config:
    """All configuration, loaded once. Attribute access only; never mutate."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.global_ = GlobalCfg.model_validate(_load(root / "global.yaml"))
        self.score = ScoreCfg.model_validate(_load(root / "score.yaml"))
        self.engine = EngineCfg.model_validate(_load(root / "engine.yaml"))
        self.imputation = ImputationCfg.model_validate(_load(root / "imputation.yaml"))
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
        self.national = regions.national
        self.regions: dict[str, RegionCfg] = regions.regions
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
        """lt50 · 50_90 · 90_130 · 130_200 · gt200 (lower edge inclusive)."""
        for edge, band in zip(self.engine.floor_area_band_edges, FLOOR_AREA_BANDS, strict=False):
            if floor_area_m2 < edge:
                return band
        return FLOOR_AREA_BANDS[-1]

    def peers(self, property_type: str | None, floor_area_m2: float) -> dict[str, float]:
        """Peer intensity percentiles {p10, p50, p75, p90} for (property_type, floor-area band).

        Reads P1's train-split `config/generated/peer_percentiles.parquet` when it exists.
        # ponytail: placeholder table keyed by area band only until P1 delivers the parquet (D10).
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
        return {
            (str(r["property_type"]), str(r["floor_area_band"])): {c: float(r[c]) for c in cols}
            for _, r in df.iterrows()
        }

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
