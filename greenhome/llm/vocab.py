"""Shared words for the rules-first router and parsers (BUILD_GUIDE P4.5): retrofit synonyms and operators.

Every pattern has word boundaries, so "install" never reads as "all" and "address" never reads as "add".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Retrofit synonyms, most specific first. "wall_any" = "wall insulation" without a wall type: the parser
# resolves it from the home's wall type (or asks).
_RETROFIT_PATTERNS: list[tuple[str, str]] = [
    (
        "solid_wall_insulation",
        r"\b(?:solid|external|internal)[\s-]walls?(?:\s+insulation)?\b|\bewi\b|\biwi\b",
    ),
    ("cavity_wall_insulation", r"\bcavity(?:[\s-]walls?)?(?:\s+insulation|\s+fill)?\b"),
    ("wall_any", r"\bwall\s+insulation\b|\binsulat\w*\s+(?:the\s+|my\s+|our\s+)?walls\b"),
    (
        "loft_insulation",
        r"\b(?:loft|attic)(?:\s+insulation)?\b|\broof\s+insulation\b|"
        r"\binsulat\w*\s+(?:the\s+|my\s+|our\s+)?(?:loft|attic|roof)\b",
    ),
    ("air_source_heat_pump", r"\b(?:air[\s-]source\s+)?heat[\s-]?pumps?\b|\bashp\b"),
    ("solar_pv", r"\bsolar(?:\s+(?:panels?|pv|power))?\b|\bpv\b|\bphotovoltaics?\b|\bpanels\b"),
    ("double_glazing", r"\b(?:double|triple|secondary)[\s-]glaz\w*\b|\bglazing\b|\b(?:new\s+)?windows\b"),
    (
        "smart_thermostat",
        r"\b(?:smart\s+)?thermostats?\b|\bsmart\s+(?:heating\s+)?controls?\b|"
        r"\bheating\s+controls?\b|\bsmart\s+heating\b",
    ),
]
RETROFIT_RES = [(r, re.compile(p, re.IGNORECASE)) for r, p in _RETROFIT_PATTERNS]

EVERYTHING = re.compile(
    r"\b(?:everything|all\s+of\s+(?:them|it)|the\s+full\s+package|full\s+package|"
    r"all\s+(?:the\s+)?recommended(?:\s+\w+)?|whole\s+package|the\s+lot)\b",
    re.IGNORECASE,
)
NOTHING = re.compile(
    r"\b(?:nothing|no\s+changes|none\s+of\s+(?:them|it)|do\s+nothing|no\s+retrofits)\b", re.IGNORECASE
)

OP_ONLY = re.compile(r"\b(?:only|just|solely)\b", re.IGNORECASE)
OP_REMOVE = re.compile(
    r"\b(?:without|except|skip(?:ping|ped)?|exclud\w*|drop(?:ping|ped)?|minus|leave\s+out|"
    r"leaving\s+out|no|not|remove|removing|but\s+not|apart\s+from|other\s+than|aside\s+from|"
    r"(?:everything|all|the\s+lot|the\s+full\s+package)\s+but)\b",
    re.IGNORECASE,
)
OP_ADD = re.compile(
    r"\b(?:add(?:ed|ing)?|also|plus|with|install(?:ed|ing)?|get(?:ting)?|fit(?:ted|ting)?|"
    r"put\s+in|include|including|as\s+well|too)\b",
    re.IGNORECASE,
)
# Between two retrofit mentions, only a connective → the second inherits the first's operator
# ("without loft or cavity"). At the start of a message, "and X" means add X ("and a heat pump").
CONNECTIVE = re.compile(r"^[\s,]*(?:(?:and|or|nor|&|plus)\b)?[\s,]*(?:an?|the|some)?\s*$", re.IGNORECASE)
LEADING_AND = re.compile(r"^\s*(?:and|plus|also)\b", re.IGNORECASE)
INSTEAD_OF = re.compile(r"\binstead\s+of\b|\brather\s+than\b|\bin\s+place\s+of\b", re.IGNORECASE)

HYPOTHETICAL = re.compile(
    r"\b(?:what\s+if|suppose|supposing|imagine|if\s+(?:i|we)|what\s+would\s+happen|"
    r"what\s+about|how\s+about)\b",
    re.IGNORECASE,
)

DOMAIN = re.compile(
    r"\b(?:home|house|flat|property|energy|electric\w*|gas|heat\w*|insulat\w*|glaz\w*|windows?|solar|score|"
    r"rating|epc|sap|value|price|worth|bills?|carbon|co2|emissions?|sav(?:e|es|ing|ings)|recommend\w*|"
    r"retrofits?|loft|walls?|boiler|thermostat|kwh|budget|grants?|costs?|cheap\w*|efficien\w*|green|"
    r"panels|pump|upgrades?|improve\w*|survey|install\w*|class|poor|draught\w*)\b",
    re.IGNORECASE,
)


@dataclass
class RetrofitMention:
    retrofit: str  # a Retrofit value, or "wall_any"
    start: int
    end: int


def normalise(text: str) -> str:
    """Lower case, curly quotes → straight, collapse spaces."""
    t = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", t).strip().lower()


def find_retrofits(text: str) -> list[RetrofitMention]:
    """Retrofit mentions in text order; overlapping matches keep the earliest pattern (most specific)."""
    found: list[RetrofitMention] = []
    for r, rx in RETROFIT_RES:
        for m in rx.finditer(text):
            if not any(m.start() < f.end and f.start < m.end() for f in found):
                found.append(RetrofitMention(r, m.start(), m.end()))
    return sorted(found, key=lambda f: f.start)
