"""喊单运行态管理。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from app.core.schedule_guard import is_within_schedule
from app.db import repository
from app.models.system_status import SignalModeResponse, SignalRuntimeStatus


class SignalRuntimeService:
    """仅负责喊单启停状态，不承载业务查询。"""

    _instance: Optional["SignalRuntimeService"] = None

    def __init__(self) -> None:
        self._state = "stopped"
        self._started_at: Optional[datetime] = None
        self._last_changed_at: Optional[datetime] = None
        self._signal_mode: Literal["ratio", "multiplier"] = "ratio"

    @classmethod
    def get(cls) -> "SignalRuntimeService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def get_status(self) -> SignalRuntimeStatus:
        schedule_active = True
        cfg = None
        if self._state == "running":
            cfg = repository.load_config()
            if cfg.schedule_enabled:
                time_ranges_dicts = [tr.model_dump() for tr in cfg.schedule_time_ranges]
                schedule_active = is_within_schedule(cfg.schedule_weekdays, time_ranges_dicts)
        # 未运行时从配置读取 signal_mode，与 get_mode() 行为一致
        if self._state == "running":
            effective_mode = self._signal_mode
        else:
            if cfg is None:
                cfg = repository.load_config()
            effective_mode = cfg.signal_mode
        return SignalRuntimeStatus(
            state=self._state,
            started_at=self._started_at,
            last_changed_at=self._last_changed_at,
            schedule_active=schedule_active,
            signal_mode=effective_mode,
        )

    def start(self, signal_mode: Literal["ratio", "multiplier"] | None = None) -> SignalRuntimeStatus:
        now = datetime.utcnow()
        if self._state != "running":
            # 优先使用调用方传入的模式；未指定时从数据库配置读取
            if signal_mode is None:
                cfg = repository.load_config()
                signal_mode = cfg.signal_mode
            self._state = "running"
            self._signal_mode = signal_mode
            self._started_at = now
            self._last_changed_at = now
        return self.get_status()

    def get_mode(self) -> SignalModeResponse:
        """返回当前喊单模式（优先内存态，未运行时从配置读取）。"""
        if self._state == "running":
            return SignalModeResponse(signal_mode=self._signal_mode)
        cfg = repository.load_config()
        return SignalModeResponse(signal_mode=cfg.signal_mode)

    def stop(self) -> SignalRuntimeStatus:
        now = datetime.utcnow()
        if self._state != "stopped":
            self._state = "stopped"
            self._last_changed_at = now
        return self.get_status()
