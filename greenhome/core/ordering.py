"""Suitability, prerequisites, install order and budget filtering of retrofits (README P2.8 steps 2–4, 6).

Thresholds come from `score.yaml: suitability`; stages, prerequisites and soft edges from the catalogue and
`engine.yaml: stage_order`.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass

from greenhome.config import get_config
from greenhome.contracts import Feasibility, FuelSaving, HomeInput, Retrofit, Suitability
from greenhome.core.score import insulation_sub_score

_WORST_LAST = [s.value for s in Suitability]  # high, medium, low


@dataclass(frozen=True)
class Candidate:
    retrofit: str
    feasibility: str  # feasible | needs_survey
    p_assessor: float
    standalone: FuelSaving | None  # None when savings are unavailable
    baseline_purchased_kwh: float | None


def prerequisites_met(retrofit: str, home: HomeInput, package: Iterable[str]) -> bool:
    """Every hard prerequisite holds: insulation sub-score ≥ min (unknown counts as below) or an enabling
    retrofit is in the package."""
    names = {str(r) for r in package}
    sub = insulation_sub_score(home.roof_type, home.roof_insulation, home.wall_type, home.wall_insulation)
    return all(
        (sub is not None and sub >= p.insulation_sub_score_min)
        or any(str(a) in names for a in p.or_in_package_any)
        for p in get_config().catalogue[str(retrofit)].prerequisites
    )


def _norm(x: float, values: Iterable[float]) -> float:
    top = max((v for v in values if v > 0), default=0.0)
    return 0.0 if top == 0 else min(max(x / top, 0.0), 1.0)


def _cap(level: str, cap: str) -> str:
    return max(level, cap, key=_WORST_LAST.index)


def _net_cost(retrofit: str) -> float:
    spec = get_config().catalogue[retrofit]
    return spec.cost_mid_gbp - spec.grant_gbp


def rate_suitability(
    cands: list[Candidate], home: HomeInput, package: Iterable[str], priority: str = "balanced"
) -> dict[str, tuple[float | None, str | None, list[str]]]:
    """r → (u, suitability, reasons). u = weighted assessor probability + normalised saving share + cost
    efficiency, weights chosen by the customer's `priority`; caps for needs_survey (medium) and unmet
    prerequisites (low + INSULATE_FIRST).

    # ponytail: "carbon" re-weights the net-kWh saving share rather than using a carbon share; the two
    # differ only by the elec/gas emission-factor gap. Upgrade: carry baseline carbon on Candidate.
    """
    cfg = get_config()
    s, rs = cfg.score.suitability, cfg.score.suitability.reasons
    w = s.priority_weights[priority]
    package = list(package)
    share: dict[str, float] = {}
    cost_eff: dict[str, float | None] = {}  # None = free after grant → normalised to 1.0
    for c in cands:
        if c.standalone is not None and c.baseline_purchased_kwh:
            share[c.retrofit] = c.standalone.net_kwh / c.baseline_purchased_kwh
            cost = _net_cost(c.retrofit)
            cost_eff[c.retrofit] = None if cost <= 0 else c.standalone.net_kwh / (cost / 1000)
    positive_eff = [v for v in cost_eff.values() if v is not None]

    out: dict[str, tuple[float | None, str | None, list[str]]] = {}
    for c in cands:
        spec = cfg.catalogue[c.retrofit]
        reasons: list[str] = []
        u = level = None
        if c.retrofit in share:
            sh, sv, eff = share[c.retrofit], c.standalone, cost_eff[c.retrofit]
            u = (
                w["assessor"] * c.p_assessor
                + w["saving_share"] * _norm(sh, share.values())
                + w["cost_eff"] * (1.0 if eff is None else _norm(eff, positive_eff))
            )
            level = (
                Suitability.high if u >= s.high else Suitability.medium if u >= s.medium else Suitability.low
            ).value
            if sh >= rs.high_saving_share:
                reasons.append("HIGH_SAVING")
            if spec.cost_gbp[1] <= rs.quick_win_cost_max_gbp and sv.net_kwh > 0:
                reasons.append("QUICK_WIN_LOW_COST")
            if spec.cost_mid_gbp >= rs.high_cost_gbp and sh < rs.low_saving_share:
                reasons.append("HIGH_COST_LOW_SAVING")
            if sv.electricity_kwh < 0 and sv.gas_kwh > 0:
                reasons.append("ELECTRICITY_RISES_GAS_FALLS")
            if c.feasibility == Feasibility.needs_survey:
                level = _cap(level, Suitability.medium.value)
        if c.p_assessor >= rs.assessor_often:
            reasons.append("ASSESSORS_OFTEN_RECOMMEND")
        if not prerequisites_met(c.retrofit, home, package):
            reasons.append("INSULATE_FIRST")
            if level is not None:
                level = _cap(level, Suitability.low.value)
        out[c.retrofit] = (u, level, reasons)
    return out


def _sources(retrofit: str, names: set[str]) -> set[str]:
    """Retrofits in the package that must come before `retrofit` (soft_after + prerequisite enablers)."""
    spec = get_config().catalogue[retrofit]
    enablers = [a for p in spec.prerequisites for a in p.or_in_package_any]
    before = {str(a) for a in [*spec.soft_after, *enablers]}
    return before & names


def depends_on(retrofit: str, package: Iterable[str]) -> list[str]:
    srcs = _sources(str(retrofit), {str(r) for r in package})
    return [r.value for r in Retrofit if r.value in srcs]


def order_retrofits(package: Iterable[str], priority: dict[str, float]) -> list[str]:
    """Deterministic topological sort (Kahn + heap): stage, then higher priority, then catalogue order."""
    names = {str(r) for r in package}
    cfg = get_config()
    enum_idx = {r.value: i for i, r in enumerate(Retrofit)}

    def key(r: str) -> tuple[int, float, int, str]:
        return (cfg.engine.stage_order.index(cfg.catalogue[r].stage), -priority.get(r, 0.0), enum_idx[r], r)

    preds = {r: _sources(r, names) for r in names}
    heap = [key(r) for r in names if not preds[r]]
    heapq.heapify(heap)
    out: list[str] = []
    while heap:
        r = heapq.heappop(heap)[-1]
        out.append(r)
        for other, before in preds.items():
            if r in before:
                before.discard(r)
                if not before:
                    heapq.heappush(heap, key(other))
    if len(out) != len(names):
        raise ValueError(f"cycle in retrofit dependencies among {sorted(names - set(out))}")
    return out


def budget_filter(ordered_by_u: list[str], budget_gbp: float) -> tuple[list[str], list[str]]:
    """Greedy in the given order: keep r while cumulative net cost (floored at 0) fits the budget."""
    kept: list[str] = []
    dropped: list[str] = []
    total = 0.0
    for r in ordered_by_u:
        cost = max(_net_cost(str(r)), 0.0)
        if total + cost <= budget_gbp:
            kept.append(r)
            total += cost
        else:
            dropped.append(r)
    return kept, dropped
