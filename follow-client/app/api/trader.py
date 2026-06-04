"""本地同花顺终端连接管理 API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import repository
from app.services.local_trader_service import LocalTraderService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trader", tags=["trader"])


class TraderStatusResponse(BaseModel):
    state: str
    last_error: str | None
    last_connect_at: str | None


@router.post("/connect", response_model=TraderStatusResponse)
async def connect_trader() -> TraderStatusResponse:
    """使用当前配置中的 local_ths_exe_path 接管已登录的本地同花顺终端。"""
    cfg = repository.load_config()
    if not cfg.local_ths_exe_path:
        raise HTTPException(status_code=400, detail="请先在配置页填写本地同花顺路径")

    try:
        status = await LocalTraderService.get().connect(
            exe_path=cfg.local_ths_exe_path,
            use_type_keys=cfg.use_type_keys,
            grid_strategy=cfg.grid_strategy,
        )
        return TraderStatusResponse(**status)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/disconnect", response_model=TraderStatusResponse)
async def disconnect_trader() -> TraderStatusResponse:
    """断开本地同花顺终端连接（不会退出 THS 进程）。"""
    await LocalTraderService.get().disconnect()
    return TraderStatusResponse(**LocalTraderService.get().get_status())


@router.get("/status", response_model=TraderStatusResponse)
async def get_trader_status() -> TraderStatusResponse:
    """返回本地终端当前连接状态（不触发 GUI）。"""
    return TraderStatusResponse(**LocalTraderService.get().get_status())


@router.post("/health", response_model=TraderStatusResponse)
async def health_probe() -> TraderStatusResponse:
    """主动探测本地终端窗口是否有效（触发一次 GUI 标题检查）。"""
    status = await LocalTraderService.get().health_probe()
    return TraderStatusResponse(**status)


@router.get("/positions")
async def get_positions() -> list[dict]:
    """查询本地持仓（需已连接）。"""
    try:
        return await LocalTraderService.get().get_positions()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/entrusts")
async def get_today_entrusts() -> list[dict]:
    """查询本地当日委托（需已连接）。"""
    try:
        return await LocalTraderService.get().get_today_entrusts()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history-entrusts")
async def get_history_entrusts(period: str | None = None) -> list[dict]:
    """查询本地历史委托（需已连接）。支持可选周期过滤（当日/近一周/近一月/近三月/近一年）。"""
    try:
        if not period:
            cfg = repository.load_config()
            period = cfg.history_entrust_period

        allowed_periods = {"当日", "近一周", "近一月", "近三月", "近一年"}
        if period not in allowed_periods:
            raise HTTPException(status_code=400, detail=f"不支持的查询周期: {period}。限 {list(allowed_periods)}")

        return await LocalTraderService.get().get_history_entrusts(period)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/balance")
async def get_balance() -> dict:
    """查询本地资金余额（需已连接）。"""
    try:
        return await LocalTraderService.get().get_balance()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
