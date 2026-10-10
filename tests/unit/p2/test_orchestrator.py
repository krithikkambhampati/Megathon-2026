"""Engine behaviour beyond IT1–IT12: customer context, budget, scenario modes, scope, portfolio."""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import home_input
from pydantic import ValidationError

from greenhome.config import Config
from greenhome.contracts import CustomerContext, Retrofit, Scenario
from greenhome.core.orchestrator import Engine


@pytest.fixture(scope="module")
def engine() -> Engine:
    return Engine.from_config()


def _rec(res, retrofit):
    return next(r for r in res.recommendations if r.retrofit == retrofit)


def test_returns_all_seven_with_infeasible_last(engine: Engine) -> None:
    recs = engine.analyse(home_input()).recommendations
    assert sorted(r.retrofit for r in recs) == sorted(r.value for r in Retrofit)
    groups = [0 if r.rank else (1 if r.feasibility != "infeasible" else 2) for r in recs]
    assert groups == sorted(groups)
    ranks = [r.rank for r in recs if r.rank is not None]
    assert ranks == list(range(1, len(ranks) + 1))


def test_recommended_package_respects_stage_order(engine: Engine) -> None:
    res = engine.analyse(home_input())
    order = res.savings.retrofits
    assert order.index("loft_insulation") < order.index("air_source_heat_pump") < order.index("solar_pv")
    assert "loft_insulation" in _rec(res, "air_source_heat_pump").depends_on


def test_completed_retrofit_becomes_already_installed(engine: Engine) -> None:
    ctx = CustomerContext(customer_id="C10001", completed_retrofits=["loft_insulation"])
    res = engine.analyse(home_input(), ctx)
    rec = _rec(res, "loft_insulation")
    assert (rec.feasibility, rec.rank, rec.reasons) == ("infeasible", None, ["ALREADY_INSTALLED"])
    assert "loft_insulation" not in res.savings.retrofits


def test_completed_retrofit_changes_the_home_before_validation(engine: Engine) -> None:
    ctx = CustomerContext(customer_id="C10001", completed_retrofits=["double_glazing"])
    res = engine.analyse(home_input(), ctx)
    assert res.home.home.glazing == "double"
    assert res.score.score > engine.analyse(home_input()).score.score


def test_declined_retrofit_drops_one_suitability_level(engine: Engine) -> None:
    levels = ["high", "medium", "low"]
    base = {r.retrofit: r.suitability for r in engine.analyse(home_input()).recommendations}
    ctx = CustomerContext(customer_id="C10001", declined_retrofits=list(base))
    for rec in engine.analyse(home_input(), ctx).recommendations:
        if base[rec.retrofit] is None:
            assert rec.suitability is None
        else:
            expected = levels[min(levels.index(base[rec.retrofit]) + 1, 2)]
            assert rec.suitability == expected


def test_priority_changes_ranking_inputs_never_numbers(engine: Engine) -> None:
    base = engine.analyse(home_input())
    for priority in ("carbon", "bills", "value"):
        res = engine.analyse(home_input(), CustomerContext(customer_id="C10001", priority=priority))
        assert res.savings.improvement_potential_pct == base.savings.improvement_potential_pct
        assert res.score == base.score and res.value == base.value
        assert sorted(res.savings.retrofits) == sorted(base.savings.retrofits)


def test_peer_comparison(engine: Engine) -> None:
    peer = engine.analyse(home_input()).peer
    expected = engine.cfg.peers("semi_detached", 85.0)
    assert peer.floor_area_band == "50_90" and peer.p90_kwh_m2 == expected["p90"]
    assert peer.intensity_kwh_m2 == (4800 + 12000) / 85
    no_energy = home_input(energy={})
    assert engine.analyse(no_energy).peer is None  # typical-home energy is not a measurement


def test_excluded_and_declined_retrofits(engine: Engine) -> None:
    ctx = CustomerContext(customer_id="C10001", excluded_retrofits=["solar_pv"],
                          declined_retrofits=["double_glazing"])
    res = engine.analyse(home_input(), ctx)
    solar = _rec(res, "solar_pv")
    assert solar.rank is None and "CUSTOMER_EXCLUDED" in solar.reasons
    assert "solar_pv" not in res.savings.retrofits
    assert "CUSTOMER_DECLINED_BEFORE" in _rec(res, "double_glazing").reasons


def test_budget_drops_expensive_items(engine: Engine) -> None:
    ctx = CustomerContext(customer_id="C10001", max_budget_gbp=3000)
    res = engine.analyse(home_input(), ctx)
    dropped = [r for r in res.recommendations if "OVER_BUDGET" in r.reasons]
    assert dropped and all(r.rank is None for r in dropped)
    cat = engine.cfg.catalogue
    spent = sum(max(cat[r].cost_mid_gbp - cat[r].grant_gbp, 0) for r in res.savings.retrofits)
    assert spent <= 3000


def test_improvement_potential_ignores_exclusions(engine: Engine) -> None:
    base = engine.analyse(home_input()).savings
    ctx = CustomerContext(customer_id="C10001", excluded_retrofits=["air_source_heat_pump"])
    excluded = engine.analyse(home_input(), ctx).savings
    assert excluded.improvement_potential_pct == base.improvement_potential_pct
    assert excluded.saving.net_kwh < base.saving.net_kwh


def test_mode_none_has_zero_saving_and_no_ranks(engine: Engine) -> None:
    res = engine.run_scenario(home_input(), Scenario(name="none", mode="none"))
    assert res.savings.retrofits == [] and res.savings.saving.net_kwh == 0
    assert all(r.rank is None for r in res.recommendations)
    assert res.score_after.score == res.score.score


def test_override_revalidates_home(engine: Engine) -> None:
    res = engine.run_scenario(home_input(), Scenario(name="dg", overrides={"glazing": "double"}))
    assert _rec(res, "double_glazing").feasibility == "infeasible"
    assert res.home.home.glazing == "double"


def test_invalid_override_raises(engine: Engine) -> None:
    with pytest.raises(ValidationError):
        engine.run_scenario(home_input(), Scenario(overrides={"glazing": "quadruple"}))
    with pytest.raises(ValidationError):
        engine.run_scenario(home_input(), Scenario(overrides={"not_a_field": 1}))


def test_out_of_scope_fuel_scores_but_no_savings(engine: Engine) -> None:
    home = home_input(main_fuel="other", heating_system="other_fuel_boiler",
                      energy={"annual_electricity_kwh": 4000.0, "annual_gas_kwh": 0.0})
    res = engine.analyse(home)
    assert res.score.status == "ok"
    assert res.savings.status == "out_of_scope" and res.carbon is None
    assert all("OUT_OF_SCOPE_FUEL" in r.reasons for r in res.recommendations if r.feasibility != "infeasible")


def test_value_uplift_range_and_rating_after(engine: Engine) -> None:
    v = engine.analyse(home_input()).value
    assert v.status == "ok" and v.current_value_source == "user"
    assert v.uplift_pct_low <= v.uplift_pct_mid <= v.uplift_pct_high
    assert v.uplift_pct_high - v.uplift_pct_low >= 1.0 - 1e-9
    assert v.rating_after <= v.rating_before  # "A" < "E": better or equal band


def test_portfolio_ranks_by_improvement_potential(engine: Engine, tmp_path, monkeypatch) -> None:
    props = pd.DataFrame([
        {**home_input(property_id="P10001").model_dump(exclude={"energy"}), "customer_id": "C10001"},
        {**home_input(property_id="P10002", heating_system="heat_pump", main_fuel="electricity",
                      wall_insulation="full", roof_insulation="full", glazing="double",
                      ).model_dump(exclude={"energy"}),
         "customer_id": "C10002"},
        {**home_input(property_id="P10003").model_dump(exclude={"energy"}), "customer_id": "C10003"},
    ])
    props.to_parquet(tmp_path / "properties.parquet")
    pd.DataFrame({
        "property_id": ["P10001", "P10002", "P10003"],
        "customer_id": ["C10001", "C10002", "C10003"],
        "split": ["test", "test", "train"],
    }).to_parquet(tmp_path / "splits.parquet")
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    pd.DataFrame(
        [{"property_id": "P10001", "month": m, "electricity_kwh": 400.0, "gas_kwh": 1000.0} for m in months]
        + [{"property_id": "P10002", "month": m, "electricity_kwh": 500.0, "gas_kwh": 0.0} for m in months]
    ).to_parquet(tmp_path / "energy_monthly.parquet")
    monkeypatch.setattr(Config, "data_dir", property(lambda self: tmp_path))

    rows = engine.portfolio(split="test")
    assert [r.property_id for r in rows] == ["P10001", "P10002"]
    assert [r.rank for r in rows] == [1, 2]
    assert rows[0].improvement_potential_pct > rows[1].improvement_potential_pct
    assert rows[0].is_poor is True and rows[0].customer_id == "C10001"
    assert rows[0].region == "east_midlands" and rows[0].savings_status == "ok"
    assert len(rows[0].key_issues) <= 3
    assert len(engine.portfolio(split="test", limit=1)) == 1


def test_portfolio_without_data_explains(engine: Engine, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Config, "data_dir", property(lambda self: tmp_path))
    with pytest.raises(FileNotFoundError, match="make data"):
        engine.portfolio()


def test_memory_payloads_parse_by_kind() -> None:
    from greenhome.contracts import MemoryEventIn

    kinds = {
        "completed_retrofit": {"retrofit": "loft_insulation", "completed_on": "2025-03"},
        "exclude": {"retrofit": "solar_pv"},
        "budget": {"max_budget_gbp": 5000},
        "preference": {"priority": "carbon"},
        "recommendation_shown": {"analysis_id": "abc", "ranked_retrofits": ["loft_insulation"]},
        "response": {"retrofit": "solar_pv", "response": "declined"},
    }
    for kind, body in kinds.items():
        assert MemoryEventIn.model_validate({"payload": {"kind": kind, **body}}).payload.kind == kind
    with pytest.raises(ValidationError):
        MemoryEventIn.model_validate({"payload": {"kind": "budget", "max_budget_gbp": -1}})
