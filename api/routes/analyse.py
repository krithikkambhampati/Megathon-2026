from typing import Any

from fastapi import APIRouter, Depends

from api.cache import ResultCache
from api.deps import get_cache, get_engine
from api.schemas import AnalyseRequest, ScenarioRequest
from greenhome.contracts import AnalysisResult

router = APIRouter()


@router.post("/analyse", response_model=AnalysisResult)
def analyse(
    body: AnalyseRequest, engine: Any = Depends(get_engine), cache: ResultCache = Depends(get_cache)
) -> AnalysisResult:
    ctx = None  # TODO(P5-23): CustomerContext from memory when body.customer_id is set
    result = engine.analyse(body.home, ctx)
    cache.put(result)
    return result


@router.post("/scenario", response_model=AnalysisResult)
def scenario(
    body: ScenarioRequest, engine: Any = Depends(get_engine), cache: ResultCache = Depends(get_cache)
) -> AnalysisResult:
    ctx = None  # TODO(P5-23): as above
    result = engine.run_scenario(body.home, body.scenario, ctx)
    cache.put(result)
    return result
