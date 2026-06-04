"""跟单引擎启停 + 记录查询 API。"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.db import repository
from app.models.follow import FollowRecordItem, FollowRecordsResponse, FollowStatusResponse
from app.services.follow_engine import FollowEngine
from app.services.local_trader_service import LocalTraderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/follow", tags=["follow"])


@router.post("/start", response_model=FollowStatusResponse)
async def start_follow(
    cold_start_align_existing: bool = Query(False),
) -> FollowStatusResponse:
    """启动跟单引擎。运行中再次调用幂等（不重启）。

    启动时会校验喊单端模式与本地 follow_mode 是否一致。
    """
    if not LocalTraderService.get().is_connected:
        raise HTTPException(status_code=400, detail="请先连接本地同花顺终端")
    try:
        return await FollowEngine.get().start(
            cold_start_align_existing=cold_start_align_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stop", response_model=FollowStatusResponse)
async def stop_follow() -> FollowStatusResponse:
    """停止跟单引擎。"""
    return await FollowEngine.get().stop()


@router.get("/status", response_model=FollowStatusResponse)
async def get_follow_status() -> FollowStatusResponse:
    """查询跟单引擎当前状态（不触发 GUI）。"""
    return FollowEngine.get().get_status()


@router.get("/records", response_model=FollowRecordsResponse)
async def get_follow_records(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    stock_code: Optional[str] = Query(None),
) -> FollowRecordsResponse:
    """分页查询跟单操作日志。"""
    items_raw, total = repository.get_records_page(page=page, size=size, stock_code=stock_code)
    items = [FollowRecordItem(**r) for r in items_raw]
    return FollowRecordsResponse(items=items, total=total, page=page, size=size)
