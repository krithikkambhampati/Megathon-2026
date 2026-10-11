"""Memory proposals (BUILD_GUIDE P4.5, CR-1): message → `list[MemoryEventIn]`, rules first, LLM JSON fallback.

P4 NEVER stores anything. `chat()` returns the proposal; P5's UI asks the user to confirm, then P5 stores it.
A budget is only accepted if the user typed that amount (the LLM never supplies a number).
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import TypeAdapter, ValidationError

from greenhome.contracts import AnalysisResult, MemoryEventIn
from greenhome.llm import vocab
from greenhome.llm.budget import Deadline
from greenhome.llm.checker import extract_numbers
from greenhome.llm.client import LLMClient, LLMError
from greenhome.llm.settings import LLMSettings, get_llm_settings

log = logging.getLogger(__name__)

_CLAUSES = re.compile(r"\s*(?:[.;!?]+(?=\s|$)|,\s+|\s+(?:and|but|also|plus)\s+)\s*")
_COMPLETED = re.compile(
    r"\b(?:we|i)(?:'ve|\s+have)?\s+(?:already\s+|recently\s+|just\s+)?(?:installed|put\s+in|got|"
    r"fitted|had\b.*\b(?:fitted|put\s+in|installed|done)|have|had)\b"
)
_EXCLUDE = re.compile(
    r"\b(?:don't|do\s+not|doesn't|won't|wouldn't)\s+(?:want|like)\b|\bcan't\s+(?:have|get|fit|"
    r"install|afford)\b|\bcannot\s+(?:have|get|fit|install|afford)\b|\bnot\s+interested\b|"
    r"\bno\s+way\b|\bnot\s+(?:allowed|possible)\b"
)
_DECLINED = re.compile(r"\b(?:declined|said\s+no\s+to|turned\s+down|rejected|refused)\b")
_BUDGET = re.compile(
    r"\bbudget\b|\bup\s+to\s+£|\bspend\s+(?:up\s+to\s+|at\s+most\s+|no\s+more\s+than\s+)?£|"
    r"\bmax(?:imum)?\s+(?:of\s+)?£"
)
_PRIORITY = re.compile(r"\b(?:care|caring|priority|prioritise|prioritize|focus|mostly|most\s+important)\b")
_PRIORITY_WORDS = [
    ("carbon", re.compile(r"\b(?:carbon|co2|emissions?|climate|planet|environment\w*|green)\b")),
    ("bills", re.compile(r"\b(?:bills?|money|costs?|cheap\w*|running\s+costs?|saving\s+money)\b")),
    ("value", re.compile(r"\b(?:value|resale|selling|price)\b")),
    ("balanced", re.compile(r"\b(?:balanced|a\s+mix|everything\s+equally|all\s+of\s+(?:them|it))\b")),
]
_MONTH = re.compile(
    r"\b(?P<y>20\d\d)-(?P<m>0[1-9]|1[0-2])\b|\b(?P<name>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|"
    r"nov|dec)[a-z]*\s+(?P<y2>20\d\d)\b"
)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

_EVENTS = TypeAdapter(list[MemoryEventIn])


def _month(text: str) -> str | None:
    """'2024-03' or 'March 2024' → '2024-03'. Vague dates ('last year') stay None."""
    m = _MONTH.search(text)
    if not m:
        return None
    if m["y"]:
        return f"{m['y']}-{m['m']}"
    return f"{m['y2']}-{_MONTHS.index(m['name'][:3]) + 1:02d}"


def _retrofits(clause: str) -> list[str]:
    out = []
    for m in vocab.find_retrofits(clause):
        r = "cavity_wall_insulation" if m.retrofit == "wall_any" else m.retrofit
        if r not in out:
            out.append(r)
    return out


def _user_amounts(message: str) -> list[float]:
    return [
        m.value for m in extract_numbers(message) if m.unit == "gbp" or (m.unit == "plain" and m.value >= 100)
    ]


def parse_rules(message: str) -> list[MemoryEventIn]:
    text = vocab.normalise(message)
    events: list[dict] = []
    for clause in [c for c in _CLAUSES.split(text) if c]:
        named = _retrofits(clause)
        if _BUDGET.search(clause):
            amounts = _user_amounts(clause)
            if amounts:
                events.append({"kind": "budget", "max_budget_gbp": amounts[0]})
                continue
        if _PRIORITY.search(clause):
            for prio, rx in _PRIORITY_WORDS:
                if rx.search(clause):
                    events.append({"kind": "preference", "priority": prio})
                    break
            else:
                continue
            continue
        if not named:
            continue
        if _DECLINED.search(clause):
            events += [{"kind": "response", "retrofit": r, "response": "declined"} for r in named]
        elif _EXCLUDE.search(clause):
            events += [{"kind": "exclude", "retrofit": r} for r in named]
        elif _COMPLETED.search(clause) and not vocab.HYPOTHETICAL.search(clause):
            when = _month(clause)
            events += [{"kind": "completed_retrofit", "retrofit": r, "completed_on": when} for r in named]
    seen, unique = set(), []
    for e in events:
        key = json.dumps(e, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append({"payload": e})
    return _EVENTS.validate_python(unique)


_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["completed_retrofit", "exclude", "budget", "preference", "response"],
                    },
                    "retrofit": {"type": "string"},
                    "max_budget_gbp": {"type": "number"},
                    "priority": {"type": "string", "enum": ["carbon", "bills", "value", "balanced"]},
                    "response": {"type": "string", "enum": ["accepted", "declined"]},
                },
                "required": ["kind"],
            },
        }
    },
    "required": ["events"],
}


def _parse_llm(message: str, llm: LLMClient, deadline: Deadline, s: LLMSettings) -> list[MemoryEventIn]:
    from greenhome.llm.explainer import render  # local import: explainer imports facts/checker

    try:
        raw = llm.generate(
            render("memory_parse.j2"),
            [{"role": "user", "content": message}],
            _SCHEMA,
            s.tokens("memory_parse", 200),
            timeout_s=deadline.call_timeout(s.cap("memory_parse")),
        )
        items = json.loads(raw).get("events") or []
    except (LLMError, ValueError, AttributeError) as e:
        log.info("memory LLM fallback failed (%s)", e)
        return []
    amounts = _user_amounts(message)
    kept = []
    for e in items:
        if not isinstance(e, dict):
            continue
        e = {k: v for k, v in e.items() if v is not None}
        if e.get("kind") == "completed_retrofit":
            e["completed_on"] = _month(vocab.normalise(message))  # never the LLM's date
        if e.get("kind") == "budget" and e.get("max_budget_gbp") not in amounts:
            continue  # a budget the user didn't type is invented
        try:
            kept += _EVENTS.validate_python([{"payload": e}])
        except ValidationError:
            continue
    return kept


def parse_memory(
    message: str,
    base: AnalysisResult | None = None,
    *,
    llm: LLMClient | None = None,
    deadline: Deadline | None = None,
    settings: LLMSettings | None = None,
) -> list[MemoryEventIn]:
    events = parse_rules(message)
    if events:
        return events
    s = settings or get_llm_settings()
    if llm is not None and deadline is not None and deadline.can_call(s.min_call_s):
        return _parse_llm(message, llm, deadline, s)
    return []
