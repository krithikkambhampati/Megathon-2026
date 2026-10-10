"""Number checker (README P4.4): every number in a reply must come from the fact sheet it was given.

check() runs on every LLM reply, and in tests on every template answer, so the user never sees an
unchecked number. Steps: extract numeric mentions → normalise to (|value|, unit class) → match against the
allowed set (display numbers of the sheet's facts, numbers in anything else the model saw, a few
context-bound structural numbers) within a tolerance → £ claims we never make → banned phrases (negation-
aware) → direction (an "increase" described as a saving).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from greenhome.contracts import CheckReport
from greenhome.llm.facts import Fact, FactSheet

# Fact.unit → (unit class, display step in the class's base unit). Base units: kWh, kg, £, %, points.
_FACT_UNIT: dict[str, tuple[str, float]] = {
    "kwh_per_year": ("kwh", 10),
    "kwh_per_m2": ("kwh", 1),
    "kg_per_year": ("co2", 10),
    "t_per_year": ("co2", 100),
    "gbp_value": ("gbp", 500),
    "gbp_cost": ("gbp", 10),
    "pct": ("pct", 0.1),
    "pp": ("pct", 0.1),
    "score": ("score", 1),
    "points": ("score", 0.1),
    "m2": ("plain", 1),
    "sap": ("score", 1),
    "count": ("score", 1),
}
_CLASS_STEP: dict[str, float] = {
    "gbp": 10,
    "pct": 0.1,
    "kwh": 10,
    "co2": 10,
    "score": 1,
    "plain": 1,
    "year": 0,
}
_REL_TOL = 0.005

BANNED: dict[str, str] = {  # name → regex; skipped when a negation comes just before
    "guarantee": r"\bguarantee[ds]?\b",
    "will increase your value": r"\bwill (?:definitely |certainly )?(?:increase|raise|boost) (?:your )?"
    r"(?:property |home |house )?value",
    "certainly save": r"\bcertainly save",
    "exactly <n>": r"\bexactly £?\d",
    "financial advice": r"\bfinancial advice\b",
    "mortgage advice": r"\byou should (?:re)?mortgage\b",
}
_BANNED_RE = {k: re.compile(p, re.IGNORECASE) for k, p in BANNED.items()}
_NEGATION = re.compile(
    r"\b(?:not|no|never|isn't|aren't|can't|cannot|without|nor)\b[^.!?;]{0,20}$", re.IGNORECASE
)

# £ claims there is never a fact for: a £ value increase and a £ bill saving.
_NEVER_CLAIMS = [
    re.compile(r"\b(?:add|increase|boost|raise)s?\b[^.!?;]{0,30}\bvalue\b[^.!?;]{0,15}£\s?\d", re.IGNORECASE),
    re.compile(r"£\s?[\d,.]+\s?k?\s*(?:a|per|each)\s*(?:year|month|yr)\b", re.IGNORECASE),
    re.compile(r"\bbills?\b[^.!?;]{0,20}£\s?\d", re.IGNORECASE),
]

_NUM_RE = re.compile(
    r"(?<![\w.,/£])"  # not inside a word or number (F7, CO2e, P10001)
    r"(?P<sign>[+−–-])?(?P<cur>£)?(?P<sign2>[−-])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<mult>\s?(?:k|m(?![²2\w])|bn|million|thousand)(?![a-zA-Z]))?"
    r"(?P<ord>st|nd|rd|th)?"
    r"(?:\s?(?P<unit>%|per\s?cent|pp\b|percentage points?|kwh|mwh|kg|tonnes?|t(?![\w])|/\s?100))?"
    r"(?![\w])",
    re.IGNORECASE,
)
_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "hundred": 100,
}
_WORD_RE = re.compile(
    r"\b(?P<w>"
    + "|".join(_WORDS)
    + r")(?:\s+(?P<scale>hundred|thousand))?\s+(?P<unit>kwh|kg|tonnes?|per\s?cent|"
    r"percent|pounds)\b",
    re.IGNORECASE,
)
_FRACTION_RE = re.compile(r"\b(?P<f>halve[sd]?|halving|a third of|a quarter of|half of)\b", re.IGNORECASE)
_FRACTION = {
    "halve": 50.0,
    "halves": 50.0,
    "halved": 50.0,
    "halving": 50.0,
    "half of": 50.0,
    "a third of": 33.3,
    "a quarter of": 25.0,
}
_RANGE_GAP = re.compile(r"^\s*(?:–|—|-|−|to|and)\s*$", re.IGNORECASE)
_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9}
_TIME_AFTER = re.compile(
    r"^\s*(?:years?|yrs?|months?|weeks?|days?|hours?|minutes?|times|x\b|%|£|kwh|kg|t\b)", re.IGNORECASE
)
_MONTHS_AFTER = re.compile(r"^\s*months?\b", re.IGNORECASE)

_SAVING_CUE = re.compile(
    r"\b(?:sav(?:e|es|ed|ing|ings)|reduc\w*|cut\w*|lower\w*|less|fall\w*|drop\w*|"
    r"decreas\w*)\b",
    re.IGNORECASE,
)
_INCREASE_CUE = re.compile(
    r"\b(?:increas\w*|ris(?:e|es|ing)|rose|goes up|go up|higher|extra|additional|"
    r"adds?|adding|more electricity|more gas)\b",
    re.IGNORECASE,
)
_CLAUSE_SPLIT = re.compile(
    r"[.;!?](?=\s|$)|\n|,\s*(?:but|while|whereas|although)\b", re.IGNORECASE
)  # not "3.5"


@dataclass
class Mention:
    raw: str
    value: float  # absolute value in the class's base unit
    negative: bool
    unit: str  # gbp | pct | kwh | co2 | score | plain | year
    span: tuple[int, int]


def _unit_class(unit: str | None, cur: bool) -> tuple[str, float]:
    """→ (class, multiplier into the base unit)."""
    if cur:
        return "gbp", 1
    if not unit:
        return "plain", 1
    u = unit.lower().replace(" ", "")
    if u in ("%", "percent", "pp") or u.startswith("percentagepoint"):
        return "pct", 1
    if u in ("kwh", "mwh"):
        return "kwh", 1000 if u == "mwh" else 1
    if u == "kg":
        return "co2", 1
    if u in ("t", "tonne", "tonnes"):
        return "co2", 1000
    if u == "pounds":
        return "gbp", 1
    if u.startswith("/"):
        return "score", 1
    return "plain", 1


def extract_numbers(text: str) -> list[Mention]:
    """Every numeric mention. A range's first end inherits the unit (or £) of the second, and vice versa."""
    raw: list[dict] = []
    for m in _NUM_RE.finditer(text):
        num = float(m["num"].replace(",", ""))
        if m["mult"]:
            num *= _MULT[m["mult"].strip().lower()]
        raw.append(
            {
                "m": m,
                "num": num,
                "cur": bool(m["cur"]),
                "unit": m["unit"],
                "neg": m["sign"] in ("−", "-", "–") or bool(m["sign2"]),
            }
        )
    for a, b in zip(raw, raw[1:], strict=False):  # "2–5%", "2 to 5 %", "£358,909 to 362,409", "2 - 5"
        gap = text[a["m"].end() : b["m"].start("num")].replace("£", "")
        if _RANGE_GAP.match(gap):
            if a["unit"] is None and not a["cur"] and b["unit"]:
                a["unit"] = b["unit"]
            if a["cur"] and not b["cur"] and b["unit"] is None:
                b["cur"] = True
            b["neg"] = False  # the dash is the range connector, not a minus sign
    out = []
    for r in raw:
        cls, mult = _unit_class(r["unit"], r["cur"])
        m = r["m"]
        value = r["num"] * mult
        if cls == "plain" and value.is_integer() and 1900 <= value <= 2100 and "," not in m["num"]:
            cls = "year"
        out.append(Mention(m.group(0).strip(), value, r["neg"], cls, (m.start(), m.end())))
    for m in _WORD_RE.finditer(text):
        value = float(_WORDS[m["w"].lower()]) * (
            1000 if (m["scale"] or "").lower() == "thousand" else 100 if m["scale"] else 1
        )
        cls, mult = _unit_class(m["unit"], False)
        out.append(Mention(m.group(0), value * mult, False, cls, (m.start(), m.end())))
    for m in _FRACTION_RE.finditer(text):
        out.append(Mention(m.group(0), _FRACTION[m["f"].lower()], False, "pct", (m.start(), m.end())))
    return sorted(out, key=lambda x: x.span)


@dataclass
class _Allowed:
    value: float
    unit: str
    tol: float
    direction: str | None


def _allowed(sheet: FactSheet, extra: list[Fact]) -> list[_Allowed]:
    out: list[_Allowed] = []
    for f in [*sheet.facts, *extra]:
        cls_step = _FACT_UNIT.get(f.unit)
        for m in extract_numbers(f.display):
            cls = m.unit
            if cls == "plain" and cls_step:
                cls = cls_step[0]
            step = cls_step[1] if cls_step and cls == cls_step[0] else _CLASS_STEP.get(cls, 1)
            out.append(_Allowed(m.value, cls, step / 2, f.direction))
        for m in extract_numbers(f.label):  # "(out of 100)"
            out.append(_Allowed(m.value, "plain", 0.5, None))
    for t in [*sheet.notes, *sheet.reasons.values()]:
        for m in extract_numbers(t):
            out.append(_Allowed(m.value, "plain", _CLASS_STEP.get(m.unit, 1) / 2, None))
    return out


def _compatible(mention: str, allowed: str) -> bool:
    if mention == "year":  # a year must appear as a year (or a bare number) in what the model saw
        return allowed in ("year", "plain")
    if mention == allowed:
        return True
    if mention == "plain":  # a bare number may echo any fact ("saves 840 a year")
        return True
    if allowed == "plain":  # numbers from notes/labels/reasons carry no unit
        return mention in ("score", "pct")
    return mention == "score" and allowed == "score"


def _structural(m: Mention, text: str) -> bool:
    """Numbers that are allowed without a fact: 0, small counts, the /100 scale, '12 months'."""
    after = text[m.span[1] : m.span[1] + 12]
    if m.value == 0:
        return True
    if m.unit == "plain" and m.value.is_integer() and 1 <= m.value <= 10 and not _TIME_AFTER.match(after):
        return True
    if m.value == 100 and m.unit in ("plain", "score"):
        return True
    return m.unit == "plain" and m.value == 12 and bool(_MONTHS_AFTER.match(after))


def _matches(m: Mention, allowed: list[_Allowed]) -> list[_Allowed]:
    hits = []
    for a in allowed:
        if not _compatible(m.unit, a.unit):
            continue
        tol = 0.0 if m.unit == "year" else max(a.tol, _REL_TOL * a.value)
        if abs(m.value - a.value) <= tol + 1e-9:
            hits.append(a)
    return hits


def _direction_ok(text: str, span: tuple[int, int]) -> bool:
    """For a number that is only ever an increase: the nearest direction cue (±6 words, same clause) must be
    an increase cue, not a saving cue. No cue at all is fine (e.g. '3,600 kWh/year increase' copied as is)."""
    starts = [0] + [m.end() for m in _CLAUSE_SPLIT.finditer(text) if m.end() <= span[0]]
    ends = [m.start() for m in _CLAUSE_SPLIT.finditer(text) if m.start() >= span[1]]
    clause_start, clause_end = max(starts), (min(ends) if ends else len(text))
    before = text[clause_start : span[0]].split()[-6:]
    after = text[span[1] : clause_end].split()[:6]

    def nearest(words: list[str], reverse: bool) -> str | None:
        seq = list(reversed(words)) if reverse else words
        for i in range(len(seq)):
            # look at 1- and 2-word windows so "goes up" / "more electricity" count
            w2 = " ".join(seq[i : i + 2] if not reverse else reversed(seq[i : i + 2]))
            for w in (seq[i], w2):
                if _INCREASE_CUE.search(w):
                    return f"up:{i}"
                if _SAVING_CUE.search(w):
                    return f"down:{i}"
        return None

    cues = [c for c in (nearest(before, True), nearest(after, False)) if c]
    if not cues:
        return True
    kind = min(cues, key=lambda c: int(c.split(":")[1])).split(":")[0]
    return kind == "up"


def banned_phrases(text: str) -> list[str]:
    """Banned claims in `text`, skipping negated ones ("not guaranteed" is required wording)."""
    out = []
    for rx in _BANNED_RE.values():
        for mt in rx.finditer(text):
            if not _NEGATION.search(text[max(0, mt.start() - 30) : mt.start()]):
                out.append(mt.group(0))
    return out


def check(text: str, sheet: FactSheet, *, extra_allowed: list[Fact] | None = None) -> CheckReport:
    """Check one reply against the sheet it was written from. `attempts` / `fallback_used` are left
    0 / False for the caller (explainer / chat) to fill in."""
    allowed = _allowed(sheet, list(extra_allowed or []))
    found: list[str] = []
    unsupported: list[str] = []
    for m in extract_numbers(text):
        found.append(m.raw)
        hits = _matches(m, allowed)
        if not hits:
            if not _structural(m, text):
                unsupported.append(m.raw)
            continue
        if all(h.direction == "up" for h in hits) and not _direction_ok(text, m.span):
            unsupported.append(f"{m.raw} (direction)")
    for rx in _NEVER_CLAIMS:
        unsupported += [f"{mt.group(0).strip()} (no such figure)" for mt in rx.finditer(text)]
    banned = banned_phrases(text)
    return CheckReport(
        passed=not unsupported and not banned,
        numbers_found=found,
        unsupported=unsupported,
        banned_phrases=banned,
        attempts=0,
        fallback_used=False,
    )


def feedback(report: CheckReport) -> str:
    """Retry message (README P4.4 rule 6), naming every kind of failure."""
    parts = []
    nums = [u for u in report.unsupported if not u.endswith(")")]
    if nums:
        parts.append(f"These numbers are not in FACTS: {', '.join(nums)}.")
    dirs = [u.removesuffix(" (direction)") for u in report.unsupported if u.endswith("(direction)")]
    if dirs:
        parts.append(f"These are increases, not savings: {', '.join(dirs)}. Say that use goes up.")
    never = [
        u.removesuffix(" (no such figure)") for u in report.unsupported if u.endswith("(no such figure)")
    ]
    if never:
        parts.append(f"There is no figure for this in FACTS: {'; '.join(never)}.")
    if report.banned_phrases:
        parts.append(f"Do not say: {', '.join(report.banned_phrases)}.")
    parts.append("Use only FACTS, copied exactly as written.")
    return " ".join(parts)
