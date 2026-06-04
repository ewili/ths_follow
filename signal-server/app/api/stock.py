"""/api/stock/* 路由：股票列表与涨跌停价采集（US-002）。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from app.db import stock_repository
from app.models.stock import (
    StockFetchResponse,
    StockPriceDTO,
    StockPriceListResponse,
    StockStatusResponse,
)
from app.services.stock_data_service import fetch_and_save
from app.tasks.scheduler import is_scheduler_running

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/prices", response_model=StockPriceListResponse)
async def get_stock_prices(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=500),
    keyword: Optional[str] = Query(None, max_length=20),
    trade_date: Optional[str] = Query(None),
) -> StockPriceListResponse:
    """查询股票涨跌停价列表（分页 + 搜索）。"""
    records, total = stock_repository.get_latest_stocks(
        trade_date=trade_date,
        page=page,
        size=size,
        keyword=keyword,
    )

    items = [
        StockPriceDTO(
            stock_code=r["stock_code"],
            stock_name=r["stock_name"],
            close_price=r["close_price"],
            limitup_price=r["limitup_price"],
            limitdown_price=r["limitdown_price"],
            trade_date=r["trade_date"],
            updated_at=datetime.fromisoformat(r["updated_at"]),
        )
        for r in records
    ]

    result_trade_date = items[0].trade_date if items else (trade_date or stock_repository.get_latest_trade_date())

    return StockPriceListResponse(
        items=items,
        total=total,
        trade_date=result_trade_date,
        page=page,
        size=size,
    )


def _check_fetch_allowed() -> str | None:
    """检查当前是否允许采集，返回拒绝原因；None 表示允许。"""
    now = datetime.now()
    weekday = now.weekday()  # 0=周一 … 6=周日
    # 工作日 15:00 前拒绝（盘中实时价不准确），周末和收盘后放行
    if weekday < 5:
        hour_min = now.hour * 100 + now.minute
        if hour_min < 1500:
            return "当前尚未收盘（15:00 前），使用盘中实时价计算涨跌停价可能不准确"
    return None


@router.post("/fetch", response_model=StockFetchResponse)
async def trigger_fetch() -> StockFetchResponse:
    """手动触发采集（仅允许交易日收盘后）。"""
    reason = _check_fetch_allowed()
    if reason:
        logger.warning("event=manual_fetch_rejected reason=%s", reason)
        return StockFetchResponse(
            success=False, count=0, trade_date=None,
            message=reason,
        )
    logger.info("event=manual_fetch_trigger 手动触发股票采集")
    result = await asyncio.to_thread(fetch_and_save)
    return StockFetchResponse(**result)


@router.get("/status", response_model=StockStatusResponse)
async def get_fetch_status() -> StockStatusResponse:
    """返回采集状态概览。"""
    latest_date = stock_repository.get_latest_trade_date()
    count = stock_repository.get_stock_count(latest_date) if latest_date else 0
    return StockStatusResponse(
        latest_trade_date=latest_date,
        stock_count=count,
        scheduler_running=is_scheduler_running(),
    )
