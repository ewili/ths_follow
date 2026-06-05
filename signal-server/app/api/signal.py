"""/api/signal/* 路由：喊单委托/持仓/资金查询（US-003）。

错误码与 HTTP 状态映射由 TraderService.with_lock 在底层统一抛出，
本路由不需要重新封装——FastAPI 异常中间件会把 ThsConnectError 透传。
"""

from __future__ import annotations

import logging
from datetime import datetime
from fastapi import APIRouter

from app.db import stock_repository
from app.models.errors import THS_BUSY, THS_NOT_LOGGED_IN, ThsConnectError
from app.models.signal import (
    SignalBalanceResponse,
    SignalEntrustsResponse,
    SignalPositionsResponse,
)
from app.models.system_status import SignalModeResponse, SignalRuntimeStatus
from app.services.signal_runtime_service import SignalRuntimeService
from app.services.signal_service import (
    SignalService,
    _BAL_KEY_TOTAL_ASSETS,
    _ENT_KEY_STOCK_CODE,
    _assemble_valid_entrust_dtos,
    _POS_KEY_POSITION_QTY,
    _POS_KEY_STOCK_CODE,
    _to_float,
    _to_int,
)
from app.services.trader_service import TraderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/signal", tags=["signal"])


@router.get("/status", response_model=SignalRuntimeStatus)
async def get_signal_status() -> SignalRuntimeStatus:
    """返回喊单运行态。"""
    return SignalRuntimeService.get().get_status()


@router.get("/mode", response_model=SignalModeResponse)
async def get_signal_mode() -> SignalModeResponse:
    """返回当前喊单模式（ratio / multiplier）。"""
    return SignalRuntimeService.get().get_mode()


@router.post("/start", response_model=SignalRuntimeStatus)
async def start_signal() -> SignalRuntimeStatus:
    """启动喊单。要求终端已连接。模式从配置中读取。"""
    if TraderService.get().trader is None:
        raise ThsConnectError(
            status_code=409,
            code=THS_NOT_LOGGED_IN,
            message="终端未连接，不能启动喊单",
        )
    return SignalRuntimeService.get().start()


@router.post("/stop", response_model=SignalRuntimeStatus)
async def stop_signal() -> SignalRuntimeStatus:
    """停止喊单。"""
    return SignalRuntimeService.get().stop()


@router.get("/balance", response_model=SignalBalanceResponse)
async def get_balance() -> SignalBalanceResponse:
    """查询喊单账户资金（含 1s TTL 缓存）。

    当 GUI 调用因窗口焦点/弹窗遮挡等临时性原因失败（409）时，
    降级返回过期缓存数据。
    """
    svc = SignalService.get()
    try:
        balance = await svc.get_balance()
        return SignalBalanceResponse(
            balance=balance,
            fetched_at=svc.fetched_at_of("balance"),
        )
    except ThsConnectError as exc:
        if exc.detail.get("code") in (THS_BUSY, THS_NOT_LOGGED_IN):
            stale = svc.stale_cache_of("balance")
            if stale is not None and stale.value is not None:
                logger.warning(
                    "balance_stale_fallback detail=%s cache_age=%.0fs",
                    exc.detail.get("detail", ""),
                    (datetime.now() - stale.fetched_at).total_seconds(),
                )
                return SignalBalanceResponse(
                    balance=stale.value,
                    fetched_at=stale.fetched_at,
                )
        raise


@router.get("/positions", response_model=SignalPositionsResponse)
async def get_positions() -> SignalPositionsResponse:
    """查询喊单账户持仓（含 1s TTL 缓存）。

    当 GUI 调用因窗口焦点/弹窗遮挡等临时性原因失败（409）时，
    降级返回过期缓存数据，避免跟单端收到 500/409 后持续无法获取持仓。
    """
    svc = SignalService.get()
    try:
        items = await svc.get_positions()
        return SignalPositionsResponse(
            items=items,
            fetched_at=svc.fetched_at_of("position"),
        )
    except ThsConnectError as exc:
        if exc.detail.get("code") in (THS_BUSY, THS_NOT_LOGGED_IN):
            stale = svc.stale_cache_of("position")
            if stale is not None and stale.value is not None:
                logger.warning(
                    "positions_stale_fallback detail=%s cache_age=%.0fs",
                    exc.detail.get("detail", ""),
                    (datetime.now() - stale.fetched_at).total_seconds(),
                )
                return SignalPositionsResponse(
                    items=stale.value,
                    fetched_at=stale.fetched_at,
                )
        raise


@router.get("/entrusts", response_model=SignalEntrustsResponse)
async def get_entrusts() -> SignalEntrustsResponse:
    """查询当日委托（价格按方向替换为涨/跌停价 + cash_ratio / position_ratio）。

    最坏情况首次请求会触发 3 次 GUI 调用（balance / position / entrusts），
    后续 1s 内全部命中缓存。

    当 GUI 调用因窗口焦点等临时性原因失败（409）时，降级返回过期缓存数据，
    避免跟单端收到 500/409 后持续无法获取委托。
    """
    svc = SignalService.get()
    try:
        items, trade_date = await svc.get_entrusts()
        return SignalEntrustsResponse(
            items=items,
            trade_date=trade_date,
            fetched_at=svc.fetched_at_of("entrusts"),
        )
    except ThsConnectError as exc:
        # THS_BUSY(窗口焦点) / THS_NOT_LOGGED_IN(终端断连) → 降级返回过期缓存
        if exc.detail.get("code") in (THS_BUSY, THS_NOT_LOGGED_IN):
            stale = svc.stale_cache_of("entrusts")
            if stale is not None and stale.value is not None:
                logger.warning(
                    "entrusts_stale_fallback detail=%s cache_age=%.0fs",
                    exc.detail.get("detail", ""),
                    (datetime.now() - stale.fetched_at).total_seconds(),
                )
                # 用过期缓存重新组装 DTO
                from app.services.signal_runtime_service import SignalRuntimeService
                signal_mode = SignalRuntimeService.get().get_mode().signal_mode
                if signal_mode == "multiplier":
                    # 倍数模式：不需要 balance/position
                    total_assets = 0.0
                    pos_qty_map = {}
                else:
                    stale_balance = svc.stale_cache_of("balance")
                    stale_position = svc.stale_cache_of("position")
                    raw_balance = stale_balance.value if stale_balance else {}
                    raw_positions = stale_position.value if stale_position else []
                    total_assets = _to_float(raw_balance.get(_BAL_KEY_TOTAL_ASSETS), 0.0)
                    pos_qty_map = {str(p.get(_POS_KEY_STOCK_CODE, "")).strip(): _to_int(p.get(_POS_KEY_POSITION_QTY), 0) for p in raw_positions}
                raw_entrusts = stale.value or []
                codes = sorted({str(e.get(_ENT_KEY_STOCK_CODE, "")).strip() for e in raw_entrusts})
                limit_map, trade_date = stock_repository.get_limit_prices_by_codes(codes)
                valid_items = _assemble_valid_entrust_dtos(
                    raw_entrusts, limit_map, total_assets, pos_qty_map, signal_mode=signal_mode
                )
                return SignalEntrustsResponse(
                    items=valid_items,
                    trade_date=trade_date,
                    fetched_at=stale.fetched_at,
                )
        raise


@router.get("/history-entrusts")
async def get_history_entrusts(period: str | None = None) -> list[dict]:
    """查询喊单端历史委托（需已连接）。支持可选周期过滤（当日/近一周/近一月/近三月/近一年）。"""
    from fastapi import HTTPException
    from app.db import repository
    try:
        if not period:
            cfg = repository.load_config()
            period = cfg.history_entrust_period

        allowed_periods = {"当日", "近一周", "近一月", "近三月", "近一年"}
        if period not in allowed_periods:
            raise HTTPException(status_code=400, detail=f"不支持的查询周期: {period}。限 {list(allowed_periods)}")

        return await TraderService.get().get_history_entrusts(period)
    except ThsConnectError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/history-entrusts-dto", response_model=SignalEntrustsResponse)
async def get_history_entrusts_dto(period: str | None = None) -> SignalEntrustsResponse:
    """查询喊单端历史委托并组装为跟单 DTO 格式（含 cash_ratio / limit_price）。

    返回格式与 /api/signal/entrusts 完全一致，供跟单端直接复用现有跟单逻辑。
    """
    from fastapi import HTTPException
    from app.db import repository as sig_repo

    if not period:
        cfg = sig_repo.load_config()
        period = cfg.history_entrust_period

    allowed_periods = {"当日", "近一周", "近一月", "近三月", "近一年"}
    if period not in allowed_periods:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"不支持的查询周期: {period}。限 {list(allowed_periods)}")

    svc = SignalService.get()
    try:
        items, trade_date = await svc.get_history_entrusts_as_dto(period)
        return SignalEntrustsResponse(
            items=items,
            trade_date=trade_date,
            fetched_at=svc.fetched_at_of("entrusts"),
        )
    except ThsConnectError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
