"""Pydantic DTO：stock_limit_prices 表的读写模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StockPriceDTO(BaseModel):
    """单条股票涨跌停价记录。"""

    stock_code: str
    stock_name: str
    close_price: float
    limitup_price: float
    limitdown_price: float
    trade_date: str
    updated_at: datetime


class StockPriceListResponse(BaseModel):
    """分页查询响应。"""

    items: list[StockPriceDTO]
    total: int
    trade_date: Optional[str] = None
    page: int
    size: int


class StockFetchResponse(BaseModel):
    """手动/定时采集结果。"""

    success: bool
    count: int = 0
    trade_date: Optional[str] = None
    message: str = ""


class StockStatusResponse(BaseModel):
    """采集状态概览。"""

    latest_trade_date: Optional[str] = None
    stock_count: int = 0
    scheduler_running: bool = False
