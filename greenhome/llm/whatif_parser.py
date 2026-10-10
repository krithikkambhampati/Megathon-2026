"""What-if parser (README P4.5): message → a valid `Scenario`, rules first, LLM JSON as the fallback.

Operators are applied left to right to ONE working list of retrofits (docs/ROADMAP_P4.md), so a follow-up
like "and a heat pump but no loft insulation" builds on the current scenario. Numbers in overrides are the
user's own (e.g. "if my gas was 9,000 kWh"); P4 never makes one up. Feasibility is not checked here: P2's
`run_scenario` puts infeasible requests in `rejected` with a reason, and the answer explains it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from greenhome import format as fmt
from greenhome.contracts import AnalysisResult, HomeInput, Retrofit, Scenario
from greenhome.core.transitions import apply_retrofits
from greenhome.llm import vocab
from greenhome.llm._labels import label
from greenhome.llm.budget import Deadline
from greenhome.llm.client import LLMClient, LLMError
from greenhome.llm.facts import Fact
from greenhome.llm.settings import LLMSettings, get_llm_settings

log = logging.getLogger(__name__)

RETROFITS: tuple[str, ...] = tuple(r.value for r in Retrofit)
_UNKNOWN = ("imputed", "assumed")

_NUMBER = r"(?P<n>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<k>k\b)?"
_FUEL_USE = {
    "gas": re.compile(
        r"\bgas(?:\s+(?:use|usage|consumption))?\s+(?:was|were|is|of|at|went\s+down\s+to|"
        r"dropped\s+to|fell\s+to)\s+(?:about\s+|around\s+|only\s+)?" + _NUMBER + r"\s*(?:kwh)?"
    ),
    "electricity": re.compile(
        r"\belectric(?:ity)?(?:\s+(?:use|usage|consumption))?\s+(?:was|were|is|of|at|"
        r"went\s+down\s+to|dropped\s+to|fell\s+to)\s+(?:about\s+|around\s+|only\s+)?"
        + _NUMBER
        + r"\s*(?:kwh)?"
    ),
    "used": re.compile(r"\bused\s+" + _NUMBER + r"\s*kwh\s+(?:of\s+)?(?P<fuel>gas|electricity)"),
}
_RATING = re.compile(
    r"\b(?:rated|rating\s+(?:was|were|is|of)|epc\s+(?:was|of|is)|band)\s+(?:an?\s+)?(?P<r>[a-g])\b"
)
_ALREADY = re.compile(r"\b(?:already\s+(?:had|have|got)|had\s+already\s+(?:got|installed))\b")
_BUDGET = re.compile(r"\bbudget\b")
_MONEY = re.compile(r"£\s?\d")


@dataclass
class ParseResult:
    scenario: Scenario | None
    method: Literal["rules", "llm", "none"]
    clarify: str | None = None  # a question for the user when nothing valid could be built
    user_facts: list[Fact] = field(default_factory=list)  # the user's own numbers, shown back as facts


def _clarify(text: str) -> ParseResult:
    return ParseResult(None, "none", text)


def _resolve_wall(base: AnalysisResult) -> str | None:
    """'wall insulation' → cavity or solid by the home's wall type; None when the wall type is a guess."""
    if base.home.provenance.get("wall_type") in _UNKNOWN:
        return None
    return {"cavity": "cavity_wall_insulation", "solid": "solid_wall_insulation"}.get(
        base.home.home.wall_type
    )


def _op_for(text: str, before: str, previous: str | None) -> str:
    """Operator for one retrofit mention, from the words between it and the previous mention."""
    if previous is not None and vocab.CONNECTIVE.match(before):
        return previous
    if vocab.OP_REMOVE.search(before):
        return "remove"
    if vocab.OP_ONLY.search(before):
        return "only"
    if vocab.OP_ADD.search(before) or vocab.LEADING_AND.search(before):
        return "add"
    return previous or "mention"


def _energy_override(home: HomeInput, fuel: str, kwh: float) -> dict[str, Any]:
    """Replace one fuel's use, keeping the other fuel's readings (and their coverage) as the user gave them.

    Built from the user's raw input (`req.home`), never from the cleaned home, so imputed values are not
    relabelled as user data. The monthly readings for this fuel are blanked: otherwise they would win over
    the new annual figure (P2 annualise prefers monthly data).
    """
    energy = home.energy.model_dump()
    field_annual = "annual_gas_kwh" if fuel == "gas" else "annual_electricity_kwh"
    field_month = "gas_kwh" if fuel == "gas" else "electricity_kwh"
    energy[field_annual] = kwh
    if energy.get("monthly"):
        energy["monthly"] = [{**m, field_month: None} for m in energy["monthly"]]
    return {"energy": energy}


def _overrides(text: str, home: HomeInput, retrofits_named: list[str]) -> tuple[dict[str, Any], list[Fact]]:
    overrides: dict[str, Any] = {}
    facts: list[Fact] = []
    for name, rx in _FUEL_USE.items():
        for m in rx.finditer(text):
            fuel = m.groupdict().get("fuel") or name
            kwh = float(m["n"].replace(",", "")) * (1000 if m["k"] else 1)
            ov = _energy_override(HomeInput.model_validate({**home.model_dump(), **overrides}), fuel, kwh)
            overrides.update(ov)
            facts.append(
                Fact(
                    id="U",
                    key=f"user.annual_{fuel}_kwh",
                    value=kwh,
                    display=fmt.fmt_kwh(kwh),
                    unit="kwh_per_year",
                    label=f"Your stated yearly {fuel} use (used for this scenario)",
                )
            )
    if m := _RATING.search(text):
        overrides["energy_rating"] = m["r"].upper()
        facts.append(
            Fact(
                id="U",
                key="user.energy_rating",
                value=m["r"].upper(),
                display=m["r"].upper(),
                unit="rating",
                label="Energy rating you asked about",
            )
        )
    if _ALREADY.search(text) and retrofits_named:
        after = apply_retrofits(home, retrofits_named)  # P2's mapping, not a hand-written table
        changed = {k: v for k, v in after.model_dump().items() if v != home.model_dump().get(k)}
        changed.pop("energy", None)
        overrides.update(changed)
    return overrides, facts


def _name(mode: str, retrofits: list[str], overrides: dict) -> str:
    if mode != "custom":
        return {"recommended": "all recommended", "none": "no retrofits"}[mode]
    parts = [", ".join(retrofits) or "no retrofits"]
    if overrides:
        parts.append("with " + ", ".join(sorted(overrides)))
    return ("only " if retrofits else "") + " ".join(parts)


def parse_rules(message: str, home: HomeInput, base: AnalysisResult, current: Scenario | None) -> ParseResult:
    text = vocab.normalise(message)
    if _BUDGET.search(text):
        return _clarify(
            "A budget isn't part of a what-if scenario. Tell me your budget as a fact (for example "
            '"our budget is £8,000") and I can remember it once you confirm.'
        )
    if re.search(r"\bbills?\b", text) and _MONEY.search(text):
        return _clarify(
            "I can only use energy use in kWh for a what-if, not bills in pounds. "
            "Roughly how many kWh of gas or electricity do you use a year?"
        )
    mentions = vocab.find_retrofits(text)
    if any(m.retrofit == "wall_any" for m in mentions):
        wall = _resolve_wall(base)
        if wall is None:
            return _clarify(
                "Do you have cavity walls or solid walls? The right wall insulation depends on it."
            )
        for m in mentions:
            if m.retrofit == "wall_any":
                m.retrofit = wall

    already = bool(_ALREADY.search(text))
    named = list(dict.fromkeys(m.retrofit for m in mentions))
    overrides, facts = _overrides(text, home, named if already else [])
    if already:
        mentions = []  # "if I already had X": X changes the home (an override), not the package

    if not mentions:
        if vocab.EVERYTHING.search(text):
            return ParseResult(
                Scenario(name="all recommended", mode="recommended", overrides=overrides),
                "rules",
                user_facts=facts,
            )
        if vocab.NOTHING.search(text):
            return ParseResult(
                Scenario(name="no retrofits", mode="none", overrides=overrides), "rules", user_facts=facts
            )
        if overrides:  # a changed home with the current (or recommended) package
            if current is not None and current.mode == "custom":
                sc = Scenario(
                    name=_name("custom", list(current.retrofits), overrides),
                    mode="custom",
                    retrofits=list(current.retrofits),
                    overrides={**current.overrides, **overrides},
                )
            else:
                sc = Scenario(
                    name="all recommended with " + ", ".join(sorted(overrides)),
                    mode="recommended",
                    overrides=overrides,
                )
            return ParseResult(sc, "rules", user_facts=facts)
        return ParseResult(None, "none")

    # Operators, left to right on one working list.
    instead = vocab.INSTEAD_OF.search(text)  # "X instead of Y": X added, Y removed
    ops: list[tuple[str, str]] = []
    prev_end, prev_op = 0, None
    for m in mentions:
        if instead:
            op = "add" if m.end <= instead.start() else "remove"
        else:
            op = _op_for(text, text[prev_end : m.start], prev_op)
        ops.append((op, m.retrofit))
        prev_end, prev_op = m.end, op

    custom = current is not None and current.mode == "custom"
    if any(op == "only" for op, _ in ops):
        work: list[str] = []
    elif custom:
        work = list(current.retrofits)
    elif instead or ops[0][0] == "remove":
        work = list(base.savings.retrofits)
    else:
        work = []  # "install X" with no current scenario → custom [X]
    for op, r in ops:
        if op == "remove":
            work = [x for x in work if x != r]
        elif r not in work:
            work.append(r)
    merged = {**(current.overrides if custom else {}), **overrides}
    return ParseResult(
        Scenario(name=_name("custom", work, merged), mode="custom", retrofits=work, overrides=merged),
        "rules",
        user_facts=facts,
    )


def _validate(scenario: Scenario, home: HomeInput) -> Scenario | None:
    """A scenario is only returned if its overrides make a valid HomeInput (the engine would raise)."""
    try:
        HomeInput.model_validate({**home.model_dump(), **scenario.overrides})
        return Scenario.model_validate(scenario.model_dump())
    except ValidationError as e:
        log.info("what-if overrides rejected: %s", e.errors()[:1])
        return None


SCENARIO_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["recommended", "custom", "none"]},
        "retrofits": {"type": "array", "items": {"type": "string", "enum": list(RETROFITS)}},
    },
    "required": ["mode", "retrofits"],
}


def _parse_llm(
    message: str,
    base: AnalysisResult,
    current: Scenario | None,
    llm: LLMClient,
    deadline: Deadline,
    s: LLMSettings,
) -> Scenario | None:
    from greenhome.llm.explainer import render  # local import: explainer imports facts/checker

    system = render(
        "whatif_parse.j2",
        retrofits={r: label("Retrofit", r) for r in RETROFITS},
        base_package=list(base.savings.retrofits),
        current=list(current.retrofits) if current is not None and current.mode == "custom" else None,
    )
    try:
        raw = llm.generate(
            system,
            [{"role": "user", "content": message}],
            SCENARIO_SCHEMA,
            s.tokens("whatif_parse", 200),
            timeout_s=deadline.call_timeout(s.cap("whatif_parse")),
        )
        data = json.loads(raw)
        retrofits = list(dict.fromkeys(data.get("retrofits") or []))
        mode = data.get("mode")
        return Scenario(
            name=_name(mode, retrofits, {}) if mode in ("custom", "recommended", "none") else "llm",
            mode=mode,
            retrofits=retrofits if mode == "custom" else [],
        )
    except (LLMError, ValueError, ValidationError, TypeError, KeyError) as e:
        log.info("what-if LLM fallback failed (%s)", e)
        return None


def parse_whatif(
    message: str,
    home: HomeInput,
    base: AnalysisResult,
    current: Scenario | None = None,
    *,
    llm: LLMClient | None = None,
    deadline: Deadline | None = None,
    settings: LLMSettings | None = None,
) -> ParseResult:
    """`home` is the user's raw input (req.home); `base` gives the recommended package and provenance."""
    res = parse_rules(message, home, base, current)
    if res.clarify:
        return res
    if res.scenario is not None:
        sc = _validate(res.scenario, home)
        if sc is not None:
            return ParseResult(sc, "rules", user_facts=res.user_facts)
        return _clarify("I couldn't use that change to your home. Could you say it another way?")
    s = settings or get_llm_settings()
    if llm is not None and deadline is not None and deadline.can_call(s.min_call_s):
        sc = _parse_llm(message, base, current, llm, deadline, s)
        if sc is not None and (sc := _validate(sc, home)) is not None:
            return ParseResult(sc, "llm")
    return _clarify(
        'Which retrofits would you like to try? For example: "only solar panels", '
        '"everything except the heat pump" or "add cavity wall insulation".'
    )
