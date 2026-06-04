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
        若检测到验证码弹窗，先处理验证码再置前主窗口。
        使用 AttachThreadInput + 重试机制增强可靠性。
        """
        if self._trader is None:
            return
        # 验证码弹窗预处理：模态弹窗会阻塞 SetForegroundWindow
        captcha_handled = False
        try:
            from app.utils.easytrader_copy_patch import (
                _quick_check_captcha,
                should_skip_foreground_captcha,
            )
            if should_skip_foreground_captcha(self._trader):
                captcha_dlg = None
            else:
                captcha_dlg = _quick_check_captcha(self._trader)
                if captcha_dlg is None:
                    from app.utils.easytrader_copy_patch import _find_captcha_dialog
                    captcha_dlg = _find_captcha_dialog(self._trader, timeout=0.5)
            if captcha_dlg is not None:
                logger.info("bring_to_foreground: captcha dialog detected, handling first")
                self._handle_captcha_dialog(captcha_dlg)
                captcha_handled = True
        except Exception:
            logger.debug("bring_to_foreground_captcha_check_failed", exc_info=True)

        # 验证码处理成功后，等待窗口焦点恢复
        if captcha_handled:
            time.sleep(0.3)

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
                        if fg_hwnd and fg_hwnd != wrapper.handle:
                            _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
                            _, cur_pid = win32process.GetWindowThreadProcessId(wrapper.handle)
                            if fg_pid != cur_pid:
                                fg_tid = ctypes.windll.kernel32.GetThreadId(ctypes.windll.kernel32.OpenThread(0x1FFFFF, False, fg_pid))
                                cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
                                if fg_tid and cur_tid and fg_tid != cur_tid:
                                    ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, True)
                                    SetForegroundWindow(wrapper)
                                    ctypes.windll.user32.AttachThreadInput(cur_tid, fg_tid, False)
                                else:
                                    SetForegroundWindow(wrapper)
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

    def _handle_captcha_dialog(self, dlg_wrapper) -> None:
        """处理验证码弹窗：截图识别 → 输入 → 点击确定。

        在锁内调用，线程安全。失败仅写日志，不抛异常。
        每轮重新截图识别（THS 输入错误后可能自动刷新图片），
        最多 8 轮，每轮只输入 1 个最佳结果。
        """
        from easytrader.grid_strategies import Copy
        from app.utils.easytrader_copy_patch import (
            _find_captcha_dialog,
            _captcha_recognize,
            _CAPTCHA_IMG_PATH,
            _log,
            mark_captcha_cooldown,
        )
        from app.db import repository
        _cfg = repository.load_config()
        _captcha_mode = _cfg.captcha_mode
        _vlm_api_key = _cfg.vlm_api_key
        _captcha_auto_fail_threshold = _cfg.captcha_auto_fail_threshold
        _captcha_vlm_call_count = _cfg.captcha_vlm_call_count
        trader = self._trader
        if trader is None:
            return
        # 每轮截图识别后，在同一轮内循环试所有大小写变体
        # 全部失败后刷新图片，再进入下一轮
        for attempt in range(8):
            if attempt > 0:
                dlg_wrapper = _find_captcha_dialog(trader, timeout=1.0)
                if dlg_wrapper is None:
                    _log(logging.INFO, "captcha dialog gone after attempt %d", attempt)
                    Copy._need_captcha_reg = False
                    mark_captcha_cooldown()
                    return
            dlg = trader.app.window(handle=dlg_wrapper.handle)
            try:
                dlg.set_focus()
            except Exception:
                pass
            # 截图识别
            img_ctrl = None
            try:
                img_ctrl = dlg.child_window(control_id=0x965, class_name="Static")
                if not img_ctrl.exists():
                    img_ctrl = None
            except Exception:
                img_ctrl = None
            if img_ctrl is None:
                for child in dlg.children(class_name="Static"):
                    try:
                        if child.is_visible():
                            img_ctrl = child
                            break
                    except Exception:
                        continue
            if img_ctrl is None:
                _log(logging.ERROR, "captcha image control not found (attempt %d)", attempt)
                continue
            try:
                img_ctrl.capture_as_image().save(_CAPTCHA_IMG_PATH)
            except Exception as e:
                _log(logging.ERROR, "captcha capture failed (attempt %d): %s", attempt, e)
                continue
            captcha_num, variants = _captcha_recognize(
                _CAPTCHA_IMG_PATH,
                mode=_captcha_mode,
                vlm_api_key=_vlm_api_key,
                auto_fail_threshold=_captcha_auto_fail_threshold,
                vlm_call_count=_captcha_vlm_call_count,
            )
            
            _log(logging.INFO, "captcha result-->%s variants=%s (attempt %d)", captcha_num, variants, attempt)
            if len(captcha_num) != 4:
                try:
                    dlg.child_window(control_id=0x965, class_name="Static").click()
                    trader.wait(0.2)
                except Exception:
                    pass
                continue

            # 每轮只试1个变体（避免频繁错误输入导致THS断连）
            # 由于每轮刷新后都是全新的验证码，应始终尝试当前图片概率最高、最准确的第一个变体 (Variant 1)
            captcha_try = variants[0]
            _log(logging.INFO, "captcha trying best variant (attempt %d): %s", attempt+1, captcha_try)

            # 输入验证码
            editor = None
            try:
                editor = dlg.child_window(control_id=0x964, class_name="Edit")
                if not editor.exists():
                    editor = None
            except Exception:
                editor = None
            if editor is None:
                for child in dlg.children(class_name="Edit"):
                    try:
                        if child.is_visible():
                            editor = child
                            break
                    except Exception:
                        continue
            if editor is None:
                _log(logging.ERROR, "captcha edit control not found (attempt %d)", attempt)
                break
            try:
                editor.set_focus()
            except Exception:
                pass
            trader.wait(0.1)
            try:
                # 通过 WM_CHAR 逐字符输入，触发 EN_CHANGE 通知
                # set_edit_text (WM_SETTEXT) 不触发通知，THS 不识别；
                # type_keys 依赖 SetForegroundWindow，模态弹窗下失败
                # 清空策略：EM_SETSEL 全选 + WM_CHAR 逐字符覆盖（第一个字符替换选中内容）
                # 注意：WM_SETTEXT("") 会破坏 THS Edit 控件内部状态，不可使用
                try:
                    hwnd = editor.element_info.handle
                except Exception:
                    hwnd = None
                if hwnd is not None:
                    import win32con
                    import win32gui
                    win32gui.SendMessage(hwnd, win32con.EM_SETSEL, 0, -1)
                    for ch in captcha_try:
                        win32gui.SendMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)
                else:
                    editor.set_edit_text(captcha_try)
            except Exception as e:
                _log(logging.ERROR, "captcha type failed (attempt %d): %s", attempt, e)
                continue
            trader.wait(0.1)
            # 点击确定
            try:
                dlg.child_window(title="确定").click()
            except Exception:
                try:
                    dlg.type_keys("{ENTER}", set_foreground=False, pause=0.1)
                except Exception:
                    pass
            trader.wait(0.5)
            # 验证：对话框消失即成功
            if _find_captcha_dialog(trader, timeout=0.5) is None:
                _log(logging.INFO, "验证码验证成功-->%s (variant %d/%d)", captcha_try, attempt+1, len(variants))
                Copy._need_captcha_reg = False
                mark_captcha_cooldown()
                return
            else:
                _log(logging.WARNING, "captcha still present after input %s (variant %d/%d)", captcha_try, attempt+1, len(variants))

            # 本轮变体失败，点击图片刷新验证码
            _log(logging.INFO, "captcha variant %s failed for %s, clicking image to refresh", captcha_try, captcha_num.upper())
            # 递增等待：1s, 1.5s, 2s, 2.5s... 避免THS判定恶意操作
            wait_time = 1.0 + attempt * 0.5
            trader.wait(wait_time)
            try:
                if img_ctrl is not None:
                    img_ctrl.click()
                    trader.wait(0.5)
                else:
                    dlg.child_window(control_id=0x965, class_name="Static").click()
                    trader.wait(0.5)
            except Exception:
                pass
        # 8 次均失败，不点取消（避免破坏窗口状态），保持弹窗让用户手动处理
        _log(logging.ERROR, "captcha 8 次识别均失败，请手动处理验证码弹窗")

    async def _run_blocking(self, fn: Callable[[], T], op_name: str) -> T:
        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        async with self._lock:
            # 下单类操作需要窗口在前台
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
    ) -> tuple[list[dict], list[dict], dict]:
        """单次锁内拉取资金股票页 + 当日委托，减少复制触发的验证码次数。

        返回 (positions, today_entrusts, balance)。
        """
        if self._is_schedule_paused():
            return [], [], {}
        self._require_trader()

        if all(self._cache_valid_key(k) for k in ("position", "entrusts", "balance")):
            return (
                self._cache["position"][1],
                self._cache["entrusts"][1],
                self._cache["balance"][1],
            )

        def _snapshot() -> tuple[list[dict], list[dict], dict]:
            from app.utils.ths_gui_fetch import fetch_funds_stock, fetch_today_entrusts

            balance, positions = fetch_funds_stock(self._trader)
            entrusts = fetch_today_entrusts(self._trader)
            return positions, entrusts, balance

        positions, entrusts, balance = await self._run_blocking(
            _snapshot, "follow_snapshot"
        )
        expires = time.monotonic() + _TTL_SECONDS
        self._cache["balance"] = (expires, balance)
        self._cache["position"] = (expires, positions)
        self._cache["entrusts"] = (expires, entrusts)
        logger.info("event=local_follow_snapshot cached position=%d entrusts=%d",
                    len(positions), len(entrusts))
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
