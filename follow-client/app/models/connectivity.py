"""喊单端连通性探测模型。"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_validator

from app.models.config import validate_signal_server_url


class SignalServerConnectivityCheck(BaseModel):
    """前端提交的连通性探测参数。"""

    signal_server_url: str

    @field_validator("signal_server_url")
    @classmethod
    def _validate_signal_server_url(cls, value: str) -> str:
        return validate_signal_server_url(value)

    def normalized_url(self) -> str:
        return self.signal_server_url


class SignalServerConnectivityResult(BaseModel):
    """喊单端轻量探测结果。"""

    ok: bool
    checked_url: str
    message: str
    status_code: Optional[int] = None
