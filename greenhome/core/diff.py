"""Base vs scenario comparison (CR-2): one function feeds the what-if UI table and P4's diff facts.

`score` / `score_class` are the home's current score: they change only when a scenario overrides home
fields. `score_after` / `class_after` are the score after each result's package, so they show what a
scenario's retrofits do. Energy rows compare `savings.saving` (positive = reduction, §7.1);
delta = new − base, unrounded.
"""

from __future__ import annotations

from typing import Any, get_args

from greenhome.contracts import AnalysisResult, DiffKey, DiffRow, ResultDiff

_ROWS: dict[str, tuple[str, Any]] = {  # key → (unit, getter)
    "score": ("score", lambda r: r.score.score),
    "score_class": ("class", lambda r: r.score.score_class),
    "score_after": ("score", lambda r: r.score_after and r.score_after.score),
    "class_after": ("class", lambda r: r.score_after and r.score_after.score_class),
    "electricity_kwh": ("kwh_per_year", lambda r: r.savings.saving and r.savings.saving.electricity_kwh),
    "gas_kwh": ("kwh_per_year", lambda r: r.savings.saving and r.savings.saving.gas_kwh),
    "net_kwh": ("kwh_per_year", lambda r: r.savings.saving and r.savings.saving.net_kwh),
    "improvement_potential_pct": ("pct", lambda r: r.savings.improvement_potential_pct),
    "carbon_total_kg": ("kg_per_year", lambda r: r.carbon and r.carbon.total_kg),
    "value_uplift_pct_mid": ("pct", lambda r: r.value.uplift_pct_mid),
    "rating_after": ("rating", lambda r: r.value.rating_after),
    "sap_after": ("sap", lambda r: r.value.sap_after),
}
assert tuple(_ROWS) == get_args(DiffKey), "diff rows must follow contracts.DiffKey order"


def diff_results(base: AnalysisResult, new: AnalysisResult) -> ResultDiff:
    rows = []
    for key, (unit, get) in _ROWS.items():
        b, n = get(base), get(new)
        numeric = unit not in ("class", "rating") and b is not None and n is not None
        rows.append(DiffRow(key=key, unit=unit, base=b, new=n, delta=n - b if numeric else None))
    base_set, new_set = set(base.savings.retrofits), set(new.savings.retrofits)
    return ResultDiff(
        base_analysis_id=base.analysis_id,
        new_analysis_id=new.analysis_id,
        rows=rows,
        retrofits_added=[r for r in new.savings.retrofits if r not in base_set],
        retrofits_removed=[r for r in base.savings.retrofits if r not in new_set],
    )
