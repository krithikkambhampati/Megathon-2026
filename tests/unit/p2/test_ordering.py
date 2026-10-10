from __future__ import annotations

import shutil

import pytest
import yaml
from conftest import home_input

from greenhome.config import REPO_ROOT, get_config
from greenhome.contracts import FuelSaving
from greenhome.core.ordering import (
    Candidate,
    budget_filter,
    depends_on,
    order_retrofits,
    prerequisites_met,
    rate_suitability,
)

LOFT, CAVITY, SOLID = "loft_insulation", "cavity_wall_insulation", "solid_wall_insulation"
GLAZING = "double_glazing"
SMART, HP, SOLAR = "smart_thermostat", "air_source_heat_pump", "solar_pv"
BASELINE = 16800.0
INSULATED = {"roof_insulation": "full", "wall_insulation": "full"}  # sub-score 100


def _cand(r, net=1000.0, *, elec=None, p=0.5, feas="feasible", baseline=BASELINE, standalone=True):
    elec = 0.0 if elec is None else elec
    saving = FuelSaving(electricity_kwh=elec, gas_kwh=net - elec, net_kwh=net) if standalone else None
    return Candidate(r, feas, p, saving, baseline)


@pytest.fixture
def alt_config(tmp_path, monkeypatch):
    """Copy of config/ with a catalogue edit applied; returns an editor taking (retrofit, **fields)."""
    root = tmp_path / "config"
    shutil.copytree(REPO_ROOT / "config", root)

    def edit(retrofit, **fields):
        path = root / "retrofit_catalogue.yaml"
        cat = yaml.safe_load(path.read_text())
        next(x for x in cat if x["retrofit"] == retrofit).update(fields)
        path.write_text(yaml.safe_dump(cat))
        monkeypatch.setenv("GREENHOME_CONFIG_DIR", str(root))

    return edit


# ---------- order_retrofits / depends_on ----------
def test_p10001_order_follows_stages():
    pkg = {SOLAR, HP, SMART, GLAZING, CAVITY, LOFT}
    assert order_retrofits(pkg, {}) == [LOFT, CAVITY, GLAZING, SMART, HP, SOLAR]


def test_priority_breaks_ties_inside_a_stage_only():
    assert order_retrofits({LOFT, CAVITY}, {CAVITY: 0.9, LOFT: 0.1}) == [CAVITY, LOFT]
    assert order_retrofits({LOFT, CAVITY}, {}) == [LOFT, CAVITY]  # catalogue order
    assert order_retrofits({LOFT, SOLAR}, {SOLAR: 1.0}) == [LOFT, SOLAR]  # stage beats priority


def test_order_is_deterministic():
    pkg = [SOLAR, HP, LOFT, SMART, GLAZING, SOLID]
    pri = {SOLID: 0.3, LOFT: 0.3}
    assert order_retrofits(pkg, pri) == order_retrofits(list(reversed(pkg)), dict(reversed(pri.items())))


def test_cycle_raises(alt_config):
    alt_config(LOFT, soft_after=[SOLAR])
    with pytest.raises(ValueError):
        order_retrofits({LOFT, HP, SOLAR}, {})


def test_depends_on():
    assert depends_on(HP, {LOFT, CAVITY, SMART, SOLAR, HP}) == [LOFT, CAVITY, SMART]
    assert depends_on(SOLAR, {HP, SOLAR}) == [HP]
    assert depends_on(LOFT, {LOFT, HP}) == []


# ---------- prerequisites ----------
def test_prerequisites_met():
    p10001 = home_input()  # sub-score 0.4·35 + 0.6·20 = 26 < 50
    assert not prerequisites_met(HP, p10001, {HP, SOLAR})
    assert prerequisites_met(HP, p10001, {HP, LOFT})
    assert prerequisites_met(HP, home_input(**INSULATED), {HP})
    assert not prerequisites_met(HP, home_input(roof_insulation=None), {HP})  # unknown counts as below
    assert prerequisites_met(LOFT, p10001, set())  # no prerequisites


# ---------- rate_suitability ----------
def _net_cost(r):
    spec = get_config().catalogue[r]
    return spec.cost_mid_gbp - spec.grant_gbp


def test_u_formula():
    w = get_config().score.suitability.priority_weights["balanced"]
    out = rate_suitability([_cand(LOFT, 1000.0), _cand(CAVITY, 2000.0)], home_input(), {LOFT, CAVITY})
    eff = {LOFT: 1000.0 / _net_cost(LOFT), CAVITY: 2000.0 / _net_cost(CAVITY)}  # kWh per £ (scale cancels)
    top = max(eff.values())
    assert out[LOFT][0] == pytest.approx(
        w["assessor"] * 0.5 + w["saving_share"] * 0.5 + w["cost_eff"] * eff[LOFT] / top)
    assert out[CAVITY][0] == pytest.approx(
        w["assessor"] * 0.5 + w["saving_share"] + w["cost_eff"] * eff[CAVITY] / top)


def test_levels_from_thresholds():
    s = get_config().score.suitability
    out = rate_suitability(
        [_cand(CAVITY, 2000.0, p=1.0), _cand(LOFT, 0.0, p=0.0), _cand(SMART, -10.0, p=0.0)],
        home_input(), {LOFT, CAVITY, SMART},
    )
    assert out[CAVITY][0] >= s.high and out[CAVITY][1] == "high"
    assert out[LOFT][0] < s.medium and out[LOFT][1] == "low"
    assert out[SMART][0] == 0.0  # negatives normalise to 0


def test_needs_survey_caps_at_medium():
    out = rate_suitability([_cand(CAVITY, 2000.0, p=1.0, feas="needs_survey")], home_input(), {CAVITY})
    assert out[CAVITY][1] == "medium"


def test_unmet_prerequisite_caps_low_and_insulate_first():
    hp = _cand(HP, 5000.0, elec=-2000.0, p=1.0)
    out = rate_suitability([hp], home_input(), {HP})
    assert out[HP][1] == "low" and "INSULATE_FIRST" in out[HP][2]
    met = rate_suitability([hp], home_input(), {HP, LOFT})
    assert met[HP][1] == "high" and "INSULATE_FIRST" not in met[HP][2]


def test_suitability_none_when_savings_missing():
    out = rate_suitability(
        [_cand(HP, standalone=False, p=0.7), _cand(LOFT, baseline=None), _cand(CAVITY, baseline=0.0)],
        home_input(), {HP},
    )
    assert out[HP] == (None, None, ["ASSESSORS_OFTEN_RECOMMEND", "INSULATE_FIRST"])
    assert out[LOFT] == (None, None, [])
    assert out[CAVITY] == (None, None, [])


def test_reason_codes():
    cands = [
        _cand(LOFT, 2000.0),  # share 0.119 ≥ 0.10, cost_high 1500 ≤ 1500
        _cand(SOLID, 300.0),  # cost_mid 11500 ≥ 5000, share 0.018 < 0.03
        _cand(HP, 5000.0, elec=-2000.0, p=0.7),
    ]
    out = rate_suitability(cands, home_input(), {HP})  # no insulation in package
    assert out[LOFT][2] == ["HIGH_SAVING", "QUICK_WIN_LOW_COST"]
    assert out[SOLID][2] == ["HIGH_COST_LOW_SAVING"]
    assert out[HP][2] == [
        "HIGH_SAVING", "ELECTRICITY_RISES_GAS_FALLS", "ASSESSORS_OFTEN_RECOMMEND", "INSULATE_FIRST",
    ]


def test_no_quick_win_without_saving():
    out = rate_suitability([_cand(SMART, -5.0)], home_input(), {SMART})
    assert "QUICK_WIN_LOW_COST" not in out[SMART][2]


def test_free_after_grant_gets_full_cost_efficiency(alt_config):
    alt_config(LOFT, grant_gbp=2000)
    w = get_config().score.suitability.priority_weights["balanced"]
    out = rate_suitability([_cand(LOFT, 1.0, p=0.0), _cand(CAVITY, 2000.0, p=0.0)], home_input(), {LOFT})
    assert out[LOFT][0] == pytest.approx(w["saving_share"] * 1.0 / 2000 + w["cost_eff"])


def test_suitability_deterministic():
    cands = [_cand(LOFT, 2000.0), _cand(CAVITY, 1500.0), _cand(HP, 5000.0, elec=-2000.0)]
    home = home_input()
    assert rate_suitability(cands, home, [HP, LOFT]) == rate_suitability(cands, home, [LOFT, HP])


# ---------- budget_filter ----------
def test_budget_filter_greedy_skips_and_continues():
    hp, solar, loft = _net_cost(HP), _net_cost(SOLAR), _net_cost(LOFT)
    assert solar > hp > loft  # true for the catalogue; the budget below relies on it
    budget = hp + loft  # fits HP, not solar, then the cheaper loft still fits
    assert budget_filter([HP, SOLAR, LOFT], budget) == ([HP, LOFT], [SOLAR])
    assert budget_filter([HP, SOLAR, LOFT, CAVITY], 0.0) == ([], [HP, SOLAR, LOFT, CAVITY])
    assert budget_filter([LOFT, CAVITY], _net_cost(LOFT) + _net_cost(CAVITY)) == ([LOFT, CAVITY], [])
