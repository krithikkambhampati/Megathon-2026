import json
from typing import Literal

from fastapi import APIRouter, Query, Request, Response

from api.build_portfolio import out_path
from api.errors import APIError
from greenhome.contracts import PortfolioResponse

router = APIRouter()


def _load(request: Request, split: str) -> tuple[PortfolioResponse, str]:
    """Read the precomputed file, re-reading only when it changes (cached on app.state by mtime)."""
    path = out_path(split)
    if not path.exists():
        raise APIError(
            503,
            "portfolio_not_built",
            f"The {split} portfolio hasn't been built yet. Run `make portfolio` "
            "(needs P1's data) or `uv run python -m api.build_portfolio --source examples`.",
        )
    cache = request.app.state.__dict__.setdefault("portfolio_cache", {})
    mtime = path.stat().st_mtime
    if split not in cache or cache[split][0] != mtime:
        raw = json.loads(path.read_text("utf-8"))
        source = raw.pop("source", "data")
        cache[split] = (mtime, PortfolioResponse.model_validate(raw), source)
    return cache[split][1], cache[split][2]


@router.get("/portfolio", response_model=PortfolioResponse)
def portfolio(
    request: Request,
    response: Response,
    split: Literal["train", "val", "test"] = "test",
    limit: int = Query(50, ge=1, le=500),
    poor_only: bool = False,
) -> PortfolioResponse:
    """Homes ranked by improvement potential. `total` counts rows after the poor_only filter, before limit."""
    full, source = _load(request, split)
    rows = [r for r in full.rows if r.is_poor] if poor_only else list(full.rows)
    response.headers["X-Portfolio-Source"] = source  # "data" (P1's split) or "examples" (demo homes)
    return full.model_copy(update={"rows": rows[:limit], "total": len(rows)})
