"""TraderService：easytrader 单例管理 + asyncio.Lock 串行化。"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from app.models.config import ConnectionStatus
from app.models.errors import ThsConnectError, THS_NOT_LOGGED_IN, THS_NOT_FOUND, map_exception_message
from app.services.runtime_metrics_service import RuntimeMetricsService

logger = logging.getLogger(__name__)
T = TypeVar("T")

# easytrader 延迟导入（可选依赖）
easytrader = None
grid_strategies = None

def _ensure_easytrader():
    """确保 easytrader 已导入。"""
    global easytrader, grid_strategies
    if easytrader is None:
        try:
            import app.utils.easytrader_copy_patch  # noqa: F401 — 须在 easytrader 前加载补丁
            import easytrader as _easytrader
            from easytrader import grid_strategies as _grid_strategies
            easytrader = _easytrader
            grid_strategies = _grid_strategies
        except ImportError as e:
            raise ImportError(
                "easytrader 未安装，请运行: pip install easytrader"
            ) from e
    return easytrader, grid_strategies


# ── grid_strategy 字符串 → 类映射 ────────────────────────────

def _get_grid_strategy_map() -> Dict[str, type]:
    _, gs = _ensure_easytrader()
    return {
        "Copy": gs.Copy,
        "Xls": gs.Xls,
        "WMCopy": gs.WMCopy,
    }


def _resolve_grid_strategy(name: str) -> type:
    cls = _get_grid_strategy_map().get(name)
    if cls is None:
        raise ValueError(f"不支持的 grid_strategy: {name}")
    return cls


# ── 连接状态枚举 ────────────────────────────────────────────

class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


# ── 核心服务 ────────────────────────────────────────────────

class TraderService:
    """easytrader.ClientTrader 的进程级单例包装。"""

    _instance: Optional[TraderService] = None

    def __init__(self) -> None:
        self._trader: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._last_error: Optional[str] = None
        self._last_connect_at: Optional[datetime] = None
        # 预留缓存挂载点，US-003 使用
        self._cache_ttl_seconds: float = 1.0
        self._cache: Dict[str, Tuple[float, Any]] = {}

    @classmethod
    def get(cls) -> TraderService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """仅供测试使用：销毁单例。"""
        cls._instance = None

    # ── 公开属性 ────────────────────────────────────────

    def get_status(self) -> ConnectionStatus:
        """纯内存读，不触碰 GUI。"""
        return ConnectionStatus(
            state=self._state.value,
            last_error=self._last_error,
            last_connect_at=self._last_connect_at,
        )

    @property
    def trader(self) -> Optional[Any]:
        return self._trader

    # ── 主动置前 ────────────────────────────────────────

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
            if should_skip_foreground_captcha():
                captcha_dlg = None
            else:
                captcha_dlg = _quick_check_captcha(self._trader)
            if captcha_dlg is not None:
                logger.info("bring_to_foreground: captcha dialog detected, handling first")
                self._handle_captcha_dialog(captcha_dlg)
                captcha_handled = True
        except Exception:
            logger.debug("bring_to_foreground_captcha_check_failed", exc_info=True)

        # 验证码处理成功后，等待窗口焦点恢复
        if captcha_handled:
            _time.sleep(0.3)

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
                        _time.sleep(0.05)

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

                    _time.sleep(0.05)
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
                _time.sleep(0.1)
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
                # 先清空输入框，防止多轮尝试时字符叠加
                try:
                    editor.type_keys("^a{BACKSPACE}", set_foreground=False)
                    trader.wait(0.1)
                except Exception:
                    pass
                trader.type_edit_control_keys(editor, captcha_try)
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

    # ── 并发包装 ────────────────────────────────────────

    async def _run_blocking(self, fn: Callable[[], T], op_name: str) -> T:
        loop = asyncio.get_running_loop()
        wait_started = _time.perf_counter()
        async with self._lock:
            # GUI 操作前主动将同花顺窗口置前（connect 阶段 trader 尚未赋值，跳过）
            if op_name in ("balance", "position", "entrusts", "buy", "sell", "cancel_entrust", "health_probe"):
                await loop.run_in_executor(None, self._bring_to_foreground)
            lock_wait_ms = (_time.perf_counter() - wait_started) * 1000
            t0 = _time.perf_counter()
            result = await loop.run_in_executor(None, fn)
            gui_elapsed_ms = (_time.perf_counter() - t0) * 1000
        RuntimeMetricsService.get().record_gui_call(
            operation=op_name,
            gui_elapsed_ms=gui_elapsed_ms,
            lock_wait_ms=lock_wait_ms,
        )
        logger.debug(
            "operation=%s gui_elapsed_ms=%.1f lock_wait_ms=%.1f",
            op_name,
            gui_elapsed_ms,
            lock_wait_ms,
        )
        return result

    # ── connect ─────────────────────────────────────────

    async def connect(
        self,
        exe_path: str,
        use_type_keys: bool,
        grid_strategy: str,
    ) -> ConnectionStatus:
        def _do_connect() -> None:
            et, _ = _ensure_easytrader()
            trader = et.use("ths")
            if use_type_keys:
                trader.enable_type_keys_for_editor()
            trader.grid_strategy = _resolve_grid_strategy(grid_strategy)
            trader.connect(exe_path)
            self._trader = trader

        try:
            t0 = _time.perf_counter()
            await self._run_blocking(_do_connect, op_name="connect")
            elapsed = (_time.perf_counter() - t0) * 1000
            self._state = ConnectionState.CONNECTED
            self._last_error = None
            self._last_connect_at = datetime.utcnow()
            logger.info(
                "event=ths_connect_ok path=%s elapsed_ms=%.0f",
                exe_path,
                elapsed,
            )
            # 连接成功后自动尝试采集股票行情数据（后台异步，不阻塞）
            self._auto_fetch_stock_data()
            # TODO(US-009): operation_log.write(category="ths_connect", ...)
            return self.get_status()
        except Exception as exc:
            self._trader = None
            self._state = ConnectionState.ERROR
            self._last_error = map_exception_message(exc)
            logger.error(
                "event=ths_connect_failed detail=%s", exc, exc_info=True
            )
            # TODO(US-009): operation_log.write(category="ths_connect_failed", ...)
            raise ThsConnectError.from_exception(exc) from exc

    # ── disconnect ──────────────────────────────────────

    async def disconnect(self) -> None:
        async with self._lock:
            self._trader = None
            self._state = ConnectionState.DISCONNECTED
            self._last_error = None
            self._cache.clear()
        logger.info("event=ths_disconnect")
        # TODO(US-009): operation_log.write(category="ths_disconnect", ...)

    # ── health_probe ────────────────────────────────────

    async def health_probe(self) -> ConnectionStatus:
        if self._trader is None:
            return self.get_status()

        def _probe() -> bool:
            try:
                return self._trader._main.exists()
            except Exception:
                return False

        healthy = await self._run_blocking(_probe, op_name="health_probe")
        if not healthy:
            self._trader = None
            self._state = ConnectionState.ERROR
            self._last_error = "终端窗口失联（标题校验失败）"
            self._cache.clear()
            logger.warning("event=ths_health_fail reason=title_mismatch")
        return self.get_status()

    # ── with_lock（供 US-003 下游模块复用） ──────────────

    async def with_lock(
        self,
        fn: Callable[..., T],
        op_name: str = "unknown",
    ) -> T:
        """获取锁后在线程池中执行 fn(self._trader)。

        验证码由 easytrader_copy_patch 在 Copy 策略层透明处理，此处无需额外检查。

        Args:
            fn: 要执行的函数，接收 trader 作为参数
            op_name: 操作名称，用于日志和指标

        Returns:
            fn 的返回值

        Raises:
            ThsConnectError: 终端未连接或操作失败
        """
        if self._trader is None:
            raise ThsConnectError(
                status_code=409,
                code=THS_NOT_LOGGED_IN,
                message="终端未连接，请先连接同花顺终端",
            )

        def _wrapped() -> T:
            return fn(self._trader)

        try:
            return await self._run_blocking(_wrapped, op_name=op_name)
        except ThsConnectError:
            raise
        except Exception as exc:
            mapped = ThsConnectError.from_exception(exc)
            if mapped.detail["code"] in (THS_NOT_LOGGED_IN, THS_NOT_FOUND):
                self._trader = None
                self._state = ConnectionState.ERROR
                self._last_error = mapped.detail["message"]
                self._cache.clear()
                RuntimeMetricsService.get().record_dialog()
                logger.warning(
                    "event=ths_connection_lost code=%s, 已清空连接对象，请通过 Web 界面重新连接",
                    mapped.detail["code"]
                )
            raise mapped from exc

    async def get_history_entrusts(self, period: str) -> list[dict]:
        """查询历史委托（支持周期选择）。"""
        if self._trader is None:
            raise ThsConnectError(
                status_code=409,
                code=THS_NOT_LOGGED_IN,
                message="终端未连接，请先连接同花顺终端",
            )

        def _fetch(trader) -> list[dict]:
            trader._switch_left_menus(["查询[F4]", "历史委托"])
            try:
                main_win = trader._main
                btn = main_win.child_window(title=period, class_name="Button")
                if btn.exists():
                    btn.click()
                    trader.wait(0.5)
                else:
                    logger.warning("历史委托周期按钮 %s 未找到，可能已默认选中", period)
            except Exception as e:
                logger.warning("历史委托周期按钮 %s 点击失败: %s", period, e)
            return trader._get_grid_data(trader._config.COMMON_GRID_CONTROL_ID)

        return await self.with_lock(_fetch, op_name="history_entrusts")

    def _auto_fetch_stock_data(self) -> None:
        """连接成功后自动尝试采集股票行情数据（后台异步，不阻塞连接流程）。

        盘中（工作日 15:00 前）跳过，周末/收盘后执行。
        采集失败不影响连接状态，仅写日志。
        """
        from app.db import stock_repository as _stock_repo

        # 如果 stock_limit_prices 表已有数据，跳过自动采集
        latest = _stock_repo.get_latest_trade_date()
        if latest is not None:
            logger.info("event=auto_fetch_skip stock_limit_prices 已有数据 trade_date=%s", latest)
            return

        # 检查是否允许采集（盘中实时价不准确）
        now = datetime.now()
        weekday = now.weekday()
        if weekday < 5:
            hour_min = now.hour * 100 + now.minute
            if hour_min < 1500:
                logger.info(
                    "event=auto_fetch_skip 盘中暂不自动采集（15:00 后或周末自动触发），"
                    "可手动通过 POST /api/stock/fetch 触发"
                )
                return

        async def _do_fetch() -> None:
            try:
                from app.services.stock_data_service import fetch_and_save
                result = await asyncio.to_thread(fetch_and_save)
                if result["success"]:
                    logger.info(
                        "event=auto_fetch_ok trade_date=%s count=%d",
                        result["trade_date"], result["count"],
                    )
                else:
                    logger.warning("event=auto_fetch_failed message=%s", result["message"])
            except Exception:
                logger.exception("event=auto_fetch_exception 自动采集股票行情异常")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_do_fetch())
            logger.info("event=auto_fetch_triggered stock_limit_prices 表为空，已启动后台采集")
        except RuntimeError:
            logger.warning("event=auto_fetch_no_loop 无法获取事件循环，跳过自动采集")
