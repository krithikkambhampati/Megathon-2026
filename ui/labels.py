"""UI display helpers. The text lives in greenhome/labels.py (shared with P4's explanations); this module
re-exports it and adds what only the screens need: colours and sort orders."""

from greenhome.labels import (  # noqa: F401  (re-exported for the pages)
    FLAG_TEXT,
    ISSUE_TEXT,
    LABELS,
    NOT_SURE,
    REASON_TEXT,
    SCORE_COMPONENT,
    YES_NO,
    code_text,
    label,
)

# ScoreClass → colour (green → red, README P5.3)
CLASS_COLOUR: dict[str, str] = {
    "highly_efficient": "#1a9850",
    "good": "#91cf60",
    "moderate": "#fee08b",
    "poor": "#fc8d59",
    "very_poor": "#d73027",
}

FUEL_COLOUR: dict[str, str] = {"electricity": "#1f77b4", "gas": "#ff7f0e", "increase": "#d62728"}

SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2, "error": 0, "warning": 1, "info": 2}
