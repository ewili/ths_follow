"""Pydantic DTO：follow_config 表的读写模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


def validate_signal_server_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("喊单服务端地址必须以 http:// 或 https:// 开头")
    if not parsed.netloc or parsed.port is None:
        raise ValueError("喊单服务端地址必须包含端口号")
    return normalized.rstrip("/")


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


class FollowConfigDTO(BaseModel):
    """数据库读出 -> 前端展示。"""

    signal_server_url: str
    poll_interval_ms: int
    local_ths_exe_path: str
    cold_start_align_existing: bool
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
    entrust_source: Literal["today", "history"] = "today"
    updated_at: datetime


class FollowConfigUpdate(BaseModel):
    """前端提交 -> 写入数据库。"""

    signal_server_url: str = Field(..., min_length=1)
    poll_interval_ms: int = Field(..., ge=100, le=5000)
    local_ths_exe_path: str = Field(..., min_length=1)
    cold_start_align_existing: bool = False
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
    entrust_source: Literal["today", "history"] = "today"

    @field_validator("signal_server_url")
    @classmethod
    def _validate_signal_server_url(cls, v: str) -> str:
        return validate_signal_server_url(v)

    @field_validator("local_ths_exe_path")
    @classmethod
    def _must_be_xiadan_exe(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized.lower().endswith("xiadan.exe"):
            raise ValueError("路径必须以 xiadan.exe 结尾")
        return normalized
