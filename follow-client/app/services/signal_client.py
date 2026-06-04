"""HTTP 客户端：拉取喊单端委托（当日 / 历史）。"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.models.follow import SignalEntrustDTO

logger = logging.getLogger(__name__)

_ENTRUSTS_PATH = "/api/signal/entrusts"
_HISTORY_ENTRUSTS_DTO_PATH = "/api/signal/history-entrusts-dto"
_TIMEOUT = httpx.Timeout(connect=50.0, read=60.0, write=50.0, pool=50.0)


def is_valid_entrust(e: SignalEntrustDTO) -> bool:
    """过滤喊单端停止/未下单时返回的空占位委托。"""
    return (
        e.entrust_qty > 0
        and e.entrust_time != ""
        and e.original_price > 0
        and e.entrust_no != ""
    )


async def fetch_signal_entrusts(
    signal_server_url: str,
) -> tuple[list[SignalEntrustDTO], Optional[str]]:
    """GET /api/signal/entrusts，返回 (有效委托列表, trade_date)。

    网络异常时抛出 httpx.HTTPError 子类，由 follow_engine 捕获。
    """
    url = f"{signal_server_url.rstrip('/')}{_ENTRUSTS_PATH}"
    logger.debug("signal_entrusts fetching url=%s", url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("signal_entrusts_http_error url=%s status=%d detail=%s", url, exc.response.status_code, exc)
        raise
    except httpx.HTTPError as exc:
        logger.warning("signal_entrusts_network_error url=%s type=%s detail=%s", url, type(exc).__name__, exc)
        raise

    data = resp.json()
    items = [SignalEntrustDTO(**item) for item in data.get("items", [])]
    valid = [e for e in items if is_valid_entrust(e)]
    trade_date: Optional[str] = data.get("trade_date")

    logger.debug(
        "signal_entrusts fetched total=%d valid=%d trade_date=%s",
        len(items),
        len(valid),
        trade_date,
    )
    return valid, trade_date


async def fetch_signal_history_entrusts(
    signal_server_url: str,
    period: str,
) -> tuple[list[SignalEntrustDTO], Optional[str]]:
    """GET /api/signal/history-entrusts-dto?period=xxx，返回 (有效委托列表, trade_date)。

    返回格式与 fetch_signal_entrusts 完全一致，供跟单引擎直接复用。
    网络异常时抛出 httpx.HTTPError 子类，由 follow_engine 捕获。
    """
    url = f"{signal_server_url.rstrip('/')}{_HISTORY_ENTRUSTS_DTO_PATH}?period={period}"
    logger.debug("signal_history_entrusts fetching url=%s period=%s", url, period)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning("signal_history_entrusts_http_error url=%s status=%d detail=%s", url, exc.response.status_code, exc)
        raise
    except httpx.HTTPError as exc:
        logger.warning("signal_history_entrusts_network_error url=%s type=%s detail=%s", url, type(exc).__name__, exc)
        raise

    data = resp.json()
    items = [SignalEntrustDTO(**item) for item in data.get("items", [])]
    valid = [e for e in items if is_valid_entrust(e)]
    trade_date: Optional[str] = data.get("trade_date")

    logger.debug(
        "signal_history_entrusts fetched period=%s total=%d valid=%d trade_date=%s",
        period, len(items), len(valid), trade_date,
    )
    return valid, trade_date
