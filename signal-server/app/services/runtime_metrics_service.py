"""运行态诊断指标采集。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Deque, Optional

from app.models.system_status import DiagnosticSnapshot


@dataclass
class GuiCallRecord:
    operation: str
    gui_elapsed_ms: float
    lock_wait_ms: float


class RuntimeMetricsService:
    """进程内轻量指标收集器。"""

    _instance: Optional["RuntimeMetricsService"] = None

    def __init__(self) -> None:
        self._gui_calls: Deque[GuiCallRecord] = deque(maxlen=50)
        self._cache_hits = 0
        self._cache_misses = 0
        self._captcha_count = 0
        self._dialog_count = 0

    @classmethod
    def get(cls) -> "RuntimeMetricsService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def record_gui_call(
        self,
        operation: str,
        gui_elapsed_ms: float,
        lock_wait_ms: float,
    ) -> None:
        self._gui_calls.append(
            GuiCallRecord(
                operation=operation,
                gui_elapsed_ms=gui_elapsed_ms,
                lock_wait_ms=lock_wait_ms,
            )
        )

    def record_cache_hit(self, key: str) -> None:
        self._cache_hits += 1

    def record_cache_miss(self, key: str) -> None:
        self._cache_misses += 1

    def record_captcha(self) -> None:
        self._captcha_count += 1

    def record_dialog(self) -> None:
        self._dialog_count += 1

    def snapshot(self) -> DiagnosticSnapshot:
        gui_latencies = sorted(item.gui_elapsed_ms for item in self._gui_calls)
        lock_waits = [item.lock_wait_ms for item in self._gui_calls]
        total_cache = self._cache_hits + self._cache_misses
        recent_calls = [
            {
                "operation": item.operation,
                "gui_elapsed_ms": round(item.gui_elapsed_ms, 1),
                "lock_wait_ms": round(item.lock_wait_ms, 1),
            }
            for item in reversed(self._gui_calls)
        ]
        return DiagnosticSnapshot(
            gui_latency_p50_ms=round(_percentile(gui_latencies, 50), 1),
            gui_latency_p95_ms=round(_percentile(gui_latencies, 95), 1),
            cache_hit_rate=round(
                (self._cache_hits / total_cache) if total_cache else 0.0,
                3,
            ),
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
            captcha_count=self._captcha_count,
            dialog_count=self._dialog_count,
            avg_lock_wait_ms=round(
                (sum(lock_waits) / len(lock_waits)) if lock_waits else 0.0,
                1,
            ),
            recent_gui_calls=recent_calls,
        )


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    if p <= 50:
        return float(median(values))
    index = int(round((len(values) - 1) * (p / 100)))
    return float(values[index])
