from fastapi import APIRouter, Depends

from api.cache import ResultCache
from api.deps import cached_result, get_cache
from api.schemas import DiffRequest
from greenhome.contracts import ResultDiff
from greenhome.core.diff import diff_results

router = APIRouter()


@router.post("/diff", response_model=ResultDiff)
def diff(body: DiffRequest, cache: ResultCache = Depends(get_cache)) -> ResultDiff:
    """Both results must have been computed by this process (/v1/analyse or /v1/scenario)."""
    base = cached_result(cache, body.base_analysis_id)
    new = cached_result(cache, body.new_analysis_id)
    return diff_results(base, new)
