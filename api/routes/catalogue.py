from typing import Any

from fastapi import APIRouter, Depends, Request

from api.deps import get_engine
from api.schemas import CatalogueItem

router = APIRouter()


@router.get("/catalogue", response_model=list[CatalogueItem])
def catalogue(request: Request, engine: Any = Depends(get_engine)) -> list[dict]:
    """The demo homes as listing cards (name, key facts, score). Analysed once, then served from memory."""
    return request.app.state.catalogue.cards(engine)
