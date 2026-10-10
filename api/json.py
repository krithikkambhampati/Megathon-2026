"""JSON response that never emits NaN or Infinity (README §7.8: converted to null)."""

import json
import math
from typing import Any

from fastapi.responses import JSONResponse


def nan_to_none(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: nan_to_none(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [nan_to_none(v) for v in obj]
    return obj


class NaNSafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(
            nan_to_none(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
