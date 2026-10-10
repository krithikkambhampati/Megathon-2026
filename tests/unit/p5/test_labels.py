"""ui/labels.py: re-exports the shared text unchanged and adds the UI-only tables.
The text itself is tested in test_core_labels.py."""

import sys
from pathlib import Path

import greenhome.contracts as contracts
import greenhome.labels as core

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ui"))

import labels  # noqa: E402


def test_text_is_the_shared_copy():
    for name in ["LABELS", "FLAG_TEXT", "ISSUE_TEXT", "REASON_TEXT", "SCORE_COMPONENT", "YES_NO", "NOT_SURE"]:
        assert getattr(labels, name) is getattr(core, name), name
    assert labels.label is core.label


def test_class_colours_cover_all_classes():
    assert set(labels.CLASS_COLOUR) == {c.value for c in contracts.ScoreClass}


def test_severity_order_covers_issue_and_flag_severities():
    assert {"high", "medium", "low"} | {s.value for s in contracts.FlagSeverity} <= set(labels.SEVERITY_ORDER)
