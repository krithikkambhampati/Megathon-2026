import inspect
import json
import re
from pathlib import Path

import pytest

import greenhome.contracts as contracts
from greenhome import labels

ROOT = Path(__file__).resolve().parents[3]

ENUMS = [
    obj
    for _, obj in inspect.getmembers(contracts, inspect.isclass)
    if issubclass(obj, contracts._E) and obj is not contracts._E
]


@pytest.mark.parametrize("enum", ENUMS, ids=lambda e: e.__name__)
def test_every_enum_member_has_a_label(enum):
    assert enum.__name__ in labels.LABELS, f"add LABELS[{enum.__name__!r}]"
    assert set(labels.LABELS[enum.__name__]) == {m.value for m in enum}


def test_every_score_component_has_a_label():
    keys = set(contracts.ScoreComponent.model_fields["key"].annotation.__args__)
    assert set(labels.SCORE_COMPONENT) == keys


def _codes_in_fixtures() -> tuple[set[str], set[str], set[str]]:
    flags, issues, reasons = set(), set(), set()
    for path in (ROOT / "tests" / "fixtures").glob("analysis_result_*.json"):
        r = json.loads(path.read_text())
        flags |= {f["code"] for f in r["flags"]} | {f["code"] for f in r["home"]["flags"]}
        issues |= {i["code"] for i in r["issues"]}
        reasons |= {c for rec in r["recommendations"] for c in rec["reasons"]}
        reasons |= {x["reason"] for x in r["rejected"]}
    return flags, issues, reasons


def test_fixture_codes_have_text():
    flags, issues, reasons = _codes_in_fixtures()
    assert flags <= set(labels.FLAG_TEXT), flags - set(labels.FLAG_TEXT)
    assert issues <= set(labels.ISSUE_TEXT), issues - set(labels.ISSUE_TEXT)
    assert reasons <= set(labels.REASON_TEXT), reasons - set(labels.REASON_TEXT)


def test_flag_codes_used_by_engine_have_text():
    # P2 emits flags via _flag("CODE", ...) / DataFlag(code="CODE", ...)
    src = "\n".join(p.read_text() for p in (ROOT / "greenhome").rglob("*.py") if p.name != "labels.py")
    used = set(re.findall(r'(?:_flag\(\s*|code=)"([A-Z][A-Z_]+)"', src))
    assert used, "found no flag codes: has the engine changed how it emits flags?"
    missing = used - set(labels.FLAG_TEXT) - set(labels.ISSUE_TEXT)
    assert not missing, f"add FLAG_TEXT for {sorted(missing)}"


def test_label_helpers():
    assert labels.label("Glazing", None) == labels.NOT_SURE
    assert labels.label("Glazing", "single") == "Single glazing"
    assert labels.label("Glazing", "brand_new_value") == "brand_new_value"
    assert labels.code_text(labels.REASON_TEXT, "NEW_CODE") == "NEW_CODE"
