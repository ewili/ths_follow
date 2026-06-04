"""SignalService：喊单数据查询的三层并发缓存（US-003）。

架构（详见 docs/design/US-003-signal-order-query-api.md §4）::

    HTTP 请求（最多 20 并发）
       │
       ▼
    [L1] TTL Cache (1.0s)   → 命中即返回，~1ms
       │ miss
       ▼
    [L2] Singleflight       → N 个并发 miss 合并为 1 次拉取，失败时共享异常
       │ leader 继续
       ▼
    [L3] TraderService.with_lock (asyncio.Lock + 线程池)
       │
       ▼
    easytrader.balance / .position / .today_entrusts

职责分离原则：

- L1 解决"重复请求"
- L2 解决"并发雪崩 + 失败级联"
- L3 解决"跨 key GUI 资源互斥"（由 US-001 既有 TraderService 提供）

本模块全部状态由 asyncio 单线程访问，dict 读写无需额外锁。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal, Optional

from app.db import stock_repository
from app.core.schedule_guard import is_within_schedule
from app.db import repository
from app.models.signal import (
    SignalBalanceDTO,
    SignalEntrustDTO,
    SignalPositionDTO,
)
from app.services.runtime_metrics_service import RuntimeMetricsService
from app.services.trader_service import TraderService
from app.utils.ths_gui_fetch import fetch_funds_stock, fetch_today_entrusts

logger = logging.getLogger(__name__)


# ── 配置常量 ───────────────────────────────────────────────

#: 缓存 TTL（秒）；每次 GUI 操作必然触发验证码（2-10s），过短 TTL 会导致频繁验证码恶性循环
TTL_SECONDS: float = 10.0

CacheKey = Literal["balance", "position", "entrusts"]


# ── 缓存条目 ───────────────────────────────────────────────


@dataclass
class _CacheEntry:
    """缓存中存放的一条记录。"""

    value: Any                  # easytrader 返回的原始数据（dict / list[dict]）
    fetched_at: datetime        # 写入缓存时的 wall clock（暴露给客户端做陈旧度判断）
    expires_at: float           # monotonic 秒，TTL 过期时刻


# ── 业务字段映射常量 ────────────────────────────────────────
# 字段口径来源：docs/easytrader-evaluation.md §3 字段映射表

_BAL_KEY_CASH_BALANCE = "资金余额"
_BAL_KEY_AVAILABLE_CASH = "可用金额"
_BAL_KEY_WITHDRAWABLE_CASH = "可取金额"
_BAL_KEY_MARKET_VALUE = "股票市值"
_BAL_KEY_TOTAL_ASSETS = "总资产"

_POS_KEY_STOCK_CODE = "证券代码"
_POS_KEY_STOCK_NAME = "证券名称"
_POS_KEY_POSITION_QTY = "股票余额"
_POS_KEY_AVAILABLE_QTY = "可用余额"
_POS_KEY_COST_PRICE = "参考成本价"
_POS_KEY_MARKET_PRICE = "市价"
_POS_KEY_MARKET_VALUE = "市值"
_POS_KEY_PROFIT_LOSS = "参考盈亏"
_POS_KEY_TODAY_BUY_QTY = "当日买入"
_POS_KEY_TODAY_SELL_QTY = "当日卖出"

_ENT_KEY_STOCK_CODE = "证券代码"
_ENT_KEY_STOCK_NAME = "证券名称"
# Copy 策略用剪贴板首行作 dict 键；THS 须含「操作」列且值为「买入」/「卖出」。
# 列缺失或券商异名时 raw 无此键或值为空，见 entrusts_direction_missing 日志中的 sample_keys。
_ENT_KEY_DIRECTION = "操作"
_ENT_KEY_PRICE = "委托价格"
_ENT_KEY_QTY = "委托数量"
_ENT_KEY_FILLED_QTY = "成交数量"
_ENT_KEY_CANCELED_QTY = "撤消数量"
_ENT_KEY_STATUS = "备注"
_ENT_KEY_ENTRUST_NO = "合同编号"
_ENT_KEY_ENTRUST_TIME = "委托时间"
_ENT_KEY_ENTRUST_DATE = "委托日期"
_ENT_KEY_ENTRUST_ATTR = "委托属性"


# ── 核心服务 ────────────────────────────────────────────────


class SignalService:
    """喊单数据查询单例：TTL 缓存 + Singleflight + 业务组装。"""

    _instance: Optional["SignalService"] = None

    def __init__(self) -> None:
        self._cache: dict[CacheKey, _CacheEntry] = {}
        self._inflight: dict[CacheKey, asyncio.Future] = {}
        self._snapshot_inflight: Optional[asyncio.Future] = None

    # ── 单例管理 ──────────────────────────────────────────

    @classmethod
    def get(cls) -> "SignalService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """仅供测试使用：销毁单例，清空 cache 与 inflight。"""
        cls._instance = None

    # ── 缓存自省（暴露给路由层做 fetched_at）─────────────

    def fetched_at_of(self, key: CacheKey) -> datetime:
        """读取 key 对应缓存的 fetched_at。

        如果 key 不存在（理论上不应发生，因为调用方刚 await 完一次拉取），
        返回 now() 作为兜底。
        """
        entry = self._cache.get(key)
        return entry.fetched_at if entry is not None else datetime.now()

    def stale_cache_of(self, key: CacheKey) -> Optional[_CacheEntry]:
        """返回已过期的缓存条目（供降级使用），无缓存时返回 None。"""
        return self._cache.get(key)

    def _cache_valid(self, key: CacheKey) -> bool:
        entry = self._cache.get(key)
        return entry is not None and entry.expires_at > time.monotonic()

    async def _ensure_snapshot_cached(self, *, include_entrusts: bool = True, include_funds: bool = True) -> None:
        """单次 with_lock 拉取资金/持仓/（可选）当日委托，写入 TTL 缓存。

        减少跨页多次 Copy 触发的验证码弹窗。
        倍数模式下 include_funds=False 时跳过 balance/position 拉取。
        """
        keys: list[CacheKey] = []
        if include_funds:
            keys = ["balance", "position"]
        if include_entrusts:
            keys = ["entrusts", *keys]
        if all(self._cache_valid(k) for k in keys):
            return

        if self._snapshot_inflight is not None:
            await self._snapshot_inflight
            return

        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        fut.add_done_callback(lambda done: done.exception())
        self._snapshot_inflight = fut

        t0 = time.perf_counter()
        try:
            for k in keys:
                if not self._cache_valid(k):
                    RuntimeMetricsService.get().record_cache_miss(k)

            def _snapshot(trader) -> tuple[Optional[list], Optional[dict], Optional[list]]:
                entrusts: Optional[list] = None
                balance: Optional[dict] = None
                positions: Optional[list] = None
                need_funds = (
                    not self._cache_valid("balance")
                    or not self._cache_valid("position")
                )
                if need_funds:
                    balance, positions = fetch_funds_stock(trader)
                if include_entrusts and not self._cache_valid("entrusts"):
                    entrusts = fetch_today_entrusts(trader)
                return entrusts, balance, positions

            entrusts, balance, positions = await TraderService.get().with_lock(
                _snapshot,
                op_name="today_snapshot" if include_entrusts else "funds_snapshot",
            )

            now_dt = datetime.now()
            expires_at = time.monotonic() + TTL_SECONDS
            if entrusts is not None:
                self._cache["entrusts"] = _CacheEntry(
                    value=entrusts,
                    fetched_at=now_dt,
                    expires_at=expires_at,
                )
            if balance is not None:
                self._cache["balance"] = _CacheEntry(
                    value=balance,
                    fetched_at=now_dt,
                    expires_at=expires_at,
                )
            if positions is not None:
                self._cache["position"] = _CacheEntry(
                    value=positions,
                    fetched_at=now_dt,
                    expires_at=expires_at,
                )

            if not fut.done():
                fut.set_result(None)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "cache_miss snapshot include_entrusts=%s gui_elapsed_ms=%.0f",
                include_entrusts,
                elapsed,
            )
        except BaseException as exc:
            if not fut.done():
                fut.set_exception(exc)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(
                "cache_miss_failed snapshot include_entrusts=%s gui_elapsed_ms=%.0f detail=%s",
                include_entrusts,
                elapsed,
                exc,
            )
            raise
        finally:
            self._snapshot_inflight = None

    # ── 三层算法核心：快路径 → singleflight → leader ────

    async def _get_or_fetch(
        self,
        key: CacheKey,
        fetch_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        """三层并发读取的核心算法。

        阶段 1（快路径）：无锁查 cache，命中即返回
        阶段 2（singleflight）：发现 inflight Future 时 await 同一个 Future
        阶段 3（leader）：自己创建 Future 发起真实拉取，完成后唤醒所有等待者
        """
        if key in ("entrusts", "balance", "position"):
            include_entrusts = key == "entrusts"
            await self._ensure_snapshot_cached(include_entrusts=include_entrusts)

        # 阶段 1：快路径（dict.get 是 asyncio 单线程下的原子操作）
        entry = self._cache.get(key)
        now = time.monotonic()
        if entry is not None and entry.expires_at > now:
            RuntimeMetricsService.get().record_cache_hit(key)
            logger.debug("cache_hit key=%s age_ms=%.0f", key, 0)
            return entry.value

        # 阶段 2：singleflight 合流
        inflight = self._inflight.get(key)
        if inflight is not None:
            logger.debug("singleflight_collapse key=%s", key)
            return await inflight

        # 阶段 3：作为 leader 发起真实拉取
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        fut.add_done_callback(lambda done: done.exception())
        self._inflight[key] = fut

        t0 = time.perf_counter()
        try:
            RuntimeMetricsService.get().record_cache_miss(key)
            value = await fetch_fn()
            self._cache[key] = _CacheEntry(
                value=value,
                fetched_at=datetime.now(),
                expires_at=time.monotonic() + TTL_SECONDS,
            )
            if not fut.done():
                fut.set_result(value)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "cache_miss key=%s gui_elapsed_ms=%.0f", key, elapsed
            )
            return value
        except BaseException as exc:
            if not fut.done():
                fut.set_exception(exc)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(
                "cache_miss_failed key=%s gui_elapsed_ms=%.0f detail=%s",
                key,
                elapsed,
                exc,
            )
            raise
        finally:
            # 无论成功/失败都从 inflight 移除：
            # - 失败的等待者已收到异常，下次请求才会重新尝试
            # - 由于 finally 在 await fut 完成后才运行，所有等待者已被唤醒
            self._inflight.pop(key, None)

    # ── 三类原始数据的 fetch（调用 TraderService.with_lock） ─

    async def _fetch_balance(self) -> dict:
        balance, _ = await self._fetch_funds_stock_pair()
        return balance

    async def _fetch_position(self) -> list[dict]:
        _, positions = await self._fetch_funds_stock_pair()
        return positions

    async def _fetch_funds_stock_pair(self) -> tuple[dict, list[dict]]:
        """单次进入资金股票页，同时拉资金与持仓。"""
        return await TraderService.get().with_lock(
            lambda t: fetch_funds_stock(t),
            op_name="funds_snapshot",
        )

    async def _fetch_entrusts(self) -> list[dict]:
        return await TraderService.get().with_lock(
            lambda t: fetch_today_entrusts(t),
            op_name="entrusts",
        )

    # ── 时段守卫 ────────────────────────────────────────

    def _is_schedule_paused(self) -> bool:
        """时段控制启用且不在运行时段时返回 True。"""
        cfg = repository.load_config()
        if cfg.schedule_enabled:
            time_ranges_dicts = [tr.model_dump() for tr in cfg.schedule_time_ranges]
            if not is_within_schedule(cfg.schedule_weekdays, time_ranges_dicts):
                return True
        return False

    # ── 公开 API：返回 DTO ────────────────────────────────

    async def get_balance(self) -> SignalBalanceDTO:
        if self._is_schedule_paused():
            logger.info("balance_skipped_schedule_paused")
            return SignalBalanceDTO(
                cash_balance=0.0, available_cash=0.0,
                withdrawable_cash=0.0, market_value=0.0, total_assets=0.0,
            )
        raw = await self._get_or_fetch("balance", self._fetch_balance)
        return _balance_to_dto(raw or {})

    async def get_positions(self) -> list[SignalPositionDTO]:
        if self._is_schedule_paused():
            logger.info("positions_skipped_schedule_paused")
            return []
        raw = await self._get_or_fetch("position", self._fetch_position)
        return [_position_to_dto(p) for p in (raw or [])]

    async def get_entrusts(self) -> tuple[list[SignalEntrustDTO], Optional[str]]:
        """获取当日委托 + 价格替换 + 比例计算。

        返回 (items, trade_date)；trade_date 为涨跌停价对应的交易日，无数据时 None。
        时段控制启用且不在运行时段时，直接返回空列表，避免非交易时段 GUI 调用。

        倍数模式下跳过 balance/position 拉取，cash_ratio/position_ratio 返回 None。
        """
        if self._is_schedule_paused():
            logger.info("entrusts_skipped_schedule_paused")
            return [], None

        # 获取当前模式
        from app.services.signal_runtime_service import SignalRuntimeService
        signal_mode = SignalRuntimeService.get().get_mode().signal_mode

        if signal_mode == "multiplier":
            # 倍数模式：仅拉取 entrusts，不拉 balance/position
            await self._ensure_snapshot_cached(include_entrusts=True, include_funds=False)
            raw_entrusts = await self._get_or_fetch("entrusts", self._fetch_entrusts)
            raw_entrusts = raw_entrusts or []

            codes = sorted({str(e.get(_ENT_KEY_STOCK_CODE, "")).strip() for e in raw_entrusts})
            limit_map, trade_date = stock_repository.get_limit_prices_by_codes(codes)

            # 诊断日志
            if raw_entrusts:
                matched_codes = [c for c in codes if c in limit_map]
                logger.info(
                    "entrusts_diagnosis mode=multiplier raw_count=%d codes=%d limit_matched=%d trade_date=%s",
                    len(raw_entrusts), len(codes), len(matched_codes), trade_date,
                )

            valid_items = _assemble_valid_entrust_dtos(
                raw_entrusts, limit_map, total_assets=0.0, pos_qty_map={}, signal_mode=signal_mode
            )
            return valid_items, trade_date

        # 资金比例模式：原有逻辑不变
        await self._ensure_snapshot_cached(include_entrusts=True)
        raw_entrusts = await self._get_or_fetch("entrusts", self._fetch_entrusts)
        raw_balance = await self._get_or_fetch("balance", self._fetch_balance)
        raw_positions = await self._get_or_fetch("position", self._fetch_position)
        raw_entrusts = raw_entrusts or []
        raw_positions = raw_positions or []

        total_assets = _to_float(raw_balance.get(_BAL_KEY_TOTAL_ASSETS), 0.0)
        pos_qty_map: dict[str, int] = {
            str(p.get(_POS_KEY_STOCK_CODE, "")).strip(): _to_int(p.get(_POS_KEY_POSITION_QTY), 0)
            for p in raw_positions
        }

        codes = sorted({str(e.get(_ENT_KEY_STOCK_CODE, "")).strip() for e in raw_entrusts})
        limit_map, trade_date = stock_repository.get_limit_prices_by_codes(codes)

        # 诊断日志：帮助排查委托为空的根因
        if raw_entrusts:
            matched_codes = [c for c in codes if c in limit_map]
            logger.info(
                "entrusts_diagnosis mode=ratio raw_count=%d codes=%d limit_matched=%d trade_date=%s",
                len(raw_entrusts), len(codes), len(matched_codes), trade_date,
            )
        if trade_date is None and raw_entrusts:
            logger.warning(
                "entrusts_filtered_all: stock_limit_prices 表无数据，%d 笔委托因缺少涨跌停价被过滤，"
                "请通过 POST /api/stock/fetch 采集股票行情数据",
                len(raw_entrusts),
            )

        valid_items = _assemble_valid_entrust_dtos(
            raw_entrusts, limit_map, total_assets, pos_qty_map, signal_mode=signal_mode
        )
        return valid_items, trade_date

    async def get_history_entrusts_as_dto(
        self, period: str
    ) -> tuple[list[SignalEntrustDTO], Optional[str]]:
        """获取历史委托并组装为跟单 DTO 格式（与 get_entrusts 返回格式一致）。

        供跟单端调用，使历史委托也能复用现有 comparator + order_executor 逻辑。
        """
        from app.services.signal_runtime_service import SignalRuntimeService
        signal_mode = SignalRuntimeService.get().get_mode().signal_mode

        raw_entrusts = await TraderService.get().get_history_entrusts(period)
        raw_entrusts = raw_entrusts or []

        if signal_mode == "multiplier":
            # 倍数模式：不拉 balance/position
            codes = sorted({str(e.get(_ENT_KEY_STOCK_CODE, "")).strip() for e in raw_entrusts})
            limit_map, trade_date = stock_repository.get_limit_prices_by_codes(codes)
            return _assemble_valid_entrust_dtos(
                raw_entrusts, limit_map, total_assets=0.0, pos_qty_map={}, signal_mode=signal_mode
            ), trade_date

        # 资金比例模式：原有逻辑
        await self._ensure_snapshot_cached(include_entrusts=False)
        raw_balance = await self._get_or_fetch("balance", self._fetch_balance)
        raw_positions = await self._get_or_fetch("position", self._fetch_position)
        raw_positions = raw_positions or []

        total_assets = _to_float(raw_balance.get(_BAL_KEY_TOTAL_ASSETS), 0.0)
        pos_qty_map: dict[str, int] = {
            str(p.get(_POS_KEY_STOCK_CODE, "")).strip(): _to_int(p.get(_POS_KEY_POSITION_QTY), 0)
            for p in raw_positions
        }

        codes = sorted({str(e.get(_ENT_KEY_STOCK_CODE, "")).strip() for e in raw_entrusts})
        limit_map, trade_date = stock_repository.get_limit_prices_by_codes(codes)

        return _assemble_valid_entrust_dtos(
            raw_entrusts, limit_map, total_assets, pos_qty_map, signal_mode=signal_mode
        ), trade_date


def _is_valid_signal_entrust(dto: SignalEntrustDTO) -> bool:
    """过滤不可跟单的委托：无涨跌停价或非买卖类型。"""
    if not dto.has_limit_price:
        return False
    if "买卖" not in dto.entrust_attr:
        return False
    return True


def _assemble_valid_entrust_dtos(
    raw_entrusts: list[dict],
    limit_map: dict[str, dict],
    total_assets: float,
    pos_qty_map: dict[str, int],
    signal_mode: Literal["ratio", "multiplier"] = "ratio",
) -> list[SignalEntrustDTO]:
    """从 easytrader 原始委托构建 DTO，过滤未知方向与无效信号。"""
    items: list[SignalEntrustDTO] = []
    for e in raw_entrusts:
        dto = _build_entrust_dto(e, limit_map, total_assets, pos_qty_map, signal_mode=signal_mode)
        if dto is not None:
            items.append(dto)
    return _log_and_filter_entrust_items(raw_entrusts, items)


def _log_and_filter_entrust_items(
    raw_entrusts: list[dict],
    items: list[SignalEntrustDTO],
) -> list[SignalEntrustDTO]:
    valid_items = [it for it in items if _is_valid_signal_entrust(it)]
    filtered_no_direction = len(raw_entrusts) - len(items)
    if filtered_no_direction > 0 or len(valid_items) != len(items):
        no_limit = sum(1 for it in items if not it.has_limit_price)
        non_maimai = sum(1 for it in items if "买卖" not in it.entrust_attr)
        logger.info(
            "entrusts_filter raw=%d with_direction=%d valid=%d "
            "filtered_no_direction=%d filtered_no_limit=%d filtered_non_maimai=%d",
            len(raw_entrusts),
            len(items),
            len(valid_items),
            filtered_no_direction,
            no_limit,
            non_maimai,
        )
        if filtered_no_direction > 0 and raw_entrusts:
            # Copy 剪贴板表头须含「操作」列，否则 direction 为空；便于对照 THS 列名
            logger.info(
                "entrusts_direction_missing count=%d sample_keys=%s",
                filtered_no_direction,
                sorted(raw_entrusts[0].keys()),
            )
    return valid_items


# ── 业务组装辅助函数（模块级，纯函数，便于单测） ───────────


def _balance_to_dto(raw: dict) -> SignalBalanceDTO:
    return SignalBalanceDTO(
        cash_balance=_to_float(raw.get(_BAL_KEY_CASH_BALANCE), 0.0),
        available_cash=_to_float(raw.get(_BAL_KEY_AVAILABLE_CASH), 0.0),
        withdrawable_cash=_to_float(raw.get(_BAL_KEY_WITHDRAWABLE_CASH), 0.0),
        market_value=_to_float(raw.get(_BAL_KEY_MARKET_VALUE), 0.0),
        total_assets=_to_float(raw.get(_BAL_KEY_TOTAL_ASSETS), 0.0),
    )


def _position_to_dto(raw: dict) -> SignalPositionDTO:
    return SignalPositionDTO(
        stock_code=str(raw.get(_POS_KEY_STOCK_CODE, "")),
        stock_name=str(raw.get(_POS_KEY_STOCK_NAME, "")),
        position_qty=_to_int(raw.get(_POS_KEY_POSITION_QTY), 0),
        available_qty=_to_int(raw.get(_POS_KEY_AVAILABLE_QTY), 0),
        cost_price=_to_float(raw.get(_POS_KEY_COST_PRICE), 0.0),
        market_price=_to_float(raw.get(_POS_KEY_MARKET_PRICE), 0.0),
        market_value=_to_float(raw.get(_POS_KEY_MARKET_VALUE), 0.0),
        profit_loss=_to_float(raw.get(_POS_KEY_PROFIT_LOSS), 0.0),
        today_buy_qty=_to_int(raw.get(_POS_KEY_TODAY_BUY_QTY), 0),
        today_sell_qty=_to_int(raw.get(_POS_KEY_TODAY_SELL_QTY), 0),
    )


def _build_entrust_dto(
    raw: dict,
    limit_map: dict[str, dict],
    total_assets: float,
    pos_qty_map: dict[str, int],
    signal_mode: Literal["ratio", "multiplier"] = "ratio",
) -> Optional[SignalEntrustDTO]:
    """组装单笔委托 DTO：价格替换 + ratio 计算。

    「操作」列无法识别为买入/卖出时返回 None（不进入 API）。
    倍数模式下跳过 cash_ratio/position_ratio 计算，返回 None。
    """
    stock_code = str(raw.get(_ENT_KEY_STOCK_CODE, "")).strip()
    direction_raw = str(raw.get(_ENT_KEY_DIRECTION, ""))
    direction = _parse_direction(direction_raw)
    if direction is None:
        return None
    original_price = _to_float(raw.get(_ENT_KEY_PRICE), 0.0)
    entrust_qty = _to_int(raw.get(_ENT_KEY_QTY), 0)
    filled_qty = _to_int(raw.get(_ENT_KEY_FILLED_QTY), 0)

    # 价格替换 + 降级标记
    limit_entry = limit_map.get(stock_code)
    if limit_entry is None:
        limit_price: Optional[float] = None
        has_limit_price = False
    else:
        if direction == "买入":
            limit_price = _to_float(limit_entry.get("limitup_price"), 0.0)
        else:
            limit_price = _to_float(limit_entry.get("limitdown_price"), 0.0)
        has_limit_price = limit_price > 0

    # 倍数模式下跳过 ratio 计算
    cash_ratio: Optional[float] = None
    position_ratio: Optional[float] = None
    if signal_mode == "ratio":
        # ratio 计算：已成交用 filled_qty（实际资金部署），未成交用 entrust_qty（意图）
        # 分母使用"总资产"（现金+市值），代表账户真实规模，保证等比例跟单
        ratio_qty = filled_qty if filled_qty > 0 else entrust_qty
        if direction == "买入":
            cash_ratio = _compute_cash_ratio(original_price, ratio_qty, total_assets)
        elif direction == "卖出":
            cash_ratio = _compute_cash_ratio(original_price, ratio_qty, total_assets)
            position_ratio = _compute_position_ratio(stock_code, ratio_qty, pos_qty_map)

    return SignalEntrustDTO(
        stock_code=stock_code,
        stock_name=str(raw.get(_ENT_KEY_STOCK_NAME, "")),
        direction=direction,
        original_price=original_price,
        limit_price=limit_price if has_limit_price else None,
        has_limit_price=has_limit_price,
        entrust_qty=entrust_qty,
        filled_qty=filled_qty,
        canceled_qty=_to_int(raw.get(_ENT_KEY_CANCELED_QTY), 0),
        status=str(raw.get(_ENT_KEY_STATUS, "")),
        entrust_no=str(raw.get(_ENT_KEY_ENTRUST_NO, "")),
        entrust_time=str(raw.get(_ENT_KEY_ENTRUST_TIME, "")),
        entrust_date=str(raw.get(_ENT_KEY_ENTRUST_DATE, "")),
        entrust_attr=str(raw.get(_ENT_KEY_ENTRUST_ATTR, "买卖")),
        cash_ratio=cash_ratio,
        position_ratio=position_ratio,
    )


def _parse_direction(raw_direction: str) -> Optional[Literal["买入", "卖出"]]:
    """精确匹配 THS「操作」列：仅「买入」「卖出」有效，否则返回 None。"""
    normalized = raw_direction.strip()
    if normalized == "买入":
        return "买入"
    if normalized == "卖出":
        return "卖出"
    return None


def _compute_cash_ratio(
    price: float, qty: int, total_assets: float
) -> Optional[float]:
    """委托占账户总资产比例。除零保护返回 None。"""
    if total_assets <= 0:
        return None
    return price * qty / total_assets


def _compute_position_ratio(
    stock_code: str, qty: int, pos_qty_map: dict[str, int]
) -> Optional[float]:
    """卖出委托占持仓比例。持仓缺失或为 0 时返回 None。"""
    held = pos_qty_map.get(stock_code)
    if held is None or held <= 0:
        return None
    return qty / held


def _to_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))  # 兼容 "1000.0" 这类字符串
    except (TypeError, ValueError):
        return default
