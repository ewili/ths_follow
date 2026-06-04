from app.utils.grid_clipboard_context import (
    GRID_PAGE_FUNDS_STOCK,
    GRID_PAGE_HISTORY_ENTRUSTS,
    GRID_PAGE_TODAY_ENTRUSTS,
    records_match_grid_page,
)
from app.utils.ths_gui_fetch import (
    looks_like_entrust_grid,
    looks_like_position_grid,
)


def test_position_grid_detected():
    rows = [{"证券代码": "600000", "股票余额": 100, "成本价": 10.0}]
    assert looks_like_position_grid(rows)
    assert not looks_like_entrust_grid(rows)


def test_entrust_grid_detected():
    rows = [{"证券代码": "600000", "合同编号": "123", "委托价格": 10.0, "操作": ""}]
    assert looks_like_entrust_grid(rows)
    assert not looks_like_position_grid(rows)


def test_entrust_with_empty_operation_still_entrust():
    rows = [{"合同编号": "1", "委托数量": 100, "操作": ""}]
    assert looks_like_entrust_grid(rows)


def test_clipboard_page_mismatch_blocks_reuse_shape():
    position_rows = [{"证券代码": "600000", "股票余额": 100, "成本价": 10.0}]
    assert records_match_grid_page(position_rows, GRID_PAGE_FUNDS_STOCK)
    assert not records_match_grid_page(position_rows, GRID_PAGE_TODAY_ENTRUSTS)


def test_clipboard_entrust_shape_matches_entrust_page():
    entrust_rows = [{"合同编号": "1", "委托价格": 10.0, "操作": ""}]
    assert records_match_grid_page(entrust_rows, GRID_PAGE_TODAY_ENTRUSTS)


def test_clipboard_history_entrust_page_same_shape_as_today():
    history_rows = [{"合同编号": "1", "委托日期": "2026-06-04", "委托价格": 10.0}]
    assert records_match_grid_page(history_rows, GRID_PAGE_HISTORY_ENTRUSTS)
    assert not records_match_grid_page(
        [{"股票余额": 100, "成本价": 10.0}], GRID_PAGE_HISTORY_ENTRUSTS
    )
