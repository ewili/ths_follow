"""跟单引擎：后台轮询循环，协调各子服务。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.core.schedule_guard import is_within_schedule
from app.db import repository
from app.models.follow import FollowStatusResponse
from app.services import comparator, order_executor, signal_client
from app.services.local_trader_service import LocalTraderService

logger = logging.getLogger(__name__)


class FollowEngine:
    """进程级单例跟单引擎。"""

    _instance: Optional["FollowEngine"] = None

    _MAX_BACKOFF_S: float = 5.0

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cold_start_align_existing: bool = False
        self._start_time: Optional[datetime] = None
        self._start_timestamp: Optional[datetime] = None
        self._consecutive_failures: int = 0
        self._schedule_paused: bool = False
        self._follow_mode: str = "ratio"
        self._follow_multiplier: float = 1.0

    @classmethod
    def get(cls) -> "FollowEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ── 启停控制 ─────────────────────────────────────────────

    async def start(
        self,
        cold_start_align_existing: bool,
    ) -> FollowStatusResponse:
        if self._running:
            return self.get_status()

        # 读取本地配置的模式和倍数
        cfg = repository.load_config()
        self._follow_mode = cfg.follow_mode
        self._follow_multiplier = cfg.follow_multiplier

        # 校验喊单端模式一致性
        try:
            signal_mode = await signal_client.fetch_signal_mode(cfg.signal_server_url)
        except Exception as exc:
            logger.error("mode_check_failed detail=%s", exc, exc_info=True)
            raise ValueError(f"无法获取喊单端模式，请检查网络连接: {exc}") from exc

        if signal_mode != self._follow_mode:
            mode_labels = {"ratio": "资金比例", "multiplier": "倍数"}
            raise ValueError(
                f"跟单端模式({mode_labels.get(self._follow_mode, self._follow_mode)})"
                f"与喊单端模式({mode_labels.get(signal_mode, signal_mode)})不匹配，"
                f"请切换为一致的模式"
            )

        self._cold_start_align_existing = cold_start_align_existing
        self._start_time = datetime.utcnow()
        self._start_timestamp = None if cold_start_align_existing else self._start_time
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="follow_engine_loop")

        logger.info(
            "event=follow_engine_start cold_start_align=%s follow_mode=%s follow_multiplier=%.1f",
            cold_start_align_existing, self._follow_mode, self._follow_multiplier,
        )
        return self.get_status()

    async def stop(self) -> FollowStatusResponse:
        if not self._running:
            return self.get_status()

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("event=follow_engine_stop")
        return self.get_status()

    def get_status(self) -> FollowStatusResponse:
        return FollowStatusResponse(
            running=self._running,
            cold_start_align_existing=self._cold_start_align_existing if self._running else None,
            start_time=self._start_time if self._running else None,
            follow_mode=self._follow_mode if self._running else repository.load_config().follow_mode,
            follow_multiplier=self._follow_multiplier if self._running else repository.load_config().follow_multiplier,
        )

    # ── 轮询核心 ─────────────────────────────────────────────

    async def _loop(self) -> None:
        cfg = repository.load_config()
        poll_interval_s = cfg.poll_interval_ms / 1000.0
        signal_url = cfg.signal_server_url
        trader = LocalTraderService.get()

        logger.info(
            "event=follow_loop_enter poll_interval_ms=%d signal_url=%s schedule_enabled=%s",
            cfg.poll_interval_ms, signal_url, cfg.schedule_enabled,
        )

        while self._running:
            # 时段控制：不在运行时段时暂停轮询
            cfg = repository.load_config()
            if cfg.schedule_enabled:
                time_ranges_dicts = [tr.model_dump() for tr in cfg.schedule_time_ranges]
                if not is_within_schedule(cfg.schedule_weekdays, time_ranges_dicts):
                    if not self._schedule_paused:
                        self._schedule_paused = True
                        logger.info(
                            "event=schedule_paused weekdays=%s time_ranges=%s",
                            cfg.schedule_weekdays, time_ranges_dicts,
                        )
                    await asyncio.sleep(30)
                    continue
                elif self._schedule_paused:
                    self._schedule_paused = False
                    logger.info("event=schedule_resumed")

            try:
                ok = await self._one_round(trader, signal_url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                ok = False
                logger.error("follow_loop_error detail=%s", exc, exc_info=True)

            if ok:
                self._consecutive_failures = 0
                await asyncio.sleep(poll_interval_s)
            else:
                self._consecutive_failures += 1
                backoff = min(
                    poll_interval_s * 2 ** (self._consecutive_failures - 1),
                    self._MAX_BACKOFF_S,
                )
                logger.debug(
                    "follow_backoff failures=%d sleep=%.1fs",
                    self._consecutive_failures, backoff,
                )
                await asyncio.sleep(backoff)

    async def _one_round(self, trader: LocalTraderService, signal_url: str) -> bool:
        """单轮轮询。返回 True 表示正常推进，False 表示跳过/失败。"""
        if not trader.is_connected:
            logger.warning("follow_round skip: local trader not connected")
            return False

        # 0. 模式一致性校验（每轮检查）
        cfg = repository.load_config()
        try:
            signal_mode = await signal_client.fetch_signal_mode(signal_url)
            if signal_mode != self._follow_mode:
                mode_labels = {"ratio": "资金比例", "multiplier": "倍数"}
                logger.error(
                    "mode_mismatch local=%s signal=%s, auto stopping",
                    self._follow_mode, signal_mode,
                )
                await self.stop()
                return False
        except Exception as exc:
            # 网络临时异常，不停止引擎，等下一轮重试
            logger.warning("mode_check_transient_error detail=%s", exc)

        # 1. 拉取喊单委托（根据 entrust_source 配置切换数据源）
        try:
            if cfg.entrust_source == "history":
                signal_entrusts, _ = await signal_client.fetch_signal_history_entrusts(
                    signal_url, cfg.history_entrust_period
                )
            else:
                signal_entrusts, _ = await signal_client.fetch_signal_entrusts(signal_url)
        except Exception as exc:
            exc_str = str(exc).lower()
            exc_type = type(exc).__name__
            exc_repr = f"{exc_type}({exc!r})"
            if "setforegroundwindow" in exc_str or "sendinput" in exc_str or "409" in str(exc):
                # 临时性窗口焦点错误，下一轮自动重试
                logger.info("signal_fetch_transient type=%s detail=%s", exc_type, exc_repr)
            else:
                logger.warning("signal_fetch_failed type=%s detail=%s", exc_type, exc_repr, exc_info=True)
            return False

        if not signal_entrusts:
            return True

        # 2. 拉取本地数据（倍数模式下不拉 balance）
        try:
            if self._follow_mode == "multiplier":
                # 倍数模式：仅拉持仓和委托（卖出需可用持仓），不拉资金
                local_positions, local_entrusts, _ = (
                    await trader.get_follow_snapshot()
                )
                local_balance_dict = {}
            else:
                local_positions, local_entrusts, local_balance_dict = (
                    await trader.get_follow_snapshot()
                )
            local_positions = local_positions or []
            local_entrusts = local_entrusts or []
            local_balance_dict = local_balance_dict or {}
        except Exception as exc:
            exc_str = str(exc).lower()
            exc_type = type(exc).__name__
            exc_repr = f"{exc_type}({exc!r})"
            if "setforegroundwindow" in exc_str or "sendinput" in exc_str:
                # 临时性窗口焦点错误，下一轮自动重试
                logger.info("local_data_fetch_transient type=%s detail=%s", exc_type, exc_repr)
            else:
                logger.warning("local_data_fetch_failed type=%s detail=%s", exc_type, exc_repr, exc_info=True)
            return False

        total_assets = float(local_balance_dict.get("总资产", local_balance_dict.get("total_assets", 0.0)) or 0.0)

        # 3. 对比决策
        actions = comparator.compare_and_decide(
            signal_entrusts=signal_entrusts,
            local_positions=local_positions,
            local_entrusts=local_entrusts,
            has_followed=repository.has_followed,
            start_timestamp=self._start_timestamp,
            follow_mode=self._follow_mode,
            follow_multiplier=self._follow_multiplier,
        )

        if not actions:
            return True

        # 4. 执行（cancel 优先）
        cancel_actions = [a for a in actions if a.action == "cancel"]
        other_actions = [a for a in actions if a.action != "cancel"]

        for act in cancel_actions:
            await order_executor.execute_cancel(act)

        pos_map: dict[str, int] = {}
        for p in local_positions:
            code = str(p.get("证券代码", p.get("stock_code", ""))).strip()
            avail = int(p.get("股份可用", p.get("可用余额", p.get("available_qty", 0))) or 0)
            if code:
                pos_map[code] = avail

        for act in other_actions:
            if act.action == "buy":
                await order_executor.execute_buy(act, total_assets)
            elif act.action == "sell":
                available = pos_map.get(act.stock_code, 0)
                await order_executor.execute_sell(act, available)

        return True
