"""对比逻辑：喊单委托 × 本地数据 → FollowAction 列表。

处理顺序：
1. 撤单跟随（优先）：喊单已撤 + 本地有对应未成交委托 → cancel
2. 买入跟随：未跟随过（follow_records 无记录）→ buy
3. 卖出跟随：未跟随过 + 本地有可用持仓 → sell
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from app.db import repository
from app.models.follow import FollowAction, SignalEntrustDTO

logger = logging.getLogger(__name__)

_CANCEL_STATUSES = {"已撤", "部撤"}
_SETTLED_STATUSES = {"已撤", "部撤", "已成", "全部成交"}


def _normalize_status(status: str) -> str:
    """去除 THS 备注字段中的括号后缀，如 "已撤(买卖)" → "已撤"。"""
    idx = status.find("(")
    if idx > 0:
        return status[:idx]
    return status


def _effective_status(sig: SignalEntrustDTO) -> str:
    """根据 filled_qty/canceled_qty 修正 THS 返回的不一致 status。

    THS 历史委托中 status="已成" 但 filled_qty=0、canceled_qty=entrust_qty 的情况
    屡有发生，实际应为"已撤"。此处以实际成交数据为准进行修正。
    """
    if sig.canceled_qty >= sig.entrust_qty and sig.filled_qty == 0:
        return "已撤"
    if sig.canceled_qty > 0 and sig.filled_qty == 0:
        return "部撤"
    return _normalize_status(sig.status)

# THS "当日委托" 的操作列（桌面客户端 "操作" 列）
_KEY_DIRECTION = "操作"
_KEY_STATUS = "备注"
_KEY_STOCK_CODE = "证券代码"
_KEY_ENTRUST_NO = "合同编号"


def _local_direction(raw: str) -> str:
    """统一买卖方向判断（兼容桌面"买入"/"卖出"）。"""
    if "卖" in raw:
        return "卖出"
    return "买入"


def compare_and_decide(
    signal_entrusts: list[SignalEntrustDTO],
    local_positions: list[dict],
    local_entrusts: list[dict],
    has_followed: Callable[[str, str], bool],
    start_timestamp: Optional[datetime] = None,
    follow_mode: str = "ratio",
    follow_multiplier: float = 1.0,
) -> list[FollowAction]:
    """生成本轮需要执行的跟单指令列表。

    Args:
        has_followed: 函数签名 (signal_entrust_no, action) -> bool，
                      查询 follow_records 判断是否已跟随过。
        start_timestamp: 冷启动时间戳；None 表示全量对齐。
        follow_mode: 跟单模式（ratio / multiplier）
        follow_multiplier: 跟单倍数（仅 multiplier 模式使用）
    """
    actions: list[FollowAction] = []

    pos_map: dict[str, int] = {}
    for p in local_positions:
        code = str(p.get("证券代码", p.get("stock_code", ""))).strip()
        avail = int(p.get("股份可用", p.get("可用余额", p.get("available_qty", 0))) or 0)
        if code:
            pos_map[code] = avail

    # ── 步骤 1：撤单跟随（优先） ─────────────────────────────
    for sig in signal_entrusts:
        # 【触发条件】检查喊单端委托状态（用修正后的有效状态）
        if _effective_status(sig) not in _CANCEL_STATUSES:
            continue

        # 【查询映射】从 follow_records 查询所有关联的本地委托编号
        local_nos = repository.get_local_entrust_nos_by_signal(sig.entrust_no)
        if not local_nos:
            logger.debug(
                "cancel_skip no_local_mapping signal_no=%s stock=%s",
                sig.entrust_no, sig.stock_code
            )
            continue

        # 【状态验证 + 执行过滤】对每个本地委托，确认其当前状态是否可撤
        for local_no in local_nos:
            # 在跟单端本地 today_entrusts 中查找该委托
            local_entrust = _find_local_entrust_by_no(local_entrusts, local_no)
            if not local_entrust:
                logger.debug(
                    "cancel_skip not_in_today_entrusts local_no=%s signal_no=%s",
                    local_no, sig.entrust_no
                )
                continue

            # 检查跟单端本地委托状态（来自 today_entrusts["备注"]字段）
            status = _normalize_status(str(local_entrust.get(_KEY_STATUS, "")))
            if status in _SETTLED_STATUSES:
                logger.debug(
                    "cancel_skip settled_status local_no=%s status=%s",
                    local_no, status
                )
                continue

            # 生成撤单指令
            logger.info(
                "cancel_follow stock=%s signal_no=%s local_no=%s",
                sig.stock_code, sig.entrust_no, local_no,
            )
            actions.append(FollowAction(
                action="cancel",
                stock_code=sig.stock_code,
                stock_name=sig.stock_name,
                signal_entrust_no=sig.entrust_no,
                signal_entrust_time=sig.entrust_time,
                signal_original_price=sig.original_price,
                signal_entrust_qty=sig.entrust_qty,
                local_entrust_no=local_no,
            ))

    # ── 步骤 1→2 过渡：从快照中移除即将被撤的本地委托，避免双重保险误判 ──
    cancelled_local_nos = {a.local_entrust_no for a in actions if a.action == "cancel" and a.local_entrust_no}
    if cancelled_local_nos:
        local_entrusts = [e for e in local_entrusts
                          if str(e.get(_KEY_ENTRUST_NO, e.get("entrust_no", ""))) not in cancelled_local_nos]

    # ── 步骤 2：买入跟随 ──────────────────────────────────────
    for sig in signal_entrusts:
        if sig.direction != "买入":
            continue
        if _effective_status(sig) in _CANCEL_STATUSES:
            continue
        if not _passes_cold_start(sig.entrust_time, start_timestamp, sig.entrust_date):
            logger.debug("cold_start skip buy stock=%s entrust_no=%s", sig.stock_code, sig.entrust_no)
            continue
        if has_followed(sig.entrust_no, "buy"):
            continue

        # 双重保险：本地已有匹配买单且未撤，跳过（防止崩溃后重复下单）
        local_buy = _find_local_entrust(
            local_entrusts,
            stock_code=sig.stock_code,
            direction="买入",
            exclude_statuses=_SETTLED_STATUSES,
        )
        if local_buy:
            local_no = str(local_buy.get(_KEY_ENTRUST_NO, ""))
            logger.warning(
                "local_buy_exists_but_no_record stock=%s signal_no=%s local_no=%s",
                sig.stock_code, sig.entrust_no, local_no
            )
            continue

        actions.append(FollowAction(
            action="buy",
            stock_code=sig.stock_code,
            stock_name=sig.stock_name,
            signal_entrust_no=sig.entrust_no,
            signal_entrust_time=sig.entrust_time,
            signal_original_price=sig.original_price,
            signal_entrust_qty=sig.entrust_qty,
            limit_price=sig.limit_price,
            signal_cash_ratio=sig.cash_ratio,
            follow_mode=follow_mode,
            follow_multiplier=follow_multiplier,
        ))

    # ── 步骤 3：卖出跟随 ──────────────────────────────────────
    for sig in signal_entrusts:
        if sig.direction != "卖出":
            continue
        if _effective_status(sig) in _CANCEL_STATUSES:
            continue
        if not _passes_cold_start(sig.entrust_time, start_timestamp, sig.entrust_date):
            logger.debug("cold_start skip sell stock=%s entrust_no=%s", sig.stock_code, sig.entrust_no)
            continue
        if has_followed(sig.entrust_no, "sell"):
            continue

        available = pos_map.get(sig.stock_code, 0)
        if available <= 0:
            logger.debug("no_position skip sell stock=%s", sig.stock_code)
            continue

        # 双重保险：本地已有匹配卖单且未撤，跳过
        local_sell = _find_local_entrust(
            local_entrusts,
            stock_code=sig.stock_code,
            direction="卖出",
            exclude_statuses={"已撤", "部撤"},
        )
        if local_sell:
            logger.debug("local_sell_exists skip stock=%s", sig.stock_code)
            continue

        actions.append(FollowAction(
            action="sell",
            stock_code=sig.stock_code,
            stock_name=sig.stock_name,
            signal_entrust_no=sig.entrust_no,
            signal_entrust_time=sig.entrust_time,
            signal_original_price=sig.original_price,
            signal_entrust_qty=sig.entrust_qty,
            limit_price=sig.limit_price,
            signal_cash_ratio=sig.cash_ratio,
            signal_position_ratio=sig.position_ratio,
            follow_mode=follow_mode,
            follow_multiplier=follow_multiplier,
        ))

    return actions


def _find_local_entrust(
    local_entrusts: list[dict],
    stock_code: str,
    direction: str,
    exclude_statuses: set[str],
) -> Optional[dict]:
    """在本地当日委托中找匹配的委托（股票代码 + 方向 + 非终态）。"""
    for e in local_entrusts:
        code = str(e.get(_KEY_STOCK_CODE, e.get("stock_code", "")))
        raw_dir = str(e.get(_KEY_DIRECTION, e.get("direction", "")))
        status = _normalize_status(str(e.get(_KEY_STATUS, e.get("status", ""))))
        if code == stock_code and _local_direction(raw_dir) == direction and status not in exclude_statuses:
            return e
    return None


def _find_local_entrust_by_no(
    local_entrusts: list[dict],
    entrust_no: str,
) -> Optional[dict]:
    """通过合同编号精确查找本地委托。"""
    for e in local_entrusts:
        no = str(e.get(_KEY_ENTRUST_NO, e.get("entrust_no", "")))
        if no == entrust_no:
            return e
    return None


def _passes_cold_start(
    entrust_time: str,
    start_timestamp: Optional[datetime],
    entrust_date: str = "",
) -> bool:
    """冷启动过滤：若 start_timestamp 不为 None，仅处理委托时间 >= 启动时间的委托。

    entrust_time 格式为 "HH:MM:SS"，与 start_timestamp 的时间部分比较。
    entrust_date 格式为 "YYYY-MM-DD" 或 "YYYY/MM/DD"（THS 历史委托"委托日期"列），
    当日委托/历史当日委托无此列时为空字符串。
    若 entrust_date 非空，先按日期比较；日期相同再按时间比较。
    """
    if start_timestamp is None:
        return True
    # 若有委托日期，先按日期比较
    if entrust_date:
        try:
            # 兼容 "YYYY-MM-DD" 和 "YYYY/MM/DD"
            normalized = entrust_date.replace("/", "-")
            entrust_dt = datetime.strptime(normalized, "%Y-%m-%d").date()
            start_dt = start_timestamp.date()
            if entrust_dt < start_dt:
                return False
            if entrust_dt > start_dt:
                return True
            # 日期相同，继续按时间比较
        except Exception:
            pass  # 解析失败则回退到时间比较
    try:
        h, m, s = entrust_time.split(":")
        et_seconds = int(h) * 3600 + int(m) * 60 + int(s)
        start_seconds = (
            start_timestamp.hour * 3600
            + start_timestamp.minute * 60
            + start_timestamp.second
        )
        return et_seconds >= start_seconds
    except Exception:
        return True
