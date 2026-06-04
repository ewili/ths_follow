"""Pydantic DTO：喊单委托/持仓/资金 API 响应模型（US-003）。

字段口径与 docs/easytrader-evaluation.md §3 字段映射表保持一致。
特别注意：

- direction 用 Literal["买入", "卖出"] 精确匹配中文，禁止 startswith / 正则；
- 资金字段仅 5 项（THS 默认配置无"冻结资金"）；
- limit_price / cash_ratio / position_ratio 全部 Optional，缺失语义靠 has_limit_price 与 null 共同表达；
- fetched_at 是缓存写入时刻（非请求处理时刻），用作"快照一致性"指纹。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


# ── 单条 DTO ───────────────────────────────────────────────


class SignalBalanceDTO(BaseModel):
    """喊单账户资金（THS 默认 5 字段）。"""

    cash_balance: float          # 资金余额
    available_cash: float        # 可用金额
    withdrawable_cash: float     # 可取金额
    market_value: float          # 股票市值
    total_assets: float          # 总资产


class SignalPositionDTO(BaseModel):
    """喊单账户单只股票持仓。"""

    stock_code: str
    stock_name: str
    position_qty: int            # 当前持仓（含当日买入）
    available_qty: int           # 股份可用（T+1 可卖股数，跟单端卖出基准）
    cost_price: float            # 参考成本价
    market_price: float          # 参考市价
    market_value: float          # 参考市值
    profit_loss: float           # 参考盈亏
    today_buy_qty: int           # 当日买入股数
    today_sell_qty: int          # 当日卖出股数


class SignalEntrustDTO(BaseModel):
    """喊单账户单笔当日委托。"""

    stock_code: str
    stock_name: str
    direction: Literal["买入", "卖出"]
    original_price: float                 # easytrader 返回的原始委托价
    limit_price: Optional[float]          # 买入→涨停；卖出→跌停；缺失→null
    has_limit_price: bool                 # 是否成功匹配到涨/跌停价
    entrust_qty: int
    filled_qty: int
    canceled_qty: int
    status: str                           # "已成"/"已撤"/"已报"/"部成"/"部撤"
    entrust_no: str
    entrust_time: str                     # easytrader 原文 "HH:MM:SS"
    entrust_date: str = ""               # 历史委托"委托日期"列；当日委托无此列时为空
    entrust_attr: str = "买卖"            # "委托属性"列；当日委托无此列时默认"买卖"
    cash_ratio: Optional[float]           # 买入/卖出均计算；委托价×委托量/资金余额；除零→null
    position_ratio: Optional[float]       # 仅 direction="卖出"；委托量/股票余额；参考字段


# ── Response 包装类 ─────────────────────────────────────────


class SignalBalanceResponse(BaseModel):
    balance: SignalBalanceDTO
    fetched_at: datetime


class SignalPositionsResponse(BaseModel):
    items: list[SignalPositionDTO]
    fetched_at: datetime


class SignalEntrustsResponse(BaseModel):
    items: list[SignalEntrustDTO]
    trade_date: Optional[str] = None      # 涨跌停价对应的交易日（无数据时 null）
    fetched_at: datetime
