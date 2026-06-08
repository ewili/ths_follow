"""本地同花顺终端服务：easytrader 单例管理 + asyncio.Lock 串行化。

结构参照 signal_server/app/services/trader_service.py，
但额外暴露 buy / sell / cancel_entrust 下单方法。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

_TTL_SECONDS = 1.0

easytrader = None
grid_strategies = None


def _ensure_easytrader():
    global easytrader, grid_strategies
    if easytrader is None:
        try:
            import app.utils.easytrader_copy_patch  # noqa: F401 — 须在 easytrader 前加载补丁
            import easytrader as _et
            from easytrader import grid_strategies as _gs
            easytrader = _et
            grid_strategies = _gs
        except ImportError as e:
            raise ImportError("easytrader 未安装，请运行: pip install easytrader") from e
    return easytrader, grid_strategies


def _get_grid_strategy(name: str):
    _, gs = _ensure_easytrader()
    mapping = {"Copy": gs.Copy, "Xls": gs.Xls, "WMCopy": gs.WMCopy}
    cls = mapping.get(name)
    if cls is None:
        raise ValueError(f"不支持的 grid_strategy: {name}")
    return cls


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


class LocalTraderService:
    """跟单端本地 easytrader 单例。"""

    _instance: Optional["LocalTraderService"] = None

    def __init__(self) -> None:
        self._trader: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._last_error: Optional[str] = None
        self._last_connect_at: Optional[datetime] = None
        self._cache: Dict[str, Tuple[float, Any]] = {}

    @classmethod
    def get(cls) -> "LocalTraderService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ── 状态 ────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "state": self._state.value,
            "last_error": self._last_error,
            "last_connect_at": self._last_connect_at.isoformat() if self._last_connect_at else None,
        }

    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._trader is not None

    # ── 串行化 GUI 调用 ──────────────────────────────────────

    def _bring_to_foreground(self) -> None:
        """尝试将同花顺主窗口置前，减少 SetForegroundWindow / SendInput 失败概率。

        在锁内调用，线程安全。失败时仅写日志，不阻断后续操作。
        使用 AttachThreadInput + 重试机制增强可靠性。

        注意：不再在此处自动处理验证码弹窗。验证码由 easytrader_copy_patch
        在 Copy 策略层透明处理，避免健康检查等场景陷入验证码死循环阻塞全局锁。
        """
        if self._trader is None:
            return

        # 尝试将主窗口置前（带重试 + AttachThreadInput 辅助）
        for attempt in range(3):
            try:
                main_win = self._trader._main
                if main_win is not None:
                    from pywinauto import win32defines
                    from pywinauto.win32functions import SetForegroundWindow, ShowWindow
                    wrapper = main_win.wrapper_object()
                    if main_win.has_style(win32defines.WS_MINIMIZE):
                        ShowWindow(wrapper, 9)  # SW_RESTORE
                        time.sleep(0.05)

                    # AttachThreadInput：将当前线程附加到前台线程，
                    # 绕过 Windows 的 SetForegroundWindow 前台锁限制
                    try:
                        import ctypes
                        import win32gui
                        import win32process
                        fg_hwnd = win32gui.GetForegroundWindow()
                        fg_tid, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
                        cur_tid, cur_pid = win32process.GetWindowThreadProcessId(wrapper.handle)
                        if fg_pid != cur_pid:
                            if fg_tid and cur_tid and fg_tid != cur_tid:
                                ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, True)
                                SetForegroundWindow(wrapper)
                                ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, False)
                            else:
                                SetForegroundWindow(wrapper)
                        else:
                            SetForegroundWindow(wrapper)
                    except Exception:
                        SetForegroundWindow(wrapper)

                    time.sleep(0.05)
                    # 验证是否成功置前
                    try:
                        import win32gui
                        current_fg = win32gui.GetForegroundWindow()
                        if current_fg == wrapper.handle:
                            if attempt > 0:
                                logger.info("bring_to_foreground_ok attempt=%d", attempt + 1)
                            return
                    except Exception:
                        pass
            except Exception:
                pass
            if attempt < 2:
                time.sleep(0.1)
        logger.info("bring_to_foreground_failed_after_retries")

    async def _run_blocking(self, fn: Callable[[], T], op_name: str) -> T:
        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        async with self._lock:
            # 下单类操作需要窗口在前台
            # health_probe 不需要置前：仅检查窗口句柄是否存在，无需 GUI 交互
            if op_name in (
                "buy", "sell", "cancel_entrust", "position", "today_entrusts",
                "balance", "follow_snapshot", "history_entrusts",
            ):
                await loop.run_in_executor(None, self._bring_to_foreground)
            result = await loop.run_in_executor(None, fn)
        elapsed = (time.perf_counter() - t0) * 1000
        logger.debug("local_trader op=%s elapsed_ms=%.1f", op_name, elapsed)
        return result

    async def _cached(self, key: str, fn: Callable[[], T], op_name: str) -> T:
        """TTL=1s 缓存层，减少 GUI 调用次数。"""
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
        value = await self._run_blocking(fn, op_name)
        self._cache[key] = (now + _TTL_SECONDS, value)
        return value

    def _invalidate_cache(self) -> None:
        self._cache.clear()

    def _cache_valid_key(self, key: str) -> bool:
        cached = self._cache.get(key)
        return cached is not None and cached[0] > time.monotonic()

    async def get_follow_snapshot(
        self,
        include_balance: bool = True,
    ) -> tuple[list[dict], list[dict], dict]:
        """单次锁内拉取持仓 + 当日委托（+可选资金），减少复制触发的验证码次数。

        返回 (positions, today_entrusts, balance)。
        include_balance=False 时跳过资金数据缓存，仍读持仓（卖出需可用股数）。
        """
        if self._is_schedule_paused():
            return [], [], {}
        self._require_trader()

        cache_keys = ("position", "entrusts", "balance") if include_balance else ("position", "entrusts")
        if all(self._cache_valid_key(k) for k in cache_keys):
            positions = self._cache["position"][1]
            entrusts = self._cache["entrusts"][1]
            balance = self._cache["balance"][1] if include_balance and self._cache_valid_key("balance") else {}
            return positions, entrusts, balance

        if include_balance:
            def _snapshot() -> tuple[list[dict], list[dict], dict]:
                from app.utils.ths_gui_fetch import fetch_funds_stock, fetch_today_entrusts

                balance, positions = fetch_funds_stock(self._trader)
                entrusts = fetch_today_entrusts(self._trader)
                return positions, entrusts, balance
        else:
            def _snapshot() -> tuple[list[dict], list[dict], dict]:
                from app.utils.ths_gui_fetch import fetch_funds_stock, fetch_today_entrusts

                _, positions = fetch_funds_stock(self._trader)
                entrusts = fetch_today_entrusts(self._trader)
                return positions, entrusts, {}

        positions, entrusts, balance = await self._run_blocking(
            _snapshot, "follow_snapshot"
        )
        expires = time.monotonic() + _TTL_SECONDS
        if include_balance and balance:
            self._cache["balance"] = (expires, balance)
        self._cache["position"] = (expires, positions)
        self._cache["entrusts"] = (expires, entrusts)
        logger.info(
            "event=local_follow_snapshot include_balance=%s cached position=%d entrusts=%d",
            include_balance, len(positions), len(entrusts),
        )
        return positions, entrusts, balance

    # ── 连接管理 ─────────────────────────────────────────────

    async def connect(
        self,
        exe_path: str,
        use_type_keys: bool,
        grid_strategy: str,
    ) -> dict:
        def _do() -> None:
            et, _ = _ensure_easytrader()
            trader = et.use("ths")
            if use_type_keys:
                trader.enable_type_keys_for_editor()
            trader.grid_strategy = _get_grid_strategy(grid_strategy)
            trader.connect(exe_path)
            self._trader = trader

        try:
            await self._run_blocking(_do, "connect")
            self._state = ConnectionState.CONNECTED
            self._last_error = None
            self._last_connect_at = datetime.utcnow()
            self._invalidate_cache()
            logger.info("event=local_trader_connect_ok path=%s", exe_path)
        except Exception as exc:
            self._trader = None
            self._state = ConnectionState.ERROR
            self._last_error = str(exc)
            logger.error("event=local_trader_connect_failed detail=%s", exc, exc_info=True)
            raise
        return self.get_status()

    async def disconnect(self) -> None:
        async with self._lock:
            self._trader = None
            self._state = ConnectionState.DISCONNECTED
            self._last_error = None
            self._invalidate_cache()
        logger.info("event=local_trader_disconnect")

    async def health_probe(self) -> dict:
        if self._trader is None:
            return self.get_status()

        def _probe() -> bool:
            try:
                return self._trader._main.exists()
            except Exception:
                return False

        healthy = await self._run_blocking(_probe, "health_probe")
        if not healthy:
            self._trader = None
            self._state = ConnectionState.ERROR
            self._last_error = "终端窗口失联（标题校验失败）"
            self._invalidate_cache()
            logger.warning("event=local_trader_health_fail")
        return self.get_status()

    # ── 时段守卫 ────────────────────────────────────────

    def _is_schedule_paused(self) -> bool:
        """时段控制启用且不在运行时段时返回 True。"""
        from app.core.schedule_guard import is_within_schedule
        from app.db import repository
        cfg = repository.load_config()
        if cfg.schedule_enabled:
            time_ranges_dicts = [tr.model_dump() for tr in cfg.schedule_time_ranges]
            if not is_within_schedule(cfg.schedule_weekdays, time_ranges_dicts):
                return True
        return False

    # ── 查询（带 TTL 缓存） ───────────────────────────────────

    def _require_trader(self):
        if self._trader is None:
            raise RuntimeError("本地同花顺终端未连接")

    async def get_positions(self) -> list[dict]:
        if self._is_schedule_paused():
            logger.info("positions_skipped_schedule_paused")
            return []
        self._require_trader()
        return await self._cached(
            "position",
            lambda: self._trader.position,
            "position",
        )

    async def get_today_entrusts(self) -> list[dict]:
        if self._is_schedule_paused():
            logger.info("entrusts_skipped_schedule_paused")
            return []
        self._require_trader()
        return await self._cached(
            "entrusts",
            lambda: self._trader.today_entrusts,
            "today_entrusts",
        )

    async def get_history_entrusts(self, period: str) -> list[dict]:
        if self._is_schedule_paused():
            logger.info("history_entrusts_skipped_schedule_paused")
            return []
        self._require_trader()

        def _fetch() -> list[dict]:
            from app.utils.ths_gui_fetch import fetch_history_entrusts

            return fetch_history_entrusts(self._trader, period)

        return await self._cached(
            f"history_{period}",
            _fetch,
            "history_entrusts",
        )

    async def get_balance(self) -> dict:
        if self._is_schedule_paused():
            logger.info("balance_skipped_schedule_paused")
            return {}
        self._require_trader()
        return await self._cached(
            "balance",
            lambda: self._trader.balance,
            "balance",
        )

    # ── 下单（不走缓存，每次实际 GUI 操作）────────────────────

    async def buy(self, stock_code: str, price: float, amount: int) -> dict:
        """买入，返回 {'entrust_no': 'xxx'} 或抛 TradeError。"""
        self._require_trader()
        self._invalidate_cache()
        return await self._run_blocking(
            lambda: self._trader.buy(stock_code, price, amount),
            "buy",
        )

    async def sell(self, stock_code: str, price: float, amount: int) -> dict:
        """卖出，返回 {'entrust_no': 'xxx'} 或抛 TradeError。"""
        self._require_trader()
        self._invalidate_cache()
        return await self._run_blocking(
            lambda: self._trader.sell(stock_code, price, amount),
            "sell",
        )

    async def cancel_entrust(self, entrust_no: str) -> dict:
        """撤单（按合同编号），返回消息字典。"""
        self._require_trader()
        self._invalidate_cache()
        return await self._run_blocking(
            lambda: self._trader.cancel_entrust(entrust_no),
            "cancel_entrust",
        )
