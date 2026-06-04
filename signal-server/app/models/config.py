"""Pydantic DTO：system_config 表的读写模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TimeRange(BaseModel):
    """运行时段的时间范围。"""
    start: str  # HH:MM
    end: str    # HH:MM

    @field_validator("start", "end")
    @classmethod
    def _must_be_hhmm(cls, v: str) -> str:
        v = v.strip()
        parts = v.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("时间格式必须为 HH:MM")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("时间范围无效")
        return f"{h:02d}:{m:02d}"

    @model_validator(mode="after")
    def _start_lt_end(self) -> "TimeRange":
        if self.start >= self.end:
            raise ValueError("开始时间必须早于结束时间")
        return self


class SystemConfigDTO(BaseModel):
    """数据库读出 → 前端展示。"""

    ths_exe_path: str
    use_type_keys: bool
    grid_strategy: Literal["Copy", "Xls", "WMCopy"]
    captcha_mode: Literal["local", "vlm", "auto"] = "local"
    vlm_api_key: str = ""
    captcha_auto_fail_threshold: int = 3
    captcha_vlm_call_count: int = 3
    schedule_enabled: bool = False
    schedule_weekdays: list[int] = []
    schedule_time_ranges: list[TimeRange] = []
    history_entrust_period: Literal["当日", "近一周", "近一月", "近三月", "近一年"] = "当日"
    updated_at: datetime


class SystemConfigUpdate(BaseModel):
    """前端提交 → 写入数据库。"""

    ths_exe_path: str = Field(..., min_length=1)
    use_type_keys: bool = False
    grid_strategy: Literal["Copy", "Xls", "WMCopy"] = "Copy"
    captcha_mode: Literal["local", "vlm", "auto"] = "local"
    vlm_api_key: str = ""
    captcha_auto_fail_threshold: int = Field(3, ge=1, le=10)
    captcha_vlm_call_count: int = Field(3, ge=1, le=10)
    schedule_enabled: bool = False
    schedule_weekdays: list[int] = []
    schedule_time_ranges: list[TimeRange] = []
    history_entrust_period: Literal["当日", "近一周", "近一月", "近三月", "近一年"] = "当日"

    @field_validator("ths_exe_path")
    @classmethod
    def _must_be_xiadan_exe(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized.lower().endswith("xiadan.exe"):
            raise ValueError("路径必须以 xiadan.exe 结尾")
        return normalized


class ConnectionStatus(BaseModel):
    """终端连接运行时状态。"""

    state: Literal["disconnected", "connected", "error"]
    last_error: Optional[str] = None
    last_connect_at: Optional[datetime] = None


class SystemConfigResponse(BaseModel):
    """GET / PUT / POST /api/system/* 统一响应体。"""

    config: SystemConfigDTO
    status: ConnectionStatus
