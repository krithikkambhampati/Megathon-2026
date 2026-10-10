"""Precompute the portfolio ranking (roadmap CR-4). The API only serves the file; it never ranks live.

    uv run python -m api.build_portfolio --split test        # P1's processed data (make data)
    uv run python -m api.build_portfolio --source examples   # the committed demo homes only

Writes outputs/portfolio/portfolio_<split>.json (a PortfolioResponse plus a "source" key). The file is
committed, so the demo works on machines without P1's processed data.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from greenhome.contracts import HomeInput, PortfolioResponse, PortfolioRow

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "outputs" / "portfolio"


def out_path(split: str) -> Path:
    return OUT_DIR / f"portfolio_{split}.json"


def example_rows(engine) -> list[PortfolioRow]:
    """Rank the demo homes (data/examples, else the test fixtures) the way engine.portfolio ranks a split."""
    homes = sorted((REPO / "data" / "examples").glob("P*.json")) or sorted(
        (REPO / "tests" / "fixtures").glob("home_input_*.json")
    )
    results = []
    for path in homes:
        home = HomeInput.model_validate_json(path.read_text("utf-8"))
        results.append((home.property_id or path.stem.removeprefix("home_input_"), engine.analyse(home)))
    results.sort(
        key=lambda x: (
            x[1].savings.improvement_potential_pct is None,
            -(x[1].savings.improvement_potential_pct or 0),
            x[0],
        )
    )
    return [
        PortfolioRow(
            rank=i,
            property_id=pid,
            customer_id=r.home.home.customer_id,
            region=r.home.home.region,
            property_type=r.home.home.property_type,
            score=r.score.score,
            score_class=r.score.score_class,
            is_poor=r.is_poor,
            improvement_potential_pct=r.savings.improvement_potential_pct,
            key_issues=[x.code for x in r.issues[:3]],
            savings_status=r.savings.status,
        )
        for i, (pid, r) in enumerate(results, start=1)
    ]


def build(engine, split: str = "test", source: str = "data") -> PortfolioResponse:
    rows = example_rows(engine) if source == "examples" else engine.portfolio(split=split)
    return PortfolioResponse(
        split=split,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        model_versions=engine.models.versions(),
        total=len(rows),
        rows=rows,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Precompute the portfolio ranking")
    ap.add_argument("--split", default="test", choices=["train", "val", "test"])
    ap.add_argument("--source", default="data", choices=["data", "examples"])
    args = ap.parse_args(argv)
    from greenhome.core.orchestrator import Engine

    engine = Engine.from_config()
    try:
        resp = build(engine, args.split, args.source)
    except FileNotFoundError as err:
        print(f"{err}\nNo processed data here: run `make data`, or use --source examples.", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.loads(resp.model_dump_json())
    payload["source"] = args.source  # for the UI's label; not part of the contract
    path = out_path(args.split)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO)}: {resp.total} homes ({args.source}; models {resp.model_versions})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
