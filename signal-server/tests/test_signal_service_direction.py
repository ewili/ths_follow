"""signal_service 方向解析与过滤单元测试。"""

from app.services.signal_service import (
    _assemble_valid_entrust_dtos,
    _build_entrust_dto,
    _parse_direction,
)


def test_parse_direction_exact_match():
    assert _parse_direction("买入") == "买入"
    assert _parse_direction("卖出") == "卖出"
    assert _parse_direction(" 买入 ") == "买入"


def test_parse_direction_unknown_returns_none():
    assert _parse_direction("") is None
    assert _parse_direction("证券买入") is None


def test_build_entrust_dto_skips_unknown_direction():
    raw = {
        "证券代码": "600000",
        "操作": "",
        "委托价格": 10.0,
        "委托数量": 100,
    }
    limit_map = {
        "600000": {"limitup_price": 11.0, "limitdown_price": 9.0},
    }
    assert _build_entrust_dto(raw, limit_map, 1_000_000.0, {}) is None


def test_assemble_filters_no_direction():
    raw_entrusts = [
        {"证券代码": "600000", "操作": "买入", "委托价格": 10.0, "委托数量": 100},
        {"证券代码": "600001", "操作": "", "委托价格": 5.0, "委托数量": 200},
    ]
    limit_map = {
        "600000": {"limitup_price": 11.0, "limitdown_price": 9.0},
        "600001": {"limitup_price": 6.0, "limitdown_price": 4.0},
    }
    valid = _assemble_valid_entrust_dtos(raw_entrusts, limit_map, 1_000_000.0, {})
    assert len(valid) == 1
    assert valid[0].stock_code == "600000"
    assert valid[0].direction == "买入"
