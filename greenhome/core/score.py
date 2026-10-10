"""Green Home Score (README P2.4) and its minimum-information policy (README P2.5).

Every table, weight and bound comes from `config/score.yaml` (and the generated intensity bounds). One pure
helper, `_sub_scores`, turns a flat dict of values into the 7 sub-scores; the main path, the score-range
enumeration and the orchestrator's score_after (a new CleanHome through `compute_score`) all share it.
"""

from __future__ import annotations

import itertools
from typing import Any

from greenhome.config import get_config
from greenhome.contracts import (
    CleanHome,
    EnergyRating,
    Glazing,
    HeatingSystem,
    Provenance,
    Renewables,
    RoofInsulation,
    RoofType,
    ScoreComponent,
    ScoreResult,
    SmartControls,
    WallInsulation,
    WallType,
)
from greenhome.format import round_score

# Enum value sets enumerated for the score range (README §7.2).
_ENUMS: dict[str, type] = {
    "energy_rating": EnergyRating,
    "roof_type": RoofType,
    "roof_insulation": RoofInsulation,
    "wall_type": WallType,
    "wall_insulation": WallInsulation,
    "glazing": Glazing,
    "heating_system": HeatingSystem,
    "renewables": Renewables,
    "smart_controls": SmartControls,
}
# Which fields drive each component (and whose provenance it reports).
_COMPONENT_FIELDS: dict[str, tuple[str, ...]] = {
    "energy_efficiency": ("energy_rating",),
    "consumption_intensity": ("electricity_kwh", "gas_kwh", "floor_area_m2"),
    "insulation": ("roof_type", "roof_insulation", "wall_type", "wall_insulation"),
    "heating": ("heating_system",),
    "glazing": ("glazing",),
    "renewables": ("renewables",),
    "smart_controls": ("smart_controls",),
}
_UNKNOWN = {Provenance.imputed.value, Provenance.assumed.value}
_PROVENANCE_WORST_FIRST = [p.value for p in (Provenance.assumed, Provenance.imputed, Provenance.derived,
                                             Provenance.example, Provenance.user)]


def insulation_sub_score(
    roof_type: str | None, roof_insulation: str | None, wall_type: str | None, wall_insulation: str | None
) -> float | None:
    """roof_weight × roof + wall_weight × wall; the wall carries all the weight under a dwelling above."""
    ins = get_config().score.insulation
    if roof_type is None or wall_insulation is None:
        return None
    wall = ins.wall[wall_insulation]
    if isinstance(wall, dict):  # uninsulated walls differ by construction
        if wall_type is None:
            return None
        wall = wall[wall_type]
    if roof_type == RoofType.dwelling_above:
        return wall
    if roof_insulation is None:
        return None
    return ins.roof_weight * ins.roof[roof_insulation] + ins.wall_weight * wall


def _intensity_sub_score(intensity_kwh_m2: float | None) -> float | None:
    if intensity_kwh_m2 is None:
        return None
    b = get_config().intensity_bounds
    frac = (b.i_worst - intensity_kwh_m2) / (b.i_worst - b.i_best)
    return 100 * min(max(frac, 0.0), 1.0)


def _sub_scores(v: dict[str, Any]) -> dict[str, float | None]:
    """The 7 sub-scores (ScoreKey order) from flat values; None where an input is missing."""
    s = get_config().score

    def look(table: dict[str, float], key: str | None) -> float | None:
        return None if key is None else table[key]

    return {
        "energy_efficiency": look(s.energy_efficiency, v["energy_rating"]),
        "consumption_intensity": _intensity_sub_score(v["intensity_kwh_m2"]),
        "insulation": insulation_sub_score(
            v["roof_type"], v["roof_insulation"], v["wall_type"], v["wall_insulation"]
        ),
        "heating": look(s.heating, v["heating_system"]),
        "glazing": look(s.glazing, v["glazing"]),
        "renewables": look(s.renewables, v["renewables"]),
        "smart_controls": look(s.smart_controls, v["smart_controls"]),
    }


def _contributions(subs: dict[str, float]) -> dict[str, float]:
    w = get_config().score.weights
    return {k: w[k] * v for k, v in subs.items()}


def classify(score_raw: float) -> tuple[int, str]:
    """(rounded score, class); the class uses the ROUNDED score (inclusive lower bounds)."""
    score = round_score(score_raw)
    return score, next(c.class_ for c in get_config().score.classes if score >= c.min)


def _enough_info(clean: CleanHome, unknown: set[str]) -> bool:
    """README P2.5: floor area AND (known rating OR non-imputed annual energy) AND few unknown features."""
    cfg = get_config()
    energy_ok = clean.energy.purchased_kwh is not None and all(
        clean.provenance.get(f) != Provenance.imputed.value for f in ("electricity_kwh", "gas_kwh")
    )
    n_unknown = len(unknown & set(cfg.engine.validation.score_feature_fields))
    return (
        clean.home.floor_area_m2 is not None
        and ("energy_rating" not in unknown or energy_ok)
        and n_unknown <= cfg.score.min_info["max_unknown_feature_fields"]
    )


def _ranges(
    values: dict[str, Any], unknown: set[str]
) -> tuple[dict[str, tuple[float, float]], tuple[int, int]]:
    """Exact enumeration over every value of each unknown score field (and an imputed rating ± spread)."""
    cfg = get_config()
    options = {
        f: [e.value for e in _ENUMS[f]] for f in cfg.engine.validation.score_feature_fields if f in unknown
    }
    if "energy_rating" in unknown:
        bands = [r.value for r in EnergyRating]
        i, k = bands.index(values["energy_rating"]), cfg.score.score_range["rating_band_spread"]
        options["energy_rating"] = bands[max(i - k, 0) : i + k + 1]
    totals: list[int] = []
    seen: dict[str, list[float]] = {k: [] for k in _COMPONENT_FIELDS}
    for combo in itertools.product(*options.values()):
        subs = _sub_scores(values | dict(zip(options, combo, strict=True)))
        if None in subs.values():  # e.g. a roof type that needs a roof_insulation we don't have
            continue
        totals.append(round_score(sum(_contributions(subs).values())))
        for k, v in subs.items():
            seen[k].append(v)
    varied = [k for k, fs in _COMPONENT_FIELDS.items() if set(fs) & options.keys()]
    return {k: (min(seen[k]), max(seen[k])) for k in varied}, (min(totals), max(totals))


def _inputs(key: str, values: dict[str, Any], clean: CleanHome) -> dict[str, Any]:
    if key == "consumption_intensity":
        b = get_config().intensity_bounds
        return {
            "purchased_kwh": clean.energy.purchased_kwh,
            "floor_area_m2": clean.home.floor_area_m2,
            "intensity_kwh_m2": values["intensity_kwh_m2"],
            "i_best": b.i_best,
            "i_worst": b.i_worst,
        }
    return {f: values[f] for f in _COMPONENT_FIELDS[key]}


def _worst_provenance(clean: CleanHome, fields: tuple[str, ...]) -> str:
    return min(
        (clean.provenance.get(f, Provenance.user.value) for f in fields), key=_PROVENANCE_WORST_FIRST.index
    )


def compute_score(clean: CleanHome) -> ScoreResult:
    """Green Home Score with components, class and an exact range over unknown inputs (README P2.4/P2.5)."""
    s = get_config().score
    h = clean.home
    purchased = clean.energy.purchased_kwh
    values: dict[str, Any] = {f: getattr(h, f) for f in _ENUMS}
    values["intensity_kwh_m2"] = (
        None if purchased is None or h.floor_area_m2 is None else purchased / h.floor_area_m2
    )
    unknown = {f for f, p in clean.provenance.items() if p in _UNKNOWN}
    subs = _sub_scores(values)
    if None in subs.values() or not _enough_info(clean, unknown):
        return ScoreResult(
            status="insufficient", score=None, score_raw=None, score_class=None, score_range=None,
            components=[], method_version=s.method_version,
        )
    contributions = _contributions(subs)
    score_raw = sum(contributions.values())
    score, score_class = classify(score_raw)
    sub_ranges, score_range = _ranges(values, unknown)
    components = [
        ScoreComponent(
            key=k,
            weight=s.weights[k],
            sub_score=v,
            contribution=contributions[k],
            inputs=_inputs(k, values, clean),
            provenance=_worst_provenance(clean, _COMPONENT_FIELDS[k]),
            sub_score_range=sub_ranges.get(k),
        )
        for k, v in subs.items()
    ]
    return ScoreResult(
        status="ok", score=score, score_raw=score_raw, score_class=score_class, score_range=score_range,
        components=components, method_version=s.method_version,
    )
