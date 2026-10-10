from fastapi import APIRouter

from greenhome import labels as L

router = APIRouter()


@router.get("/labels")
def labels() -> dict:
    """Plain-English text for every enum value and code (greenhome/labels.py), so the web app, the dashboard
    and the LLM explanations use the same words."""
    return {
        "enums": L.LABELS,
        "component": L.SCORE_COMPONENT,
        "flag": L.FLAG_TEXT,
        "issue": L.ISSUE_TEXT,
        "reason": L.REASON_TEXT,
        "field": L.FIELD_LABEL,
        "yes_no": L.YES_NO,
        "not_sure": L.NOT_SURE,
    }
