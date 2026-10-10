"""In-process LRU of analysis_id → AnalysisResult (roadmap §5.5).

Single uvicorn worker; not shared, not on disk.

Explain and diff look results up here by id, so they only work for results this process computed.
"""

from collections import OrderedDict
from threading import Lock

from greenhome.contracts import AnalysisResult


class ResultCache:
    def __init__(self, maxsize: int = 512) -> None:
        self.maxsize = maxsize
        self._items: OrderedDict[str, AnalysisResult] = OrderedDict()
        self._lock = Lock()  # sync routes run in FastAPI's threadpool

    def put(self, result: AnalysisResult) -> None:
        with self._lock:
            self._items[result.analysis_id] = result
            self._items.move_to_end(result.analysis_id)
            while len(self._items) > self.maxsize:
                self._items.popitem(last=False)

    def get(self, analysis_id: str) -> AnalysisResult | None:
        with self._lock:
            result = self._items.get(analysis_id)
            if result is not None:
                self._items.move_to_end(analysis_id)
            return result

    def __len__(self) -> int:
        return len(self._items)
