"""/api/system/* 路由：终端配置与连接管理。"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query

from app.db import repository
from app.db import stock_repository
from app.core.settings import LOG_FILE
from app.models.config import (
    SystemConfigResponse,
    SystemConfigUpdate,
)
from app.models.system_status import (
    DashboardStatusResponse,
    OperationLogEntry,
    OperationLogResponse,
)
from app.services.runtime_metrics_service import RuntimeMetricsService
from app.services.signal_runtime_service import SignalRuntimeService
from app.services.signal_service import SignalService
from app.services.trader_service import TraderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/system", tags=["system"])


def _build_response() -> SystemConfigResponse:
    cfg = repository.load_config()
    status = TraderService.get().get_status()
    return SystemConfigResponse(config=cfg, status=status)


@router.get("/config", response_model=SystemConfigResponse)
async def get_config() -> SystemConfigResponse:
    """返回当前配置 + 连接状态（不触碰 GUI）。"""
    return _build_response()


@router.put("/config", response_model=SystemConfigResponse)
async def update_config(data: SystemConfigUpdate) -> SystemConfigResponse:
    """保存配置到 SQLite（不连接终端）。"""
    repository.save_config(data)
    logger.info(
        "event=config_updated path=%s grid_strategy=%s",
        data.ths_exe_path,
        data.grid_strategy,
    )
    # TODO(US-009): operation_log.write(category="config", ...)
    return _build_response()


@router.post("/connect", response_model=SystemConfigResponse)
async def connect_terminal() -> SystemConfigResponse:
    """读取已保存配置并接管同花顺终端。"""
    cfg = repository.load_config()
    if not cfg.ths_exe_path or cfg.ths_exe_path.strip() == "":
        from app.models.errors import ThsConnectError, THS_PATH_INVALID

        raise ThsConnectError(
            status_code=400,
            code=THS_PATH_INVALID,
            message="请先配置 xiadan.exe 路径",
        )

    await TraderService.get().connect(
        exe_path=cfg.ths_exe_path,
        use_type_keys=cfg.use_type_keys,
        grid_strategy=cfg.grid_strategy,
    )
    return _build_response()


@router.post("/disconnect")
async def disconnect_terminal() -> SystemConfigResponse:
    """释放终端引用（不杀客户端进程）。"""
    await TraderService.get().disconnect()
    return _build_response()


@router.get("/health", response_model=SystemConfigResponse)
async def health_check() -> SystemConfigResponse:
    """轻量健康探针（窗口标题校验）。"""
    await TraderService.get().health_probe()
    return _build_response()


@router.get("/status", response_model=DashboardStatusResponse)
async def get_system_status() -> DashboardStatusResponse:
    """首页仪表盘聚合状态。"""
    latest_trade_date = stock_repository.get_latest_trade_date()
    stock_count = (
        stock_repository.get_stock_count(latest_trade_date)
        if latest_trade_date
        else 0
    )
    diagnostics = RuntimeMetricsService.get().snapshot()
    signal_service = SignalService.get()
    trader_service = TraderService.get()
    return DashboardStatusResponse(
        connection=trader_service.get_status(),
        signal=SignalRuntimeService.get().get_status(),
        latest_stock_trade_date=latest_trade_date,
        stock_count=stock_count,
        balance_fetched_at=_safe_fetched_at(signal_service, "balance"),
        position_fetched_at=_safe_fetched_at(signal_service, "position"),
        entrusts_fetched_at=_safe_fetched_at(signal_service, "entrusts"),
        gui_latency_p50_ms=diagnostics.gui_latency_p50_ms,
        gui_latency_p95_ms=diagnostics.gui_latency_p95_ms,
    )


@router.get("/diagnostics")
async def get_diagnostics():
    """诊断面板指标。"""
    return RuntimeMetricsService.get().snapshot()


@router.get("/logs", response_model=OperationLogResponse)
async def get_logs(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    keyword: Optional[str] = Query(None, max_length=100),
) -> OperationLogResponse:
    """分页读取当前日志文件最近记录。"""
    items, total = _read_recent_logs(
        LOG_FILE,
        page=page,
        size=size,
        keyword=keyword,
    )
    return OperationLogResponse(items=items, total=total, page=page, size=size)


def _safe_fetched_at(signal_service: SignalService, key: str):
    entry = signal_service._cache.get(key)  # noqa: SLF001 - 仅用于状态展示
    return entry.fetched_at if entry is not None else None


def _read_recent_logs(
    path: Path,
    page: int,
    size: int,
    keyword: Optional[str] = None,
) -> tuple[list[OperationLogEntry], int]:
    if not path.exists():
        return [], 0

    offset = (page - 1) * size
    window_size = offset + size
    keyword_text = (keyword or "").strip().lower()
    lines: deque[str] = deque(maxlen=window_size)
    total = 0

    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            if keyword_text and keyword_text not in line.lower():
                continue
            total += 1
            lines.append(line)

    result: list[OperationLogEntry] = []
    for line in list(reversed(lines))[offset:offset + size]:
        result.append(_parse_log_line(line))
    return result, total


def _parse_log_line(line: str) -> OperationLogEntry:
    parts = line.split(" ", 4)
    if len(parts) < 5:
        return OperationLogEntry(
            timestamp="",
            level="INFO",
            logger="unknown",
            message=line,
        )
    date_part, time_part, level, logger_part, message = parts
    logger_name = logger_part.strip("[]")
    return OperationLogEntry(
        timestamp=f"{date_part} {time_part}",
        level=level,
        logger=logger_name,
        message=message,
    )
