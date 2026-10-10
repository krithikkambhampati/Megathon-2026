"""Code → plain-English text for the LLM layer, from `greenhome.labels` (P5), so chat and screens say the
same thing. Small helpers on top; no wording lives here.
"""

from __future__ import annotations

from greenhome.labels import FLAG_TEXT, ISSUE_TEXT, LABELS, NOT_SURE, REASON_TEXT, SCORE_COMPONENT, label

__all__ = [
    "FLAG_TEXT",
    "ISSUE_TEXT",
    "LABELS",
    "NOT_SURE",
    "REASON_TEXT",
    "SCORE_COMPONENT",
    "label",
    "flag_text",
    "issue_text",
    "reason_text",
]


def reason_text(code: str) -> str:
    return REASON_TEXT.get(code, code)


def flag_text(code: str) -> str:
    return FLAG_TEXT.get(code, code)


def issue_text(code: str) -> str:
    return ISSUE_TEXT.get(code, code)
