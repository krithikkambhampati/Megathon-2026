"""Engine: the single entry point for P4/P5 (BUILD_GUIDE §4.2, §4.3, §7.7, P2.8).

    engine = Engine.from_config()
    res = engine.analyse(home, ctx=None)
    res2 = engine.run_scenario(home, Scenario(mode="custom", retrofits=["loft_insulation"]))
    rows = engine.portfolio(split="test", limit=50)

Model budget per call: rating ×2 (validate, before/after), recommender ×1, energy ×2 (standalone,
prefixes + full package), value ×1. All batched.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from greenhome.config import Config, get_config
from greenhome.contracts import (
    CONTRACT_VERSION,
    AnalysisResult,
    AnnualEnergy,
    CleanHome,
    CustomerContext,
    DataFlag,
    FuelEnergy,
    FuelSaving,
    HomeInput,
    PeerComparison,
    PortfolioRow,
    RejectedRetrofit,
    Retrofit,
    RetrofitRecommendation,
    SavingsResult,
    Scenario,
    ScoreResult,
    Suitability,
)
from greenhome.core.carbon import compute_carbon
from greenhome.core.feasibility import feasible_set
from greenhome.core.issues import detect_issues
from greenhome.core.ordering import Candidate, budget_filter, depends_on, order_retrofits, rate_suitability
from greenhome.core.score import compute_score
from greenhome.core.transitions import apply_retrofits
from greenhome.core.validate import anchor_sap, band_for_sap, validate_and_clean
from greenhome.core.value import assemble_value
from greenhome.ml.protocols import Models
from greenhome.ml.stubs import load_stub_models

UNKNOWN_PROVENANCE = frozenset({"imputed", "assumed"})
RETROFITS: tuple[str, ...] = tuple(r.value for r in Retrofit)
# Abs tolerance (kWh) for the telescoping check; float noise only, the identity is exact algebraically.
_TELESCOPE_TOL_KWH = 1e-6


class Engine:
    def __init__(self, models: Models, cfg: Config) -> None:
        self.models = models
        self.cfg = cfg

    @classmethod
    def from_config(cls, models: Models | None = None) -> Engine:
        """Load config and models once (FastAPI lifespan). `models: stub|real` in global.yaml picks them."""
        cfg = get_config()
        if models is None:
            if cfg.global_.models == "real":
                from greenhome.ml.registry import load_models  # P3 delivers (D12)

                models = load_models(cfg.models_dir)
            else:
                models = load_stub_models()
        return cls(models, cfg)

    # ---------- public API ----------
    def analyse(self, home: HomeInput, ctx: CustomerContext | None = None) -> AnalysisResult:
        return self.run_scenario(home, Scenario(), ctx)

    def run_scenario(
        self, home: HomeInput, scenario: Scenario, ctx: CustomerContext | None = None
    ) -> AnalysisResult:
        """Overrides → re-validate → same pipeline; custom items that are infeasible go to `rejected`.

        CustomerContext rules (CR-6): completed retrofits are applied to the home before validation (so
        they show as ALREADY_INSTALLED), exclusions leave the package, declined items drop one suitability
        level, the budget filters the package, and `priority` picks the suitability weights.
        Raises pydantic.ValidationError when an override is not a valid HomeInput value (API → 422).
        """
        analysis_id = self._analysis_id(home, scenario, ctx)
        if scenario.overrides:
            home = HomeInput.model_validate({**home.model_dump(), **scenario.overrides})
        if ctx and ctx.completed_retrofits:
            home = apply_retrofits(home, ctx.completed_retrofits)
        clean = validate_and_clean(home, self.models.rating)
        flags = list(clean.flags)
        unknown = {f for f, p in clean.provenance.items() if p in UNKNOWN_PROVENANCE}

        score = compute_score(clean)
        if score.status == "insufficient":
            flags.append(_flag("INSUFFICIENT_INFO_SCORE", "Not enough information to score this home."))

        feas = feasible_set(clean.home, unknown)
        issues, is_poor = detect_issues(clean, score, feas)
        candidates = [r for r in RETROFITS if feas[r][0] != "infeasible"]
        p_assessor = self.models.recommender.predict_proba([clean])[0]

        # Savings need an in-scope fuel, a known heating system and a baseline for both fuels (P2.5).
        baseline = _baseline(clean)
        if not clean.in_savings_scope:
            savings_status = "out_of_scope"
        elif baseline is None or "heating_system" in unknown:
            savings_status = "insufficient"
            flags.append(_flag("INSUFFICIENT_INFO_SAVINGS", "Not enough information to estimate savings."))
        else:
            savings_status = "ok"
        standalone: dict[str, FuelSaving] = {}
        if savings_status == "ok" and candidates:
            afters = self.models.energy.predict_after(
                [clean] * len(candidates), [frozenset({r}) for r in candidates]
            )
            standalone = {r: _saving(baseline, a) for r, a in zip(candidates, afters, strict=True)}

        # Package by scenario mode, then suitability, budget and dependency-aware order.
        rejected: list[RejectedRetrofit] = []
        if scenario.mode == "custom":
            requested = list(dict.fromkeys(scenario.retrofits))
            rejected = [
                RejectedRetrofit(retrofit=r, reason=feas[r][1][0]) for r in requested if r not in candidates
            ]
            package = [r for r in requested if r in candidates]
        elif scenario.mode == "recommended":
            excluded = set(ctx.excluded_retrofits) if ctx else set()
            package = [r for r in candidates if r not in excluded]
        else:
            package = []
        rated = rate_suitability(
            [
                Candidate(
                    retrofit=r,
                    feasibility=feas[r][0],
                    p_assessor=p_assessor[r],
                    standalone=standalone.get(r),
                    baseline_purchased_kwh=baseline.purchased_kwh if baseline else None,
                )
                for r in candidates
            ],
            clean.home,
            package,
            ctx.priority if ctx else "balanced",
        )
        if ctx:
            rated = {r: _demote(v) if r in ctx.declined_retrofits else v for r, v in rated.items()}
        priority = {r: rated[r][0] if rated[r][0] is not None else p_assessor[r] for r in candidates}
        over_budget: list[str] = []
        if scenario.mode == "recommended" and ctx and ctx.max_budget_gbp is not None:
            by_priority = sorted(package, key=lambda r: (-priority[r], RETROFITS.index(r)))
            kept, over_budget = budget_filter(by_priority, ctx.max_budget_gbp)
            package = [r for r in package if r in kept]
        order = order_retrofits(package, priority)

        savings, incremental = self._savings(clean, baseline, savings_status, order, candidates)
        after_energy = savings.after
        carbon = compute_carbon(savings.saving) if savings.saving else None

        # Rating and value before/after (BUILD_GUIDE P2.8 steps 8–9).
        after_home = apply_retrofits(clean.home, order)
        after_clean = _after_clean(clean, after_home, after_energy)
        raw_before, raw_after = self.models.rating.predict_sap([clean, after_clean])
        sap_before = clean.sap_estimate if clean.sap_estimate is not None else anchor_sap(raw_before, None)
        sap_after = anchor_sap(sap_before + (raw_after - raw_before), None)
        rating_before = clean.home.energy_rating
        rating_after = band_for_sap(sap_after)
        log_prices = None
        if _value_possible(clean.home) and rating_before is not None:
            log_prices = self.models.value.predict_log_price(
                [clean, after_clean], [rating_before, rating_after], self.cfg.global_.as_of_date
            )
        else:
            flags.append(_flag("INSUFFICIENT_INFO_VALUE", "Not enough information to estimate value change."))
        value = assemble_value(
            current_value_gbp=clean.home.current_value_gbp,
            rating_before=rating_before,
            rating_after=rating_after,
            sap_before=sap_before,
            sap_after=sap_after,
            log_prices=log_prices,
        )

        score_after: ScoreResult | None = None
        if after_energy is not None:
            scored_home = after_clean.home.model_copy(update={"energy_rating": rating_after})
            score_after = compute_score(
                after_clean.model_copy(update={"home": scored_home, "sap_estimate": sap_after})
            )

        recommendations = self._recommendations(
            feas, rated, p_assessor, standalone, incremental, order, clean, ctx, over_budget
        )
        return AnalysisResult(
            contract_version=CONTRACT_VERSION,
            analysis_id=analysis_id,
            model_versions=self.models.versions(),
            home=clean,
            score=score,
            issues=issues,
            is_poor=is_poor,
            recommendations=recommendations,
            scenario=scenario,
            rejected=rejected,
            savings=savings,
            carbon=carbon,
            value=value,
            score_after=score_after,
            flags=flags,
            peer=self._peer(clean),
        )

    def portfolio(self, split: str = "test", limit: int | None = None) -> list[PortfolioRow]:
        """Rank one split's homes by improvement potential (PS §3), poor homes with their key issues.

        # ponytail: analyses homes one by one (~ms each on stubs); batch across homes if the split grows
        # beyond ~10k homes.
        """
        import pandas as pd

        data = self.cfg.data_dir
        paths = {n: data / f"{n}.parquet" for n in ("properties", "splits", "energy_monthly")}
        missing = [str(p) for n, p in paths.items() if n != "energy_monthly" and not p.exists()]
        if missing:
            raise FileNotFoundError(f"portfolio needs P1's processed data (`make data`): {missing}")
        props = pd.read_parquet(paths["properties"])
        ids = pd.read_parquet(paths["splits"]).query("split == @split")["property_id"]
        props = props[props["property_id"].isin(set(ids))].sort_values("property_id")
        monthly = pd.read_parquet(paths["energy_monthly"]) if paths["energy_monthly"].exists() else None
        by_id = {} if monthly is None else {k: g for k, g in monthly.groupby("property_id")}

        results = [self.analyse(_home_from_row(rec, by_id.get(rec["property_id"])))
                   for rec in props.to_dict("records")]
        results.sort(key=lambda r: (
            r.savings.improvement_potential_pct is None,
            -(r.savings.improvement_potential_pct or 0),
            r.home.home.property_id,
        ))
        rows = [
            PortfolioRow(
                rank=i,
                property_id=res.home.home.property_id,
                customer_id=res.home.home.customer_id,
                region=res.home.home.region,
                property_type=res.home.home.property_type,
                score=res.score.score,
                score_class=res.score.score_class,
                is_poor=res.is_poor,
                improvement_potential_pct=res.savings.improvement_potential_pct,
                key_issues=[issue.code for issue in res.issues[:3]],  # issues are sorted high → low
                savings_status=res.savings.status,
            )
            for i, res in enumerate(results, start=1)
        ]
        return rows[:limit] if limit is not None else rows

    # ---------- steps ----------
    def _savings(
        self,
        clean: CleanHome,
        baseline: FuelEnergy | None,
        status: str,
        order: list[str],
        candidates: list[str],
    ) -> tuple[SavingsResult, dict[str, FuelSaving]]:
        """Prefix packages telescope, so incremental savings sum exactly to the package saving (IT3).

        Improvement potential always uses the full feasible package, as the PS defines it.
        """
        if status != "ok" or baseline is None:
            empty = SavingsResult(status=status, retrofits=order, baseline=baseline, after=None, saving=None,
                                  improvement_potential_pct=None)
            return empty, {}
        packages = [frozenset(order[: k + 1]) for k in range(len(order))] + [frozenset(candidates)]
        afters = self.models.energy.predict_after([clean] * len(packages), packages)
        prev, incremental = baseline, {}
        for r, after in zip(order, afters[:-1], strict=True):
            incremental[r] = _saving(prev, after)
            prev = after
        saving = _saving(baseline, prev)
        drift = abs(sum(s.net_kwh for s in incremental.values()) - saving.net_kwh)
        assert drift <= _TELESCOPE_TOL_KWH, f"incremental savings drift {drift} kWh"
        full = afters[-1]
        ip = None
        if baseline.purchased_kwh > 0:
            ip = 100 * (baseline.purchased_kwh - full.purchased_kwh) / baseline.purchased_kwh
        result = SavingsResult(status="ok", retrofits=order, baseline=baseline, after=prev, saving=saving,
                               improvement_potential_pct=ip)
        return result, incremental

    def _recommendations(
        self,
        feas: dict[str, tuple[str, list[str]]],
        rated: dict[str, tuple[float | None, str | None, list[str]]],
        p_assessor: dict[str, float],
        standalone: dict[str, FuelSaving],
        incremental: dict[str, FuelSaving],
        order: list[str],
        clean: CleanHome,
        ctx: CustomerContext | None,
        over_budget: list[str],
    ) -> list[RetrofitRecommendation]:
        """All 7 retrofits: the package in order, then other feasible by suitability, then infeasible."""
        rank = {r: i for i, r in enumerate(order, start=1)}
        recs = []
        for r in RETROFITS:
            feasibility, reasons = feas[r]
            u, suitability, extra = rated.get(r, (None, None, []))
            reasons = list(reasons) + extra
            if ctx and r in ctx.excluded_retrofits:
                reasons.append("CUSTOMER_EXCLUDED")
            if ctx and r in ctx.declined_retrofits:
                reasons.append("CUSTOMER_DECLINED_BEFORE")
            if r in over_budget:
                reasons.append("OVER_BUDGET")
            if not clean.in_savings_scope and feasibility != "infeasible":
                reasons.append("OUT_OF_SCOPE_FUEL")
            spec = self.cfg.catalogue[r]
            recs.append(RetrofitRecommendation(
                retrofit=r,
                rank=rank.get(r),
                feasibility=feasibility,
                suitability=suitability,
                reasons=list(dict.fromkeys(reasons)),
                depends_on=depends_on(r, order) if r in rank else [],
                standalone_saving=standalone.get(r),
                incremental_saving=incremental.get(r),
                standalone_carbon_kg=compute_carbon(standalone[r]).total_kg if r in standalone else None,
                cost_low_gbp=spec.cost_gbp[0],
                cost_high_gbp=spec.cost_gbp[1],
                assessor_likelihood=p_assessor[r] if feasibility != "infeasible" else None,
            ))

        def sort_key(rec: RetrofitRecommendation) -> tuple:
            u = rated.get(rec.retrofit, (None,))[0]
            group = 0 if rec.rank is not None else (1 if rec.feasibility != "infeasible" else 2)
            return (group, rec.rank or 0, -(u or 0.0), RETROFITS.index(rec.retrofit))

        return sorted(recs, key=sort_key)

    def _peer(self, clean: CleanHome) -> PeerComparison | None:
        """CR-3: the same peer group the issues use; None when intensity is unknown or not metered."""
        area = clean.home.floor_area_m2
        energy_imputed = "imputed" in (clean.provenance.get(f) for f in ("electricity_kwh", "gas_kwh"))
        if clean.intensity_kwh_m2 is None or area is None or energy_imputed:
            return None
        peers = self.cfg.peers(clean.home.property_type, area)
        return PeerComparison(
            intensity_kwh_m2=clean.intensity_kwh_m2,
            property_type=clean.home.property_type,
            floor_area_band=self.cfg.floor_area_band(area),
            p50_kwh_m2=peers["p50"],
            p75_kwh_m2=peers["p75"],
            p90_kwh_m2=peers["p90"],
        )

    def _analysis_id(self, home: HomeInput, scenario: Scenario, ctx: CustomerContext | None) -> str:
        """sha256 of canonical input + scenario + ctx + versions (stable across runs and processes)."""
        payload = {
            "home": home.model_dump(mode="json"),
            "scenario": scenario.model_dump(mode="json"),
            "ctx": ctx.model_dump(mode="json") if ctx else None,
            "model_versions": self.models.versions(),
            "contract_version": CONTRACT_VERSION,
            "method_version": self.cfg.score.method_version,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


# ---------- helpers ----------
def _flag(code: str, message: str) -> DataFlag:
    return DataFlag(code=code, severity="warning", message=message)


Rated = tuple[float | None, str | None, list[str]]  # (u, suitability, reasons) from rate_suitability


def _demote(rated: Rated) -> Rated:
    """Declined before → one suitability level lower (high → medium → low; low stays low)."""
    u, level, reasons = rated
    levels = [s.value for s in Suitability]  # high, medium, low
    if level is not None:
        level = levels[min(levels.index(level) + 1, len(levels) - 1)]
    return u, level, reasons


def _baseline(clean: CleanHome) -> FuelEnergy | None:
    e, g = clean.energy.electricity_kwh, clean.energy.gas_kwh
    return None if e is None or g is None else FuelEnergy(electricity_kwh=e, gas_kwh=g, purchased_kwh=e + g)


def _saving(before: FuelEnergy, after: FuelEnergy) -> FuelSaving:
    """Positive = reduction (§7.1)."""
    e = before.electricity_kwh - after.electricity_kwh
    g = before.gas_kwh - after.gas_kwh
    return FuelSaving(electricity_kwh=e, gas_kwh=g, net_kwh=e + g)


def _value_possible(home: HomeInput) -> bool:
    """P2.5: a user value, or enough features for a model estimate."""
    model_inputs = (home.region, home.property_type, home.floor_area_m2, home.age_band)
    return home.current_value_gbp is not None or all(v is not None for v in model_inputs)


def _after_clean(clean: CleanHome, after_home: HomeInput, after: FuelEnergy | None) -> CleanHome:
    """Post-package home for the models: changed fields are 'derived'; the rating is left unchanged so
    the rating model's before/after delta reflects only the retrofits."""
    changed = {f for f in clean.provenance if getattr(after_home, f, None) != getattr(clean.home, f, None)}
    provenance = {f: ("derived" if f in changed else p) for f, p in clean.provenance.items()}
    energy, intensity = clean.energy, clean.intensity_kwh_m2
    if after is not None:
        provenance |= {"electricity_kwh": "derived", "gas_kwh": "derived"}
        energy = AnnualEnergy(
            electricity_kwh=after.electricity_kwh,
            gas_kwh=after.gas_kwh,
            purchased_kwh=after.purchased_kwh,
            electricity_coverage=None,
            gas_coverage=None,
            source="imputed",
        )
        area = after_home.floor_area_m2
        intensity = after.purchased_kwh / area if area else None
    return clean.model_copy(update={
        "home": after_home,
        "provenance": provenance,
        "energy": energy,
        "intensity_kwh_m2": intensity,
        "flags": [],
    })


def _home_from_row(row: dict[str, Any], monthly: Any | None) -> HomeInput:
    """properties.parquet row (+ its energy_monthly rows) → HomeInput. NaN/NA → None (§7.1)."""
    import pandas as pd

    def clean(v: Any) -> Any:
        return None if v is None or (not isinstance(v, str) and pd.isna(v)) else v

    fields = set(HomeInput.model_fields) - {"energy"}
    data = {k: clean(row[k]) for k in fields if k in row}
    if data.get("bedrooms") is not None:
        data["bedrooms"] = int(data["bedrooms"])
    readings = []
    if monthly is not None:
        for m in monthly.sort_values("month").to_dict("records"):
            readings.append({
                "month": m["month"],
                "electricity_kwh": clean(m.get("electricity_kwh")),
                "gas_kwh": clean(m.get("gas_kwh")),
            })
    data["energy"] = {"monthly": readings or None}
    return HomeInput.model_validate(data)
