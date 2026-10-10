"""Intent router (README P4.5): rules first, the LLM (JSON enum) only for messages no rule matches.

Order matters (docs/archive/ROADMAP_P4.md): hypotheticals are what-ifs before the memory rules run, so
"what if we had a heat pump" is not taken as a statement about the home.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from greenhome.llm import vocab
from greenhome.llm.budget import Deadline
from greenhome.llm.client import LLMClient, LLMError
from greenhome.llm.settings import LLMSettings, get_llm_settings

log = logging.getLogger(__name__)

Intent = Literal["whatif", "explain", "memory", "out_of_scope", "unclear"]
Section = Literal["score", "recommendations", "savings", "value"]
INTENTS: tuple[str, ...] = ("whatif", "explain", "memory", "out_of_scope", "unclear")

_MEMORY = [
    re.compile(
        r"\b(?:we|i)(?:'ve| have)?\s+(?:already\s+|recently\s+|just\s+)?(?:installed|put\s+in|got|fitted|"
        r"had\s+(?:\w+\s+){0,4}?(?:fitted|put\s+in|installed|done))\b"
    ),
    re.compile(r"\b(?:we|i)\s+(?:already|now)\s+(?:have|had|got)\b"),
    re.compile(r"\b(?:i|we)\s+(?:can't|cannot|can not)\s+(?:have|get|fit|afford|install)\b"),
    re.compile(r"\bbudget\b"),
    re.compile(r"\b(?:don't|do not|doesn't|won't)\s+want\b"),
    re.compile(r"\bnot\s+interested\b"),
    re.compile(r"\b(?:we|i)\s+(?:care|mostly\s+care|care\s+most|mainly\s+care)\s+(?:most\s+)?about\b"),
    re.compile(r"\b(?:our|my)\s+(?:main\s+)?priority\b"),
    re.compile(r"\b(?:we|i)\s+(?:declined|said\s+no\s+to|turned\s+down|rejected)\b"),
]
_EXPLAIN_START = re.compile(
    r"^(?:why|how|explain|what\s+does|what\s+do|what\s+is|what's|what\s+are|tell\s+me|can\s+you\s+explain|"
    r"could\s+you\s+explain|which|is\s+it|is\s+my|are\s+the|should\s+i|where|when)\b"
)
_EXPLAIN_ANY = re.compile(
    r"\b(?:why|how\s+come|how\s+much|how\s+does|explain|tell\s+me|show\s+me|what\s+is|"
    r"what's|what\s+are|what\s+does)\b"
)
_WHY = re.compile(r"\b(?:why|how|explain)\b")  # a why/how question stays an explanation
_QUESTION = re.compile(r"\?\s*$|^(?:would|will|is|are|does|do|can|could|should|has|have|did)\b")
_WEAK_WHATIF = re.compile(
    r"\b(?:only|just|without|except|excluding|skip|minus|apart\s+from|other\s+than|aside\s+from|but|add|also|"
    r"plus|install|get|fit|instead\s+of|drop|remove|leave\s+out)\b"
)
_CHANGE = re.compile(
    r"\b(?:go(?:es)?\s+up|went\s+up|go(?:es)?\s+down|drop(?:s|ped)?|chang\w*|differ\w*|"
    r"why\s+did|compared?)\b"
)

_SECTION_WORDS: list[tuple[str, re.Pattern]] = [
    ("value", re.compile(r"\b(?:value|price|worth|sell|sale|mortgage|uplift)\b")),
    ("score", re.compile(r"\b(?:score|rating|epc|class|points|sap|poor|band)\b")),
    (
        "savings",
        re.compile(
            r"\b(?:sav(?:e|es|ing|ings)|carbon|co2|emissions?|electricity|gas|kwh|bills?|"
            r"energy\s+use|use\s+more|use\s+less)\b"
        ),
    ),
    (
        "recommendations",
        re.compile(
            r"\b(?:recommend\w*|suitab\w*|retrofits?|order|first|feasible|why\s+not|"
            r"can\s+i|costs?|upgrade|improve\w*)\b"
        ),
    ),
]


@dataclass
class RouteResult:
    intent: Intent
    method: Literal["rules", "llm", "default"]
    section: Section = "score"
    focus: list[str] = field(default_factory=list)
    refers_to_change: bool = False  # "why did the score go up?" during a what-if


def _section(text: str, focus: list[str]) -> Section:
    if _SECTION_WORDS[0][1].search(text):
        return "value"
    if focus and not _SECTION_WORDS[1][1].search(text):
        return "recommendations"  # a named retrofit: its card has its own savings and reasons
    for name, rx in _SECTION_WORDS[1:]:
        if rx.search(text):
            return name  # type: ignore[return-value]
    return "score"


def _focus(text: str) -> list[str]:
    out: list[str] = []
    for m in vocab.find_retrofits(text):
        r = "cavity_wall_insulation" if m.retrofit == "wall_any" else m.retrofit
        if r not in out:
            out.append(r)
    return out


def route(
    message: str,
    *,
    has_scenario: bool = False,
    llm: LLMClient | None = None,
    deadline: Deadline | None = None,
    settings: LLMSettings | None = None,
) -> RouteResult:
    text = vocab.normalise(message)
    focus = _focus(text)
    mentions = bool(focus) or bool(vocab.EVERYTHING.search(text)) or bool(vocab.NOTHING.search(text))

    def res(intent: Intent, method: Literal["rules", "llm", "default"] = "rules") -> RouteResult:
        return RouteResult(
            intent, method, _section(text, focus), focus, has_scenario and bool(_CHANGE.search(text))
        )

    if not text:
        return res("unclear", "default")
    if vocab.HYPOTHETICAL.search(text) and (mentions or _override_cue(text)):
        return res("whatif")
    if any(rx.search(text) for rx in _MEMORY) and not text.endswith("?") or _memory_question(text):
        return res("memory")
    if (_EXPLAIN_START.search(text) or _EXPLAIN_ANY.search(text)) and vocab.DOMAIN.search(text):
        if _WEAK_WHATIF.search(text) and mentions and not _WHY.search(text):
            return res("whatif")
        return res("explain")
    package_word = bool(vocab.EVERYTHING.search(text) or vocab.NOTHING.search(text))
    if mentions and (
        _WEAK_WHATIF.search(text) or vocab.LEADING_AND.search(text) or has_scenario or package_word
    ):
        return res("whatif")  # "everything except the heat pump", "everything", "skip solar"
    if not vocab.DOMAIN.search(text):
        return res("out_of_scope")
    if _QUESTION.search(text):  # "Would a heat pump cut my energy use?" → explain, not unclear
        return res("explain")
    return _llm_route(message, text, focus, has_scenario, llm, deadline, settings)


def _override_cue(text: str) -> bool:
    return bool(re.search(r"\b(?:gas|electricity|rated|rating|epc|budget)\b", text))


def _memory_question(text: str) -> bool:
    """Statements phrased with a question mark are still memory ('we already have solar, right?')."""
    return bool(re.search(r"\b(?:we|i)\s+already\s+(?:installed|have|had|got)\b", text))


_ROUTER_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string", "enum": list(INTENTS)}},
    "required": ["intent"],
}


def _llm_route(
    message: str,
    text: str,
    focus: list[str],
    has_scenario: bool,
    llm: LLMClient | None,
    deadline: Deadline | None,
    settings: LLMSettings | None,
) -> RouteResult:
    s = settings or get_llm_settings()
    base = RouteResult("unclear", "default", _section(text, focus), focus)
    if llm is None or deadline is None or not deadline.can_call(s.min_call_s):
        return base
    from greenhome.llm.explainer import render  # local import: explainer imports facts/checker

    try:
        raw = llm.generate(
            render("router.j2"),
            [{"role": "user", "content": message}],
            _ROUTER_SCHEMA,
            s.tokens("router", 16),
            timeout_s=deadline.call_timeout(s.cap("router")),
        )
        intent = json.loads(raw).get("intent")
    except (LLMError, ValueError, AttributeError) as e:
        log.info("router LLM fallback failed (%s)", e)
        return base
    if intent not in INTENTS:
        return base
    return RouteResult(intent, "llm", base.section, focus, has_scenario and bool(_CHANGE.search(text)))
