"""下单执行器：股数计算 + easytrader 下单 + 写 follow_records。"""

from __future__ import annotations

import logging
import math


def _floor2(x: float) -> float:
    """向下截断到2位小数。"""
    return math.floor(x * 100) / 100


def _ceil2(x: float) -> float:
    """向上截断到2位小数。"""
    return math.ceil(x * 100) / 100
from typing import Optional

from app.models.follow import FollowAction
from app.services.local_trader_service import LocalTraderService
from app.db import repository

logger = logging.getLogger(__name__)

_MIN_LOT = 100

# THS 当日委托字段名
_KEY_ENTRUST_NO = "合同编号"
_KEY_STOCK_CODE = "证券代码"
_KEY_DIRECTION = "操作"
_KEY_PRICE = "委托价格"
_KEY_QTY = "委托数量"


def _calc_buy_qty_multiplier(
    multiplier: float,
    entrust_qty: int,
) -> int:
    """按倍数计算买入股数，向下取整到100整数倍，不足100股按100股。

    Args:
        multiplier: 跟单倍数
        entrust_qty: 喊单买入股数

    Returns:
        应买入股数（至少100股）
    """
    raw = math.floor(entrust_qty * multiplier / _MIN_LOT) * _MIN_LOT
    return max(_MIN_LOT, raw)


def _calc_sell_qty_multiplier(
    multiplier: float,
    entrust_qty: int,
    available_qty: int,
) -> int:
    """按倍数计算卖出股数，向下取整到100整数倍，不超过可用持仓。

    兜底规则：
    - 计算结果不足100股但有持仓 → 全部卖出
    - 计算结果超过可用持仓 → 全部卖出（不留零股）

    Args:
        multiplier: 跟单倍数
        entrust_qty: 喊单卖出股数
        available_qty: 本地可用持仓

    Returns:
        实际应卖出的股数
    """
    raw = math.floor(entrust_qty * multiplier / _MIN_LOT) * _MIN_LOT
    # 兜底：计算结果不足100股但有持仓 → 全部卖出
    if raw == 0 and available_qty > 0:
        return available_qty
    return min(raw, available_qty)


def _calc_buy_qty_ratio(
    cash_ratio: float,
    total_assets: float,
    limit_price: float,
) -> int:
    """按资金比例计算买入股数，向下取整到100整数倍，不足100股按100股。
    
    Args:
        cash_ratio: 喊单委托占喊单总资产比例
        total_assets: 跟单账户总资产
        limit_price: 涨停价
    
    Returns:
        应买入股数（至少100股）
    """
    amount = total_assets * cash_ratio
    raw = math.floor(amount / limit_price / _MIN_LOT) * _MIN_LOT
    
    if raw < _MIN_LOT:
        required_amount = _MIN_LOT * limit_price
        if amount < required_amount:
            logger.warning(
                "buy_qty_insufficient_cash calculated_amount=%.2f required_for_100=%.2f "
                "forcing_100_shares (will_likely_fail)",
                amount, required_amount
            )
    
    return max(_MIN_LOT, raw)


def _calc_sell_qty_by_position_ratio(
    position_ratio: Optional[float],
    available: int,
) -> int:
    """按持仓比例计算卖出股数，向下取整到100整数倍。
    
    业务决策：卖出模式按对等比例卖出（喊单 position_ratio × 跟单本地股份可用）。
    
    兜底规则（避免零股和丢失跟单动作）：
    - position_ratio 为 None 时全部卖出可用持仓
    - 若计算结果取整后为0，但实际持仓 > 0 → 全部卖出
    - 若计算结果 >= 可用持仓 → 全部卖出（不留零股）
    
    Args:
        position_ratio: 喊单卖出占持仓比例
        available: 跟单本地股份可用
    
    Returns:
        实际应卖出的股数（0 或 [100, available] 区间的100整数倍或 available）
    """
    # position_ratio 为 None 时兜底：全部卖出可用持仓
    if position_ratio is None:
        logger.warning("sell_position_ratio_null fallback_sell_all available=%d", available)
        return available
    
    raw = math.floor(available * position_ratio / _MIN_LOT) * _MIN_LOT
    
    # 兜底：计算结果不足100股但有持仓 → 全部卖出
    if raw == 0 and available > 0:
        return available
    
    # 兜底：计算结果超过可用持仓 → 全部卖出（不留零股）
    return min(raw, available)


async def _recover_entrust_no(stock_code: str, direction: str, price: float, qty: int) -> str:
    """easytrader 下单返回 entrust_no 为空时，从当日委托中恢复合同编号。

    匹配条件：证券代码 + 买卖方向 + 委托价格 + 委托数量 完全一致。
    """
    try:
        trader = LocalTraderService.get()
        entrusts = await trader.get_today_entrusts()
        for e in entrusts:
            code = str(e.get(_KEY_STOCK_CODE, "")).strip()
            raw_dir = str(e.get(_KEY_DIRECTION, ""))
            no = str(e.get(_KEY_ENTRUST_NO, ""))
            e_price = float(e.get(_KEY_PRICE, 0) or 0)
            e_qty = int(float(e.get(_KEY_QTY, 0) or 0))
            is_sell = "卖" in raw_dir
            dir_match = (direction == "买入" and not is_sell) or (direction == "卖出" and is_sell)
            if code == stock_code and dir_match and abs(e_price - price) < 0.001 and e_qty == qty and no:
                return no
    except Exception as exc:
        logger.warning("recover_entrust_no_failed stock=%s detail=%s", stock_code, exc)
    return ""


def _log_entrust_no_result(action_name: str, stock_code: str, price: float, qty: int, entrust_no: str, recovered: bool = False, extra: str = "") -> None:
    """根据 entrust_no 是否为空选择日志级别：空→WARNING（撤单跟随和双重保险将失效），非空→INFO。"""
    if entrust_no:
        suffix = " (recovered)" if recovered else ""
        logger.info("%s_ok stock=%s price=%.4f qty=%d entrust_no=%s%s%s", action_name, stock_code, price, qty, entrust_no, suffix, extra)
    else:
        logger.warning("%s_ok_no_entrust_no stock=%s price=%.4f qty=%d (合同编号获取失败，撤单跟随和双重保险将失效)%s", action_name, stock_code, price, qty, extra)


async def execute_buy(
    action: FollowAction,
    total_assets: float,
) -> None:
    trader = LocalTraderService.get()
    stock_code = action.stock_code

    if action.limit_price is None:
        _write_record(action, "buy",
                      status="warn", error_code="limit_price_null",
                      detail="limit_price=null，涨停价未采集，跳过")
        logger.warning("buy skip limit_price_null stock=%s", stock_code)
        return

    # 根据模式选择计算方式
    if action.follow_mode == "multiplier":
        qty = _calc_buy_qty_multiplier(action.follow_multiplier, action.signal_entrust_qty)
    else:
        qty = _calc_buy_qty_ratio(action.signal_cash_ratio, total_assets, action.limit_price)
    price = _floor2(action.limit_price)

    # 【先写】写入 pending 记录（防止崩溃后重复下单）
    _write_record(
        action, "buy",
        limit_price=price, quantity=qty,
        status="pending",
        signal_ratio=action.signal_cash_ratio,
    )

    try:
        # 【后执行】执行下单
        result = await trader.buy(stock_code, price, qty)
        entrust_no = result.get("entrust_no", "")

        # 合同编号为空时尝试从当日委托恢复
        recovered = False
        if not entrust_no:
            logger.warning("buy_empty_entrust_no stock=%s price=%.4f qty=%d, attempting recovery", stock_code, price, qty)
            entrust_no = await _recover_entrust_no(stock_code, "买入", price, qty)
            if entrust_no:
                recovered = True

        # 【更新】成功后更新为 success
        repository.update_follow_record(
            action.signal_entrust_no, "buy",
            status="success", entrust_no=entrust_no,
        )
        _log_entrust_no_result("buy", stock_code, price, qty, entrust_no, recovered=recovered)
    except Exception as exc:
        error_detail = str(exc)
        error_code = "trade_error"
        
        # 识别常见错误类型
        if "资金不足" in error_detail or "可用资金" in error_detail:
            error_code = "insufficient_cash"
        elif "价格" in error_detail and "小数" in error_detail:
            error_code = "price_precision"
        
        # SetForegroundWindow / SendInput 临时错误：重试一次
        if "setforegroundwindow" in error_detail.lower() or "sendinput" in error_detail.lower():
            logger.info("buy_transient_error stock=%s detail=%s, retrying after foreground", stock_code, exc)
            import asyncio
            await asyncio.sleep(0.3)
            try:
                result = await trader.buy(stock_code, price, qty)
                entrust_no = result.get("entrust_no", "")

                # 合同编号为空时尝试从当日委托恢复
                recovered = False
                if not entrust_no:
                    logger.warning("buy_retry_empty_entrust_no stock=%s, attempting recovery", stock_code)
                    entrust_no = await _recover_entrust_no(stock_code, "买入", price, qty)
                    if entrust_no:
                        recovered = True

                repository.update_follow_record(
                    action.signal_entrust_no, "buy",
                    status="success", entrust_no=entrust_no,
                )
                _log_entrust_no_result("buy_retry", stock_code, price, qty, entrust_no, recovered=recovered)
                return
            except Exception as retry_exc:
                error_detail = str(retry_exc)
                error_code = "trade_error"
                logger.warning("buy_retry_failed stock=%s detail=%s", stock_code, retry_exc)
        
        # 【更新】失败后更新为 failed
        repository.update_follow_record(
            action.signal_entrust_no, "buy",
            status="failed", error_code=error_code, detail=error_detail,
        )
        logger.error("buy_failed stock=%s error_code=%s detail=%s", stock_code, error_code, exc)


async def execute_sell(
    action: FollowAction,
    available_qty: int,
) -> None:
    trader = LocalTraderService.get()
    stock_code = action.stock_code

    if available_qty <= 0:
        logger.debug("sell skip no_position stock=%s", stock_code)
        return

    price = _ceil2(action.limit_price or action.signal_original_price)
    used_fallback_price = action.limit_price is None

    # 根据模式选择计算方式
    if action.follow_mode == "multiplier":
        qty = _calc_sell_qty_multiplier(
            action.follow_multiplier, action.signal_entrust_qty, available_qty,
        )
    else:
        qty = _calc_sell_qty_by_position_ratio(
            action.signal_position_ratio, available_qty,
        )

    if used_fallback_price:
        logger.warning(
            "sell_price_fallback stock=%s limitdown_price=None using_signal_price=%.4f",
            stock_code, price
        )

    # 【先写】写入 pending 记录（防止崩溃后重复下单）
    _write_record(
        action, "sell",
        limit_price=price, quantity=qty,
        status="pending",
        signal_ratio=action.signal_cash_ratio,
    )

    try:
        # 【后执行】执行下单
        result = await trader.sell(stock_code, price, qty)
        entrust_no = result.get("entrust_no", "")

        # 合同编号为空时尝试从当日委托恢复
        recovered = False
        if not entrust_no:
            logger.warning("sell_empty_entrust_no stock=%s price=%.4f qty=%d, attempting recovery", stock_code, price, qty)
            entrust_no = await _recover_entrust_no(stock_code, "卖出", price, qty)
            if entrust_no:
                recovered = True

        detail_msg = None
        if used_fallback_price:
            detail_msg = f"涨跌停价缺失，使用喊单原价 {price:.4f} 作为卖出价"

        # 【更新】成功后更新为 success
        repository.update_follow_record(
            action.signal_entrust_no, "sell",
            status="success", entrust_no=entrust_no,
            detail=detail_msg,
        )
        extra = " (fallback_price)" if used_fallback_price else ""
        _log_entrust_no_result("sell", stock_code, price, qty, entrust_no, recovered=recovered, extra=extra)
    except Exception as exc:
        error_detail = str(exc)
        
        # SetForegroundWindow / SendInput 临时错误：重试一次
        if "setforegroundwindow" in error_detail.lower() or "sendinput" in error_detail.lower():
            logger.info("sell_transient_error stock=%s detail=%s, retrying after foreground", stock_code, exc)
            import asyncio
            await asyncio.sleep(0.3)
            try:
                result = await trader.sell(stock_code, price, qty)
                entrust_no = result.get("entrust_no", "")

                # 合同编号为空时尝试从当日委托恢复
                recovered = False
                if not entrust_no:
                    logger.warning("sell_retry_empty_entrust_no stock=%s, attempting recovery", stock_code)
                    entrust_no = await _recover_entrust_no(stock_code, "卖出", price, qty)
                    if entrust_no:
                        recovered = True

                detail_msg = None
                if used_fallback_price:
                    detail_msg = f"涨跌停价缺失，使用喊单原价 {price:.4f} 作为卖出价"
                repository.update_follow_record(
                    action.signal_entrust_no, "sell",
                    status="success", entrust_no=entrust_no,
                    detail=detail_msg,
                )
                _log_entrust_no_result("sell_retry", stock_code, price, qty, entrust_no, recovered=recovered)
                return
            except Exception as retry_exc:
                error_detail = str(retry_exc)
                logger.warning("sell_retry_failed stock=%s detail=%s", stock_code, retry_exc)
        
        # 【更新】失败后更新为 failed
        repository.update_follow_record(
            action.signal_entrust_no, "sell",
            status="failed", error_code="trade_error", detail=error_detail,
        )
        logger.error("sell_failed stock=%s detail=%s", stock_code, exc)


async def execute_cancel(action: FollowAction) -> None:
    trader = LocalTraderService.get()
    if not action.local_entrust_no:
        logger.warning("cancel skip no_local_entrust_no stock=%s", action.stock_code)
        return

    # 【先写】写入 pending 记录（防止崩溃后重复撤单）
    _write_record(
        action, "cancel",
        status="pending",
        entrust_no=action.local_entrust_no,
    )

    try:
        # 【后执行】执行撤单
        result = await trader.cancel_entrust(action.local_entrust_no)
        
        # 【更新】成功后更新为 success
        repository.update_follow_record(
            action.signal_entrust_no, "cancel",
            status="success", detail=str(result),
        )
        logger.info("cancel_ok stock=%s local_no=%s", action.stock_code, action.local_entrust_no)
    except Exception as exc:
        # 【更新】失败后更新为 failed
        repository.update_follow_record(
            action.signal_entrust_no, "cancel",
            status="failed", error_code="cancel_error", detail=str(exc),
        )
        logger.error("cancel_failed stock=%s detail=%s", action.stock_code, exc)


def _write_record(
    action: FollowAction,
    act: str,
    *,
    status: str,
    limit_price: Optional[float] = None,
    quantity: Optional[int] = None,
    entrust_no: Optional[str] = None,
    error_code: Optional[str] = None,
    detail: Optional[str] = None,
    signal_ratio: Optional[float] = None,
) -> None:
    try:
        repository.insert_follow_record({
            "stock_code": action.stock_code,
            "stock_name": action.stock_name,
            "action": act,
            "signal_entrust_no": action.signal_entrust_no,
            "signal_entrust_time": action.signal_entrust_time,
            "signal_original_price": action.signal_original_price,
            "signal_entrust_qty": action.signal_entrust_qty,
            "limit_price": limit_price,
            "quantity": quantity,
            "signal_ratio": signal_ratio,
            "follow_mode": action.follow_mode,
            "follow_multiplier": action.follow_multiplier if action.follow_mode == "multiplier" else None,
            "status": status,
            "entrust_no": entrust_no,
            "error_code": error_code,
            "detail": detail,
        })
    except Exception as exc:
        logger.error("write_record_failed action=%s stock=%s detail=%s", act, action.stock_code, exc)
