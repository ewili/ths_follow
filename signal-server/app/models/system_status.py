"""Pydantic DTO：US-004 管理台状态、诊断与日志。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.models.config import ConnectionStatus


class SignalRuntimeStatus(BaseModel):
    """喊单运行态（内存态，重启后重置）。"""

    state: Literal["stopped", "running"]
    started_at: Optional[datetime] = None
    last_changed_at: Optional[datetime] = None
    schedule_active: bool = True
    signal_mode: Literal["ratio", "multiplier"] = "ratio"


class SignalModeResponse(BaseModel):
    """喊单模式查询响应。"""

    signal_mode: Literal["ratio", "multiplier"]


class DashboardStatusResponse(BaseModel):
    """首页仪表盘状态。"""

    connection: ConnectionStatus
    signal: SignalRuntimeStatus
    latest_stock_trade_date: Optional[str] = None
    stock_count: int = 0
    balance_fetched_at: Optional[datetime] = None
    position_fetched_at: Optional[datetime] = None
    entrusts_fetched_at: Optional[datetime] = None
    gui_latency_p50_ms: float = 0.0
    gui_latency_p95_ms: float = 0.0


class DiagnosticSnapshot(BaseModel):
    """诊断面板快照。"""

    gui_latency_p50_ms: float = 0.0
    gui_latency_p95_ms: float = 0.0
    cache_hit_rate: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    captcha_count: int = 0
    dialog_count: int = 0
    avg_lock_wait_ms: float = 0.0
    recent_gui_calls: list[dict]


class OperationLogEntry(BaseModel):
    """日志页单行记录。"""

    timestamp: str
    level: str
    logger: str
    message: str


class OperationLogResponse(BaseModel):
    """日志列表响应。"""

    items: list[OperationLogEntry]
    total: int
    page: int
    size: int
