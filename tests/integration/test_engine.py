"""Integration tests IT1–IT12 (README P2.9), owned with P5. Run on stubs, or real models once P3 ships."""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import pytest

from greenhome.config import REPO_ROOT, get_config
from greenhome.contracts import HomeInput, Scenario
from greenhome.core.orchestrator import Engine

FIXTURES = REPO_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))
from generate import home_inputs, render  # noqa: E402

HIDDEN_FACTORS = {
    "setpoint_factor",
    "occupancy_factor",
    "true_scop",
    "pv_orientation_factor",
    "self_consumption_frac",
}
TIME_BUDGET_S = 0.5


@pytest.fixture(scope="module")
def engine() -> Engine:
    return Engine.from_config()


@pytest.fixture(scope="module")
def homes() -> dict[str, HomeInput]:
    return home_inputs()


def _example_homes() -> list[Path]:
    examples = get_config().examples_dir
    paths = sorted(examples.glob("*.json")) if examples.exists() else []
    return [p for p in paths if p.name != "index.json"] + sorted(FIXTURES.glob("home_input_*.json"))


def _model_feature_files() -> list[Path]:
    models = get_config().models_dir
    return sorted(models.glob("*/features.json")) if models.exists() else []


@pytest.mark.parametrize("path", _example_homes(), ids=lambda p: p.name)
def test_it1_every_example_analyses_within_budget(engine: Engine, path: Path) -> None:
    home = HomeInput.model_validate_json(path.read_text())
    engine.analyse(home)  # warm-up
    t0 = time.perf_counter()
    engine.analyse(home)
    assert time.perf_counter() - t0 < TIME_BUDGET_S


def test_it2_contributions_sum_to_score_raw(engine: Engine, homes: dict[str, HomeInput]) -> None:
    for home in homes.values():
        score = engine.analyse(home).score
        if score.status == "ok":
            assert math.isclose(sum(c.contribution for c in score.components), score.score_raw, abs_tol=1e-9)


def test_it3_incremental_savings_sum_to_package(engine: Engine, homes: dict[str, HomeInput]) -> None:
    for home in homes.values():
        res = engine.analyse(home)
        if res.savings.status != "ok":
            continue
        incr = [r.incremental_saving for r in res.recommendations if r.rank is not None]
        for fuel in ("electricity_kwh", "gas_kwh", "net_kwh"):
            total = sum(getattr(s, fuel) for s in incr)
            assert abs(total - getattr(res.savings.saving, fuel)) <= 1.0


def test_it4_carbon_equals_formula(engine: Engine, homes: dict[str, HomeInput]) -> None:
    ef = get_config().emission_factors
    res = engine.analyse(homes["P10001"])
    s, c = res.savings.saving, res.carbon
    expected = s.electricity_kwh * ef["electricity"].kg_co2e_per_kwh + s.gas_kwh * ef["gas"].kg_co2e_per_kwh
    assert math.isclose(c.total_kg, expected, rel_tol=1e-12)


def test_it5_heat_pump_on_gas_home_raises_electricity(engine: Engine, homes: dict[str, HomeInput]) -> None:
    scenario = Scenario(name="hp", mode="custom", retrofits=["air_source_heat_pump"])
    res = engine.run_scenario(homes["P10001"], scenario)
    assert res.savings.retrofits == ["air_source_heat_pump"]
    assert res.savings.saving.electricity_kwh < 0
    assert res.savings.saving.gas_kwh > 0


def test_it6_infeasible_custom_retrofit_is_rejected(engine: Engine, homes: dict[str, HomeInput]) -> None:
    scenario = Scenario(name="x", mode="custom", retrofits=["solid_wall_insulation", "loft_insulation"])
    res = engine.run_scenario(homes["P10001"], scenario)  # P10001 has cavity walls
    assert [r.retrofit for r in res.rejected] == ["solid_wall_insulation"]
    assert res.rejected[0].reason == "WRONG_WALL_TYPE"
    assert res.savings.retrofits == ["loft_insulation"]


def test_it7_missing_winter_months_not_underestimated(engine: Engine, homes: dict[str, HomeInput]) -> None:
    home = homes["P90004"]
    gas = [m.gas_kwh for m in home.energy.monthly if m.gas_kwh is not None]
    res = engine.analyse(home)
    assert res.home.energy.gas_kwh > sum(gas) / len(gas) * 12


def test_it8_no_info_home_returns_no_numbers(engine: Engine, homes: dict[str, HomeInput]) -> None:
    res = engine.analyse(homes["P90003"])
    assert res.score.status == "insufficient" and res.score.score is None and res.score.score_range is None
    assert res.savings.status == "insufficient" and res.savings.saving is None and res.carbon is None
    assert res.value.status == "insufficient" and res.value.uplift_pct_mid is None
    assert res.is_poor is None and res.score_after is None
    codes = {f.code for f in res.flags}
    assert {"INSUFFICIENT_INFO_SCORE", "INSUFFICIENT_INFO_SAVINGS", "INSUFFICIENT_INFO_VALUE"} <= codes


def test_it9_analysis_id_is_stable(homes: dict[str, HomeInput]) -> None:
    a = Engine.from_config().analyse(homes["P10001"]).analysis_id
    b = Engine.from_config().analyse(homes["P10001"].model_copy(deep=True)).analysis_id
    c = Engine.from_config().run_scenario(homes["P10001"], Scenario(mode="none")).analysis_id
    assert a == b != c


@pytest.mark.skipif(not _model_feature_files(), reason="P3 has not shipped models/*/features.json yet")
def test_it10_real_models_serve_every_fixture(homes: dict[str, HomeInput]) -> None:
    """P3's wrappers compare each model's saved columns with greenhome.ml.features at predict time and raise
    on a mismatch, so analysing every fixture home with the real models is the train/serve skew check."""
    from greenhome.ml.registry import load_models

    engine = Engine.from_config(models=load_models(get_config().models_dir))
    for home in homes.values():
        engine.analyse(home)


@pytest.mark.skipif(not _model_feature_files(), reason="P3 has not shipped models/*/features.json yet")
@pytest.mark.parametrize("path", _model_feature_files(), ids=lambda p: p.parent.name)
def test_it11_no_hidden_simulator_factor_is_a_feature(path: Path) -> None:
    assert not HIDDEN_FACTORS & set(json.dumps(json.loads(path.read_text())).replace('"', " ").split())


def test_it12_json_has_no_nan(engine: Engine, homes: dict[str, HomeInput]) -> None:
    for home in homes.values():
        text = engine.analyse(home).model_dump_json()
        assert "NaN" not in text and "Infinity" not in text


def test_fixtures_are_current(homes: dict[str, HomeInput]) -> None:
    """P4/P5 build against the committed fixtures; regenerate with tests/fixtures/generate.py."""
    from greenhome.ml.stubs import load_stub_models

    engine = Engine.from_config(models=load_stub_models())
    for key, home in homes.items():
        committed = json.loads((FIXTURES / f"analysis_result_{key}.json").read_text())
        fresh = json.loads(render(engine.analyse(home)))
        where = _first_difference(fresh, committed)
        assert where is None, f"stale fixture {key} at {where}: run tests/fixtures/generate.py"


def _first_difference(a, b, path: str = "$") -> str | None:
    """Path of the first real difference. Floats match to 1e-9 relative: the last binary digit of a sum
    differs between machines/BLAS builds, which is not a stale fixture."""
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return f"{path} keys {sorted(a.keys() ^ b.keys())}"
        return next((d for k in a if (d := _first_difference(a[k], b[k], f"{path}.{k}"))), None)
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path} length {len(a)} != {len(b)}"
        return next(
            (
                d
                for i, (x, y) in enumerate(zip(a, b, strict=True))
                if (d := _first_difference(x, y, f"{path}[{i}]"))
            ),
            None,
        )
    if isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return None if math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9) else f"{path} {a!r} != {b!r}"
    return None if a == b else f"{path} {a!r} != {b!r}"
