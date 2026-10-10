"""Demo homes: P1's data/examples/ (index.json + <id>.json).

Falls back to P2's fixture homes until P1 ships.
"""

import json
import re
from pathlib import Path

from fastapi import APIRouter

from api.deps import FIXTURES_DIR
from api.errors import APIError
from api.schemas import ExampleIndexItem
from greenhome.config import get_config
from greenhome.contracts import HomeInput

router = APIRouter()

_ID = re.compile(r"^P\d{5,}$")
_FIXTURE_TEXT = {
    "P10001": ("PS example home", "Rating E semi, single glazing, unfilled cavity (score 36, Poor)"),
    "P90002": ("Flat with unknown answers", "Several 'not sure' answers, so the score comes with a range"),
    "P90003": ("Almost no information", "Too little data: the app says 'insufficient' instead of guessing"),
    "P90004": ("Missing winter months", "Gaps in monthly readings, annualised with seasonal shares"),
    "P90005": ("Off-gas home", "Oil or LPG heating: scored, but savings are out of scope"),
}


def _examples_dir() -> Path:
    return get_config().examples_dir


@router.get("/examples", response_model=list[ExampleIndexItem])
def list_examples() -> list[ExampleIndexItem]:
    index = _examples_dir() / "index.json"
    if index.exists():
        return [ExampleIndexItem.model_validate(x) for x in json.loads(index.read_text("utf-8"))]
    items = []
    for path in sorted(FIXTURES_DIR.glob("home_input_*.json")):
        pid = path.stem.removeprefix("home_input_")
        title, why = _FIXTURE_TEXT.get(pid, (f"Test home {pid}", "P2 test fixture"))
        why = f"{why} [test fixture]"
        items.append(ExampleIndexItem(property_id=pid, title=title, why_interesting=why))
    return items


@router.get("/examples/{property_id}", response_model=HomeInput)
def get_example(property_id: str) -> HomeInput:
    if _ID.match(property_id):  # also stops path traversal
        p1_file = _examples_dir() / f"{property_id}.json"
        fixture_file = FIXTURES_DIR / f"home_input_{property_id}.json"
        for path in (p1_file, fixture_file):
            if path.exists():
                return HomeInput.model_validate_json(path.read_text("utf-8"))
    raise APIError(404, "example_not_found", f"No example home {property_id!r}")
