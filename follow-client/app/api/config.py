"""跟单端配置管理 API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.db import repository
from app.models.connectivity import (
    SignalServerConnectivityCheck,
    SignalServerConnectivityResult,
)
from app.models.config import FollowConfigDTO, FollowConfigUpdate
from app.services.connectivity import probe_signal_server

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=FollowConfigDTO)
async def get_config() -> FollowConfigDTO:
    """返回当前已保存的跟单配置。"""
    return repository.load_config()


@router.put("/config", response_model=FollowConfigDTO)
async def update_config(data: FollowConfigUpdate) -> FollowConfigDTO:
    """保存跟单配置到 SQLite。"""
    cfg = repository.save_config(data)
    logger.info(
        "event=follow_config_updated signal_server_url=%s poll_interval_ms=%s",
        cfg.signal_server_url,
        cfg.poll_interval_ms,
    )
    return cfg


@router.post("/config/connectivity", response_model=SignalServerConnectivityResult)
async def check_connectivity(
    data: SignalServerConnectivityCheck,
) -> SignalServerConnectivityResult:
    """探测喊单端轻量接口是否可达。"""
    return await probe_signal_server(data.normalized_url())
