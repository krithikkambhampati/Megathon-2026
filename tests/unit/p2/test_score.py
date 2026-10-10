from __future__ import annotations

import math

import pytest
from conftest import home_input, make_clean
from hypothesis import given, settings
from hypothesis import strategies as st

from greenhome.config import get_config
from greenhome.contracts import (
    EnergyRating,
    Glazing,
    HeatingSystem,
    Renewables,
    RoofInsulation,
    RoofType,
    SmartControls,
    WallInsulation,
    WallType,
)
from greenhome.core.score import classify, compute_score, insulation_sub_score

CFG = get_config()
QUALITY_FIELDS = (
    "energy_rating", "roof_insulation", "wall_insulation", "glazing", "heating_system", "renewables",
    "smart_controls",
)
ENUMS = {
    "energy_rating": EnergyRating, "roof_type": RoofType, "roof_insulation": RoofInsulation,
    "wall_type": WallType, "wall_insulation": WallInsulation, "glazing": Glazing,
    "heating_system": HeatingSystem, "renewables": Renewables, "smart_controls": SmartControls,
}
full_homes = st.fixed_dictionaries({f: st.sampled_from([e.value for e in E]) for f, E in ENUMS.items()})
kwh = st.floats(min_value=0, max_value=40_000, allow_nan=False)


def _score(elec: float = 4800.0, gas: float = 12000.0, unknown: tuple[str, ...] = (), **fields):
    return compute_score(make_clean(home_input(**fields), electricity_kwh=elec, gas_kwh=gas, unknown=unknown))


def _sub(result, key: str) -> float:
    return next(c.sub_score for c in result.components if c.key == key)


def test_weights_sum_to_one():
    assert math.isclose(sum(CFG.score.weights.values()), 1.0, abs_tol=1e-9)


@pytest.mark.parametrize("field", QUALITY_FIELDS)
def test_each_lookup_is_monotone_in_quality_order(field):
    key = {"energy_rating": "energy_efficiency", "heating_system": "heating"}.get(field, field)
    if field in ("roof_insulation", "wall_insulation"):
        key = "insulation"
    for wall_type in [w.value for w in WallType]:
        subs = [_sub(_score(**{field: v, "wall_type": wall_type}), key) for v in CFG.quality_order(field)]
        assert subs == sorted(subs)


@settings(max_examples=200, deadline=None)
@given(fields=full_homes, elec=kwh, gas=kwh, field=st.sampled_from(QUALITY_FIELDS), data=st.data())
def test_improving_any_single_input_never_lowers_score(fields, elec, gas, field, data):
    order = CFG.quality_order(field)
    better = data.draw(st.sampled_from(order[order.index(fields[field]) :]))
    before = _score(elec, gas, **fields).score_raw
    assert _score(elec, gas, **{**fields, field: better}).score_raw >= before - 1e-9
    lower_gas = data.draw(st.floats(min_value=0, max_value=gas, allow_nan=False))
    assert _score(elec, lower_gas, **fields).score_raw >= before - 1e-9


def test_intensity_sub_score_non_increasing_and_clipped():
    subs = [_sub(_score(elec=0.0, gas=g), "consumption_intensity") for g in range(0, 60_001, 2_500)]
    assert all(a >= b for a, b in zip(subs, subs[1:], strict=False))
    assert subs[0] == 100 and subs[-1] == 0
    assert all(0 <= s <= 100 for s in subs)


@settings(max_examples=50, deadline=None)
@given(fields=full_homes, elec=kwh, gas=kwh)
def test_contributions_sum_to_score_raw(fields, elec, gas):
    r = _score(elec, gas, **fields)
    assert math.isclose(sum(c.contribution for c in r.components), r.score_raw, abs_tol=1e-9)
    assert all(math.isclose(c.contribution, c.weight * c.sub_score) for c in r.components)


def test_class_boundaries_use_the_rounded_score():
    assert classify(29.5) == (30, "poor")
    assert classify(29.49) == (29, "very_poor")
    assert classify(79.5) == (80, "highly_efficient")
    assert classify(79.49) == (79, "good")
    for upper, lower in zip(CFG.score.classes, CFG.score.classes[1:], strict=False):
        assert classify(upper.min - 0.5)[1] == upper.class_
        assert classify(upper.min - 0.51)[1] == lower.class_


def test_p10001_golden_example():
    b = CFG.intensity_bounds
    intensity = (4800 + 12000) / 85
    expected_intensity = 100 * min(max((b.i_worst - intensity) / (b.i_worst - b.i_best), 0), 1)
    r = _score()
    assert r.status == "ok"
    assert [c.key for c in r.components] == list(CFG.score.weights)
    subs = [c.sub_score for c in r.components]
    assert subs == pytest.approx([47, expected_intensity, 26, 65, 0, 0, 50])
    expected_raw = sum(w * s for w, s in zip(CFG.score.weights.values(), subs, strict=True))
    assert r.score_raw == pytest.approx(expected_raw)
    intensity_comp = r.components[1]
    assert intensity_comp.inputs["intensity_kwh_m2"] == pytest.approx(intensity)
    assert intensity_comp.inputs["i_best"] == b.i_best and intensity_comp.inputs["i_worst"] == b.i_worst
    assert r.components[0].inputs == {"energy_rating": "E"}
    assert r.method_version == CFG.score.method_version
    assert (r.score, r.score_class) == classify(r.score_raw)
    assert r.score_range == (r.score, r.score)  # every input is user-given


def test_dwelling_above_excludes_roof():
    assert insulation_sub_score("dwelling_above", None, "cavity", "none") == 20
    assert insulation_sub_score("dwelling_above", "full", "cavity", "full") == 100
    assert insulation_sub_score("pitched_loft", None, "cavity", "none") is None
    a = _score(roof_type="dwelling_above", roof_insulation="none")
    b = _score(roof_type="dwelling_above", roof_insulation="full")
    assert _sub(a, "insulation") == _sub(b, "insulation") == 20


def test_insufficient_without_floor_area():
    r = _score(floor_area_m2=None)
    assert r.status == "insufficient"
    assert (r.score, r.score_raw, r.score_class, r.score_range, r.components) == (None, None, None, None, [])


def test_insufficient_with_too_many_unknown_features():
    fields = CFG.engine.validation.score_feature_fields
    limit = CFG.score.min_info["max_unknown_feature_fields"]
    assert _score(unknown=tuple(fields[:limit])).status == "ok"
    assert _score(unknown=tuple(fields[: limit + 1])).status == "insufficient"


def test_insufficient_when_rating_unknown_and_energy_imputed():
    clean = make_clean(unknown=("energy_rating",))
    assert compute_score(clean).status == "ok"
    clean.provenance["gas_kwh"] = "imputed"
    assert compute_score(clean).status == "insufficient"
    known_rating = make_clean()
    known_rating.provenance["gas_kwh"] = "imputed"
    r = compute_score(known_rating)
    assert r.status == "ok" and r.components[1].provenance == "imputed"


def test_insufficient_without_energy():
    assert compute_score(make_clean(gas_kwh=None)).status == "insufficient"


def test_score_range_contains_score_and_widens_with_unknowns():
    widths = []
    nested = [(), ("glazing",), ("glazing", "smart_controls"), ("glazing", "smart_controls", "energy_rating")]
    for unknown in nested:
        r = _score(unknown=unknown)
        lo, hi = r.score_range
        assert lo <= r.score <= hi
        widths.append((lo, hi))
    for (lo1, hi1), (lo2, hi2) in zip(widths, widths[1:], strict=False):
        assert lo2 <= lo1 and hi2 >= hi1
    assert widths[0][0] == widths[0][1]
    r = _score(unknown=("glazing", "energy_rating"))
    ranges = {c.key: c.sub_score_range for c in r.components}
    assert ranges["glazing"] == (0, 100)
    assert ranges["energy_efficiency"] == (CFG.score.energy_efficiency["F"], CFG.score.energy_efficiency["D"])
    assert ranges["heating"] is None and ranges["consumption_intensity"] is None
    assert next(c.provenance for c in r.components if c.key == "glazing") == "imputed"


def test_score_is_deterministic():
    clean = make_clean(unknown=("glazing", "wall_insulation"))
    assert compute_score(clean).model_dump() == compute_score(clean).model_dump()
