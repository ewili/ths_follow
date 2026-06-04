"""同花顺 GUI 数据拉取：合并同页 Copy、委托表校验，减少验证码与错页。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PAGE_SETTLE_SECONDS = 0.15

_ENTRUST_MARKER_KEYS = frozenset({"合同编号", "委托价格", "委托数量", "委托时间"})
_POSITION_MARKER_KEYS = frozenset({"股票余额", "成本价", "参考成本价", "当日买入", "当日卖出"})


def grid_sample_keys(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    return list(rows[0].keys())


def looks_like_position_grid(rows: list[dict]) -> bool:
    if not rows:
        return False
    keys = set(rows[0].keys())
    if keys & _ENTRUST_MARKER_KEYS:
        return False
    return bool(keys & _POSITION_MARKER_KEYS)


def looks_like_entrust_grid(rows: list[dict]) -> bool:
    if not rows:
        return True
    keys = set(rows[0].keys())
    return bool(keys & _ENTRUST_MARKER_KEYS)


def fetch_funds_stock(trader: Any) -> tuple[dict, list[dict]]:
    from app.utils.grid_clipboard_context import GRID_PAGE_FUNDS_STOCK, set_grid_copy_context

    trader._switch_left_menus(["查询[F4]", "资金股票"])
    trader.wait(_PAGE_SETTLE_SECONDS)
    balance = trader._get_balance_from_statics()
    set_grid_copy_context(GRID_PAGE_FUNDS_STOCK)
    positions = trader._get_grid_data(trader.config.COMMON_GRID_CONTROL_ID) or []
    return balance, positions


def fetch_today_entrusts(trader: Any, *, max_attempts: int = 2) -> list[dict]:
    last_keys: list[str] = []
    from app.utils.grid_clipboard_context import GRID_PAGE_TODAY_ENTRUSTS, set_grid_copy_context

    for attempt in range(max_attempts):
        trader._switch_left_menus(["查询[F4]", "当日委托"])
        trader.wait(_PAGE_SETTLE_SECONDS)
        set_grid_copy_context(GRID_PAGE_TODAY_ENTRUSTS)
        rows = trader._get_grid_data(trader.config.COMMON_GRID_CONTROL_ID) or []
        if not rows:
            return []
        last_keys = grid_sample_keys(rows)
        if looks_like_position_grid(rows):
            logger.warning(
                "today_entrusts_wrong_page attempt=%d/%d sample_keys=%s",
                attempt + 1,
                max_attempts,
                last_keys[:12],
            )
            continue
        if looks_like_entrust_grid(rows):
            return rows
        logger.warning(
            "today_entrusts_unknown_grid attempt=%d/%d sample_keys=%s",
            attempt + 1,
            max_attempts,
            last_keys[:12],
        )
    logger.error(
        "today_entrusts_aborted_after_retries sample_keys=%s",
        last_keys[:12],
    )
    return []


def _click_history_period_button(trader: Any, period: str) -> None:
    try:
        main_win = trader._main
        btn = main_win.child_window(title=period, class_name="Button")
        if btn.exists():
            btn.click()
            trader.wait(_PAGE_SETTLE_SECONDS)
        else:
            logger.warning("历史委托周期按钮 %s 未找到，可能已默认选中", period)
    except Exception as e:
        logger.warning("历史委托周期按钮 %s 点击失败: %s", period, e)


def fetch_history_entrusts(
    trader: Any, period: str, *, max_attempts: int = 2
) -> list[dict]:
    from app.utils.grid_clipboard_context import (
        GRID_PAGE_HISTORY_ENTRUSTS,
        set_grid_copy_context,
    )

    last_keys: list[str] = []
    for attempt in range(max_attempts):
        trader._switch_left_menus(["查询[F4]", "历史委托"])
        trader.wait(_PAGE_SETTLE_SECONDS)
        _click_history_period_button(trader, period)
        set_grid_copy_context(GRID_PAGE_HISTORY_ENTRUSTS)
        rows = trader._get_grid_data(trader.config.COMMON_GRID_CONTROL_ID) or []
        if not rows:
            return []
        last_keys = grid_sample_keys(rows)
        if looks_like_position_grid(rows):
            logger.warning(
                "history_entrusts_wrong_page period=%s attempt=%d/%d sample_keys=%s",
                period,
                attempt + 1,
                max_attempts,
                last_keys[:12],
            )
            continue
        if looks_like_entrust_grid(rows):
            return rows
        logger.warning(
            "history_entrusts_unknown_grid period=%s attempt=%d/%d sample_keys=%s",
            period,
            attempt + 1,
            max_attempts,
            last_keys[:12],
        )
    logger.error(
        "history_entrusts_aborted_after_retries period=%s sample_keys=%s",
        period,
        last_keys[:12],
    )
    return []
