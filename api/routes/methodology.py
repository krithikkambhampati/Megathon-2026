import json

from fastapi import APIRouter, Request

from api.deps import engine_info
from api.schemas import MethodologyResponse
from greenhome.config import REPO_ROOT, get_config
from greenhome.contracts import CONTRACT_VERSION

router = APIRouter()


@router.get("/methodology", response_model=MethodologyResponse)
def methodology(request: Request) -> MethodologyResponse:
    """Powers "How is this computed?". Everything is read from config, never re-typed."""
    cfg = get_config()
    score = cfg.score
    return MethodologyResponse(
        contract_version=CONTRACT_VERSION,
        score_method_version=score.method_version,
        weights=score.weights,
        classes=[{"class": c.class_, "min": c.min} for c in score.classes],
        sub_score_tables={
            "energy_efficiency": score.energy_efficiency,
            "insulation": score.insulation.model_dump(mode="json"),
            "heating": score.heating,
            "glazing": score.glazing,
            "renewables": score.renewables,
            "smart_controls": score.smart_controls,
        },
        intensity_bounds=cfg.intensity_bounds.model_dump(mode="json"),
        retrofit_catalogue=[spec.model_dump(mode="json") for spec in cfg.catalogue.values()],
        emission_factors=[ef.model_dump(mode="json") for ef in cfg.emission_factors.values()],
        model_versions=engine_info(getattr(request.app.state, "engine", None))[1],
        results=_results(),
    )


def _results() -> dict | None:
    """Headline evaluation results, copied from the reports into reports/results_summary.json."""
    path = REPO_ROOT / "reports" / "results_summary.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else None
