"""跟单业务相关 DTO / 数据类。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


# ── 喊单端委托 DTO（与 signal_server 接口对齐）────────────────


class SignalEntrustDTO(BaseModel):
    stock_code: str
    stock_name: str
    direction: Literal["买入", "卖出"]
    original_price: float
    limit_price: Optional[float]
    has_limit_price: bool
    entrust_qty: int
    filled_qty: int
    canceled_qty: int
    status: str
    entrust_no: str
    entrust_time: str
    entrust_date: str = ""
    entrust_attr: str = "买卖"
    cash_ratio: Optional[float]
    position_ratio: Optional[float]


# ── 跟单引擎内部指令 ─────────────────────────────────────────


@dataclass
class FollowAction:
    action: Literal["buy", "sell", "cancel"]
    stock_code: str
    stock_name: str
    signal_entrust_no: str
    signal_entrust_time: str
    signal_original_price: float
    signal_entrust_qty: int
    limit_price: Optional[float] = None
    signal_cash_ratio: Optional[float] = None
    signal_position_ratio: Optional[float] = None
    follow_mode: Literal["ratio", "multiplier"] = "ratio"
    follow_multiplier: float = 1.0
    local_entrust_no: Optional[str] = None


# ── 跟单状态 Response ────────────────────────────────────────


class FollowStatusResponse(BaseModel):
    running: bool
    cold_start_align_existing: Optional[bool] = None
    start_time: Optional[datetime] = None
    follow_mode: Literal["ratio", "multiplier"] = "ratio"
    follow_multiplier: float = 1.0


# ── 跟单记录 Response ────────────────────────────────────────


class FollowRecordItem(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    action: str
    signal_entrust_no: str
    signal_entrust_time: str
    signal_original_price: float
    signal_entrust_qty: int
    limit_price: Optional[float]
    quantity: Optional[int]
    signal_ratio: Optional[float]
    follow_mode: Optional[str] = None
    follow_multiplier: Optional[float] = None
    status: str
    entrust_no: Optional[str]
    error_code: Optional[str]
    detail: Optional[str]
    created_at: str


class FollowRecordsResponse(BaseModel):
    items: list[FollowRecordItem]
    total: int
    page: int
    size: int
