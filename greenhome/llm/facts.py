"""Fact sheets (README P4.2): AnalysisResult → the only numbers the LLM and the templates may use.

Every display string comes from `greenhome/format.py`, so the chat says exactly what the screens say.
Diff facts come from `greenhome/core/diff.py`; P4 does no arithmetic on result numbers (the one conversion
is a score weight fraction → percent for display). Sections that are `insufficient` / `out_of_scope` give a
status, never a number.

A sheet has two views of the same strings: `facts` (flat, numbered: what the prompt shows and what the
checker allows) and `view` (nested: what the Jinja templates iterate over). The model sees only each fact's
label and display string, never the raw value.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from greenhome import format as fmt
from greenhome.config import get_config
from greenhome.contracts import AnalysisResult, DataFlag, FuelSaving, ResultDiff, RetrofitRecommendation
from greenhome.core.diff import diff_results
from greenhome.llm._labels import (
    LABELS,
    SCORE_COMPONENT,
    field_label,
    flag_text,
    issue_text,
    label,
    reason_text,
)

SheetSection = Literal["score", "recommendations", "savings", "value", "whatif", "memory"]
FactUnit = Literal[
    "kwh_per_year",
    "kwh_per_m2",
    "kg_per_year",
    "t_per_year",
    "gbp_value",
    "gbp_cost",
    "pct",
    "pp",
    "score",
    "points",
    "m2",
    "sap",
    "count",
    "rating",
    "class",
    "text",
]
Direction = Literal["up", "down"] | None

_SEVERITY = {"error": 0, "warning": 1, "info": 2}
_ESTIMATED = ("MISSING_FIELD", "IMPUTED_FIELD")
_FUEL = {"electricity_kwh": "electricity", "gas_kwh": "gas", "net_kwh": "net (electricity + gas)"}
# Every enum value with an underscore → its label, to clean engine messages ("gas_boiler_condensing").
_ENUM_LABEL = {v: lab for table in LABELS.values() for v, lab in table.items() if "_" in v}
_ENUM_TOKEN = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b")


class Fact(BaseModel):
    id: str  # "F1", "F2", … in sheet order
    key: str  # "savings.saving.electricity_kwh"
    value: float | str | None  # raw engine value: never shown to the model or the user
    display: str  # the exact format.py string the UI shows
    unit: FactUnit
    label: str  # what the number is, in words: "Heat pump · electricity saving"
    direction: Direction = None  # "up" = use or emissions rise (from the sign; no arithmetic)


class FactSheet(BaseModel):
    section: SheetSection
    facts: list[Fact]
    notes: list[str]  # DATA_NOTES
    reasons: dict[str, str]  # REASONS: code → plain text, for every code on this sheet
    statuses: dict[str, str]  # score / savings / value → ok | insufficient | out_of_scope
    view: dict[str, Any]  # nested display strings for templates

    def get(self, key: str) -> Fact | None:
        return next((f for f in self.facts if f.key == key), None)

    def lines(self) -> str:
        """Prompt form, one fact per line: `F7 Heat pump · electricity saving: 3,600 kWh/year increase`."""
        return "\n".join(f"{f.id} {f.label}: {f.display}" for f in self.facts)


def _rounds_negative(x: float, step: float = 10) -> bool:
    return fmt.round_half_up(x, step) < 0


def _is_zero(x: float | None, step: float = 10) -> bool:
    return x is not None and fmt.round_half_up(x, step) == 0


class _Builder:
    def __init__(self) -> None:
        self.facts: list[Fact] = []
        self.reasons: dict[str, str] = {}

    def add(
        self, key: str, value: Any, display: str, unit: str, lab: str, direction: Direction = None
    ) -> str:
        """Record a fact and return its display string (for the template view)."""
        self.facts.append(
            Fact(
                id=f"F{len(self.facts) + 1}",
                key=key,
                value=value,
                display=display,
                unit=unit,
                label=lab,
                direction=direction,
            )
        )
        return display

    def num(
        self,
        key: str,
        value: float | None,
        fn: Callable[[float | None], str],
        unit: str,
        lab: str,
        direction: Direction = None,
    ) -> str | None:
        """A numeric fact; None values are not facts (there is nothing to say)."""
        return None if value is None else self.add(key, value, fn(value), unit, lab, direction)

    def saving(
        self, key: str, value: float | None, fn: Callable[[float | None], str], unit: str, lab: str
    ) -> str | None:
        """A saving (positive = reduction). A negative one is displayed '… increase' and marked 'up'."""
        if value is None:
            return None
        return self.add(key, value, fn(value), unit, lab, "up" if _rounds_negative(value) else "down")

    def text(self, key: str, value: str | None, display: str | None, lab: str) -> str | None:
        return None if value is None else self.add(key, value, display or value, "text", lab)

    def reason(self, code: str) -> str:
        self.reasons[code] = reason_text(code)
        return self.reasons[code]


def ef_source_name(src: str) -> str:
    """'electricity: DESNZ … factors 2026, flat file v1.2 (https://…); gas: …' → 'DESNZ … factors 2026'."""
    first = src.split(";")[0].split(" (http")[0]
    return first.split(": ", 1)[-1].split(",")[0].strip()


def humanise(message: str) -> str:
    """Engine messages sometimes embed raw enum values; show their labels instead."""
    return _ENUM_TOKEN.sub(lambda m: _ENUM_LABEL.get(m.group(0), m.group(0)).lower(), message)


# ---------- notes (DATA_NOTES) ----------
def data_notes(flags: list[DataFlag]) -> list[str]:
    """Deduped flag texts, problems first. Missing/estimated answers are grouped into one note that lists
    the fields (no count: P4 doesn't compute numbers, and the raw imputed values aren't formatted)."""
    seen: set[tuple[str, str | None]] = set()
    estimated: list[str] = []
    notes: list[str] = []
    for f in sorted(flags, key=lambda f: _SEVERITY.get(f.severity, 3)):
        if (f.code, f.field) in seen:
            continue
        seen.add((f.code, f.field))
        if f.code in _ESTIMATED:
            name = field_label(f.field).lower() if f.field else ""
            if name and name not in estimated:
                estimated.append(name)
        else:
            notes.append(humanise(f.message))
    if estimated:
        notes.append(f"{flag_text('IMPUTED_FIELD')} for answers not given: {', '.join(estimated)}.")
    return notes


# ---------- sections ----------
def _score(b: _Builder, r: AnalysisResult) -> dict:
    s = r.score
    v: dict[str, Any] = {"status": s.status, "is_poor": r.is_poor}
    if s.status == "ok":
        v["score"] = b.num("score.score", s.score, fmt.fmt_score, "score", "Green Home Score (out of 100)")
        v["class"] = b.text(
            "score.score_class", s.score_class, label("ScoreClass", s.score_class), "Score class"
        )
        v["bands"] = b.text(
            "score.class_bands",
            "classes",
            ", ".join(
                f"{label('ScoreClass', c.class_)} from {fmt.fmt_score(c.min)}"
                for c in get_config().score.classes
            ),
            "Score classes (each starts at this score)",
        )
        if s.score_range and s.score_range[0] != s.score_range[1]:
            v["range"] = b.add(
                "score.score_range",
                f"{s.score_range[0]}-{s.score_range[1]}",
                fmt.fmt_range(*s.score_range, fmt.fmt_score),
                "score",
                "Possible score range, because some answers are unknown",
            )
        v["components"] = []
        for c in sorted(s.components, key=lambda c: -c.weight):
            name = SCORE_COMPONENT.get(c.key, c.key)
            k = f"score.components.{c.key}"
            comp = {
                "key": c.key,
                "name": name,
                "weight": b.add(
                    f"{k}.weight", c.weight, fmt.fmt_pct(c.weight * 100), "pct", f"{name} · weight"
                ),
                "sub_score": b.num(
                    f"{k}.sub_score",
                    c.sub_score,
                    fmt.fmt_points,
                    "points",
                    f"{name} · sub-score (out of 100)",
                ),
                "contribution": b.num(
                    f"{k}.contribution",
                    c.contribution,
                    fmt.fmt_points,
                    "points",
                    f"{name} · points it adds to the score (weight × sub-score)",
                ),
                "provenance": None if c.provenance == "user" else label("Provenance", c.provenance),
            }
            if c.sub_score_range and c.sub_score_range[0] != c.sub_score_range[1]:
                comp["range"] = b.add(
                    f"{k}.sub_score_range",
                    f"{c.sub_score_range}",
                    fmt.fmt_range(*c.sub_score_range, fmt.fmt_score),
                    "score",
                    f"{name} · possible sub-score range",
                )
            v["components"].append(comp)
    area = r.home.home.floor_area_m2
    if s.status == "ok" and area is not None:
        guessed = r.home.provenance.get("floor_area_m2") in ("imputed", "assumed")
        v["area"] = b.num(
            "home.floor_area_m2",
            area,
            fmt.fmt_area,
            "m2",
            "Floor area" + (" (estimated, not given)" if guessed else ""),
        )
    if s.status == "ok" and r.peer is not None:
        v["peer"] = {
            "intensity": b.num(
                "peer.intensity_kwh_m2",
                r.peer.intensity_kwh_m2,
                fmt.fmt_intensity,
                "kwh_per_m2",
                "Your energy use per m²",
            ),
            "p50": b.num(
                "peer.p50_kwh_m2",
                r.peer.p50_kwh_m2,
                fmt.fmt_intensity,
                "kwh_per_m2",
                "Typical (median) use per m² for similar homes",
            ),
        }
    v["issues"] = [
        b.text(
            f"issues.{n}.{i.code}",
            i.code,
            f"{issue_text(i.code)} ({humanise(i.message)})",
            f"Problem area ({i.severity})",
        )
        for n, i in enumerate(r.issues)
    ]
    if r.score_after is not None and r.score_after.status == "ok":
        v["after"] = {
            "score": b.num(
                "score_after.score",
                r.score_after.score,
                fmt.fmt_score,
                "score",
                "Score after all recommended retrofits",
            ),
            "class": b.text(
                "score_after.score_class",
                r.score_after.score_class,
                label("ScoreClass", r.score_after.score_class),
                "Score class after all recommended retrofits",
            ),
        }
    return v


def _fuel_savings(b: _Builder, key: str, s: FuelSaving | None, lab: str) -> dict | None:
    """Per-fuel saving facts; fuels that round to zero are dropped (nothing changes)."""
    if s is None:
        return None
    out: dict[str, Any] = {}
    for fuel, word in _FUEL.items():
        x = getattr(s, fuel)
        if not _is_zero(x):
            out[fuel] = b.saving(f"{key}.{fuel}", x, fmt.fmt_kwh_saving, "kwh_per_year", f"{lab} · {word}")
            out[f"{fuel}_increase"] = _rounds_negative(x)
    return out


def _rec(b: _Builder, rec: RetrofitRecommendation, *, full: bool, incremental: bool) -> dict:
    name = label("Retrofit", rec.retrofit)
    k = f"recommendations.{rec.retrofit}"
    v: dict[str, Any] = {
        "retrofit": rec.retrofit,
        "name": name,
        "feasibility": rec.feasibility,
        "feasibility_label": label("Feasibility", rec.feasibility),
        "reasons": [b.reason(c) for c in rec.reasons],
        "reason_codes": list(rec.reasons),
    }
    if not full:
        return v
    v["rank"] = b.num(f"{k}.rank", rec.rank, str, "count", f"{name} · position in the recommended order")
    v["suitability"] = None if rec.suitability is None else label("Suitability", rec.suitability)
    v["depends_on"] = [label("Retrofit", d) for d in rec.depends_on]
    v["standalone"] = _fuel_savings(
        b, f"{k}.standalone_saving", rec.standalone_saving, f"{name} on its own · estimated saving"
    )
    if incremental:
        v["incremental"] = _fuel_savings(
            b,
            f"{k}.incremental_saving",
            rec.incremental_saving,
            f"{name} in the recommended order · estimated saving",
        )
    if rec.standalone_carbon_kg is not None and not _is_zero(rec.standalone_carbon_kg):
        v["carbon"] = b.saving(
            f"{k}.standalone_carbon_kg",
            rec.standalone_carbon_kg,
            fmt.fmt_kg_saving,
            "kg_per_year",
            f"{name} on its own · estimated carbon saving",
        )
    if rec.cost_low_gbp is not None and rec.cost_high_gbp is not None:
        v["cost"] = b.add(
            f"{k}.cost_gbp",
            f"{rec.cost_low_gbp}-{rec.cost_high_gbp}",
            fmt.fmt_range(rec.cost_low_gbp, rec.cost_high_gbp, fmt.fmt_gbp_cost),
            "gbp_cost",
            f"{name} · typical installed cost before grants",
        )
    return v


def _recommendations(b: _Builder, r: AnalysisResult, focus: list[str], only: list[str] | None = None) -> dict:
    """Feasible / needs-survey items in rank order with standalone savings; infeasible ones by name + reason.
    Items in `focus` (named by the user) get full detail incl. incremental savings (README P4 hazard 5).
    `only` restricts to a scenario's package (+ focus)."""
    shown, infeasible = [], []
    for rec in r.recommendations:
        if only is not None and rec.retrofit not in only and rec.retrofit not in focus:
            continue
        in_focus = rec.retrofit in focus
        if rec.feasibility == "infeasible":
            infeasible.append(_rec(b, rec, full=in_focus, incremental=in_focus))
        else:
            shown.append(_rec(b, rec, full=True, incremental=in_focus))
    return {"items": shown, "infeasible": infeasible, "savings_status": r.savings.status}


def _savings(b: _Builder, r: AnalysisResult) -> dict:
    s = r.savings
    v: dict[str, Any] = {"status": s.status, "retrofits": [label("Retrofit", x) for x in s.retrofits]}
    if s.status != "ok":
        return v
    words = {
        "electricity_kwh": "electricity",
        "gas_kwh": "gas",
        "purchased_kwh": "total bought (electricity + gas)",
    }
    for part, when in (("baseline", "today"), ("after", "after the recommended retrofits")):
        e = getattr(s, part)
        if e is not None:
            v[part] = {
                fuel: b.num(
                    f"savings.{part}.{fuel}",
                    getattr(e, fuel),
                    fmt.fmt_kwh,
                    "kwh_per_year",
                    f"Estimated yearly {w} use {when}",
                )
                for fuel, w in words.items()
                if not _is_zero(getattr(e, fuel))
            }
    v["saving"] = _fuel_savings(b, "savings.saving", s.saving, "All recommended retrofits · estimated saving")
    v["improvement"] = b.num(
        "savings.improvement_potential_pct",
        s.improvement_potential_pct,
        fmt.fmt_pct,
        "pct",
        "Improvement potential (share of today's bought energy saved)",
    )
    if r.carbon is not None:
        c = r.carbon
        lab = "All recommended retrofits · estimated carbon saving"
        v["carbon"] = {
            "total": b.saving("carbon.total_kg", c.total_kg, fmt.fmt_kg_saving, "kg_per_year", lab),
            "increase": _rounds_negative(c.total_kg),
            "electricity": None
            if _is_zero(c.electricity_kg)
            else b.saving(
                "carbon.electricity_kg",
                c.electricity_kg,
                fmt.fmt_kg_saving,
                "kg_per_year",
                f"{lab} · electricity",
            ),
            "gas": None
            if _is_zero(c.gas_kg)
            else b.saving("carbon.gas_kg", c.gas_kg, fmt.fmt_kg_saving, "kg_per_year", f"{lab} · gas"),
            "source": b.text(
                "carbon.ef_source", c.ef_source, ef_source_name(c.ef_source), "Emission factors source"
            ),
        }
        if c.total_kg > 0:  # fmt_tonnes does not handle negatives
            v["carbon"]["tonnes"] = b.num(
                "carbon.total_t", c.total_kg, fmt.fmt_tonnes, "t_per_year", f"{lab} (tonnes)", "down"
            )
    return v


def _value(b: _Builder, r: AnalysisResult) -> dict:
    x = r.value
    v: dict[str, Any] = {"status": x.status, "caveat": x.caveat_code}
    if x.rating_before is not None and x.rating_after is not None:
        v["rating"] = b.text(
            "value.rating_change",
            f"{x.rating_before}->{x.rating_after}",
            f"{x.rating_before} → {x.rating_after}",
            "Estimated EPC rating: today → after the recommended retrofits",
        )
    if x.status != "ok":
        return v
    src = "you told us" if x.current_value_source == "user" else "estimated by our model"
    v["current"] = b.num(
        "value.current_value_gbp",
        x.current_value_gbp,
        fmt.fmt_gbp_value,
        "gbp_value",
        f"Current property value ({src})",
    )
    v["current_source"] = x.current_value_source
    v["sap_before"] = b.num(
        "value.sap_before", x.sap_before, fmt.fmt_sap, "sap", "Estimated SAP points today"
    )
    v["sap_after"] = b.num(
        "value.sap_after",
        x.sap_after,
        fmt.fmt_sap,
        "sap",
        "Estimated SAP points after the recommended retrofits",
    )
    if x.uplift_pct_low is not None and x.uplift_pct_high is not None:
        v["uplift_range"] = b.add(
            "value.uplift_pct_range",
            f"{x.uplift_pct_low}-{x.uplift_pct_high}",
            fmt.fmt_range(x.uplift_pct_low, x.uplift_pct_high, fmt.fmt_pct),
            "pct",
            "Indicative value change range (not causal)",
        )
    v["uplift_mid"] = b.num(
        "value.uplift_pct_mid",
        x.uplift_pct_mid,
        fmt.fmt_pct,
        "pct",
        "Indicative value change, middle estimate (not causal)",
    )
    if x.value_low_gbp is not None and x.value_high_gbp is not None:
        v["value_range"] = b.add(
            "value.value_gbp_range",
            f"{x.value_low_gbp}-{x.value_high_gbp}",
            fmt.fmt_range(x.value_low_gbp, x.value_high_gbp, fmt.fmt_gbp_value),
            "gbp_value",
            "Indicative property value after the retrofits (range, not causal)",
        )
    return v


# ---------- what-if diff ----------
# key → (formatter for base/new, words). Energy and carbon rows compare SAVINGS (diff.py), not use.
_DIFF_ROWS: dict[str, tuple[Callable[[Any], str], str]] = {
    "score": (fmt.fmt_score, "Green Home Score today"),
    "score_after": (fmt.fmt_score, "Score after the retrofits"),
    "sap_after": (fmt.fmt_sap, "SAP points after the retrofits"),
    "electricity_kwh": (fmt.fmt_kwh_saving, "estimated electricity saving"),
    "gas_kwh": (fmt.fmt_kwh_saving, "estimated gas saving"),
    "net_kwh": (fmt.fmt_kwh_saving, "estimated net energy saving"),
    "improvement_potential_pct": (fmt.fmt_pct, "improvement potential (full feasible package)"),
    "value_uplift_pct_mid": (fmt.fmt_pct, "indicative value change, middle estimate"),
    "carbon_total_kg": (fmt.fmt_kg_saving, "estimated carbon saving"),
}
_UNIT = {
    "score": "score",
    "sap": "sap",
    "kwh_per_year": "kwh_per_year",
    "kg_per_year": "kg_per_year",
    "pct": "pct",
}
_DELTA_UNIT = {
    "score": "score",
    "sap": "sap",
    "kwh_per_year": "kwh_per_year",
    "kg_per_year": "kg_per_year",
    "pct": "pp",
}
_SAVING_ROWS = ("electricity_kwh", "gas_kwh", "net_kwh", "carbon_total_kg")


def _diff(b: _Builder, d: ResultDiff, overrides: bool) -> dict:
    rows: dict[str, Any] = {}
    for row in d.rows:
        k = f"diff.{row.key}"
        if row.base is None and row.new is None:
            continue
        if row.key == "improvement_potential_pct" and not overrides:
            continue  # always the full feasible package: a retrofit-only what-if never changes it
        if row.unit in ("class", "rating"):
            words = {
                "score_class": "Score class today",
                "class_after": "Score class after the retrofits",
                "rating_after": "Estimated EPC rating after the retrofits",
            }[row.key]

            def show(x: Any, unit: str = row.unit) -> str:
                return label("ScoreClass", x) if unit == "class" else (x or fmt.UNKNOWN)

            changed = row.base != row.new
            disp = f"{show(row.base)} → {show(row.new)}" if changed else show(row.new)
            rows[row.key] = {
                "change": b.text(
                    k,
                    f"{row.base}->{row.new}",
                    disp,
                    f"{words}: recommended plan → this scenario" if changed else words,
                ),
                "changed": changed,
            }
            continue
        f, words = _DIFF_ROWS[row.key]
        saving = row.key in _SAVING_ROWS
        add = b.saving if saving else b.num
        rows[row.key] = {
            "base": add(f"{k}.base", row.base, f, _UNIT[row.unit], f"Recommended plan · {words}"),
            "new": add(f"{k}.new", row.new, f, _UNIT[row.unit], f"This scenario · {words}"),
            "delta": b.num(
                f"{k}.delta",
                row.delta,
                lambda x, u=row.unit: fmt.fmt_delta(x, u),
                _DELTA_UNIT[row.unit],
                f"Change in {words}: this scenario vs the recommended plan",
            ),
            "changed": row.delta is not None and fmt.fmt_delta(row.delta, row.unit) != "0",
            "new_increase": saving and row.new is not None and _rounds_negative(row.new),
        }
    return {
        "rows": rows,
        "added": [
            b.text(f"diff.added.{x}", x, label("Retrofit", x), "Added compared with the recommended plan")
            for x in d.retrofits_added
        ],
        "removed": [
            b.text(
                f"diff.removed.{x}", x, label("Retrofit", x), "Left out compared with the recommended plan"
            )
            for x in d.retrofits_removed
        ],
    }


def build_fact_sheet(
    result: AnalysisResult,
    section: SheetSection,
    base: AnalysisResult | None = None,
    diff: ResultDiff | None = None,
    focus: list[str] | None = None,
    user_facts: list[Fact] | None = None,
) -> FactSheet:
    """One sheet per answer. `focus` = retrofits the user named (full detail, incl. infeasible ones).
    `user_facts` = numbers the user stated that went into an override or memory payload.

    `whatif` needs `base`: it holds the diff (recommended plan → scenario), the scenario's package with
    suitability and reasons, and every rejected item with its reason (README P4.3 rule 5).
    """
    b = _Builder()
    focus = list(focus or [])
    view: dict[str, Any] = {"property_type": label("PropertyType", result.home.home.property_type)}
    statuses = {"score": result.score.status, "savings": result.savings.status, "value": result.value.status}
    if section == "score":
        view["score"] = _score(b, result)
    elif section == "recommendations":
        view["recommendations"] = _recommendations(b, result, focus)
    elif section == "savings":
        view["savings"] = _savings(b, result)
    elif section == "value":
        view["value"] = _value(b, result)
    elif section == "whatif":
        if base is None:
            raise ValueError("a what-if fact sheet needs the base result")
        d = diff or diff_results(base, result)
        overrides = bool(result.scenario.overrides)
        view["scenario"] = {
            "mode": result.scenario.mode,
            "overrides": overrides,
            "package": list(result.savings.retrofits),
            "retrofits": [label("Retrofit", x) for x in result.savings.retrofits],
        }
        view["diff"] = _diff(b, d, overrides)
        view["recommendations"] = _recommendations(b, result, focus, only=list(result.savings.retrofits))
        view["rejected"] = [
            {
                "name": b.text(
                    f"rejected.{x.retrofit}",
                    x.retrofit,
                    label("Retrofit", x.retrofit),
                    "Asked for but not possible for this home",
                ),
                "reason": b.reason(x.reason),
                "reason_code": x.reason,
            }
            for x in result.rejected
        ]
    elif section != "memory":
        raise ValueError(f"unknown section {section!r}")
    for f in user_facts or []:
        b.add(f.key, f.value, f.display, f.unit, f.label, f.direction)
    return FactSheet(
        section=section,
        facts=b.facts,
        notes=data_notes(result.flags),
        reasons=b.reasons,
        statuses=statuses,
        view=view,
    )


def build_facts(result: AnalysisResult, base: AnalysisResult | None = None) -> list[Fact]:
    """README P4.2 signature: every fact for a result (4 sections, plus the what-if sheet if `base`)."""
    sections: list[SheetSection] = ["score", "recommendations", "savings", "value"]
    facts = [f for s in sections for f in build_fact_sheet(result, s).facts]
    if base is not None:
        facts += build_fact_sheet(result, "whatif", base=base).facts
    return [f.model_copy(update={"id": f"F{i + 1}"}) for i, f in enumerate(facts)]
