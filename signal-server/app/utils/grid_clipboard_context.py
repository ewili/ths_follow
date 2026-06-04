"""Grid Copy 剪贴板页上下文：冷却期内仅同页、同表头形状可复用。"""

from __future__ import annotations

GRID_PAGE_FUNDS_STOCK = "funds_stock"
GRID_PAGE_TODAY_ENTRUSTS = "today_entrusts"
GRID_PAGE_HISTORY_ENTRUSTS = "history_entrusts"

_ENTRUST_GRID_PAGES = frozenset({GRID_PAGE_TODAY_ENTRUSTS, GRID_PAGE_HISTORY_ENTRUSTS})

_clipboard_page: str | None = None
_requested_grid_page: str | None = None

_ENTRUST_CLIPBOARD_KEYS = frozenset({"合同编号", "委托价格", "委托数量", "委托时间"})
_POSITION_CLIPBOARD_KEYS = frozenset({"股票余额", "成本价", "参考成本价", "当日买入", "当日卖出"})


def set_grid_copy_context(page: str) -> None:
    global _requested_grid_page
    _requested_grid_page = page


def mark_clipboard_page(page: str | None) -> None:
    global _clipboard_page
    _clipboard_page = page


def get_requested_grid_page() -> str | None:
    return _requested_grid_page


def get_clipboard_page() -> str | None:
    return _clipboard_page


def looks_like_position_keys(keys: set[str]) -> bool:
    if keys & _ENTRUST_CLIPBOARD_KEYS:
        return False
    return bool(keys & _POSITION_CLIPBOARD_KEYS)


def records_match_grid_page(records: list[dict], page: str) -> bool:
    if not records:
        return page in _ENTRUST_GRID_PAGES
    keys = set(records[0].keys())
    if page in _ENTRUST_GRID_PAGES:
        if keys & _ENTRUST_CLIPBOARD_KEYS:
            return True
        return not looks_like_position_keys(keys)
    if page == GRID_PAGE_FUNDS_STOCK:
        return bool(keys & _POSITION_CLIPBOARD_KEYS) or not bool(keys & _ENTRUST_CLIPBOARD_KEYS)
    return True
