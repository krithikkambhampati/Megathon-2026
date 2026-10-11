"""Regenerate `analysis_result_<id>.json` from every `home_input_<id>.json` using the STUB models.

P4 and P5 build against these files (BUILD_GUIDE P2.1, D2). Run after any contract or engine change:
    .venv/bin/python tests/fixtures/generate.py
`tests/integration/test_engine.py::test_fixtures_are_current` fails when they are stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent
sys.path.insert(0, str(FIXTURES.parents[1]))

from greenhome.contracts import AnalysisResult, HomeInput  # noqa: E402
from greenhome.core.orchestrator import Engine  # noqa: E402
from greenhome.ml.stubs import load_stub_models  # noqa: E402


def home_inputs() -> dict[str, HomeInput]:
    """{id: HomeInput} for every fixture input, sorted by id."""
    return {
        p.stem.removeprefix("home_input_"): HomeInput.model_validate_json(p.read_text())
        for p in sorted(FIXTURES.glob("home_input_*.json"))
    }


def render(result: AnalysisResult) -> str:
    return json.dumps(result.model_dump(mode="json"), indent=2, allow_nan=False) + "\n"


def main() -> None:
    engine = Engine.from_config(models=load_stub_models())
    for key, home in home_inputs().items():
        out = FIXTURES / f"analysis_result_{key}.json"
        out.write_text(render(engine.analyse(home)))
        print(f"wrote {out.relative_to(FIXTURES.parents[1])}")


if __name__ == "__main__":
    main()
