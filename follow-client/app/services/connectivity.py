"""喊单端轻量连通性探测。"""

from __future__ import annotations

import httpx

from app.models.connectivity import SignalServerConnectivityResult

_BALANCE_PATH = "/api/signal/status"
_TIMEOUT_SECONDS = 50.0


async def probe_signal_server(
    signal_server_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SignalServerConnectivityResult:
    checked_url = f"{signal_server_url.rstrip('/')}{_BALANCE_PATH}"
    client_kwargs: dict = {"timeout": _TIMEOUT_SECONDS, "trust_env": False}
    if transport is not None:
        client_kwargs["transport"] = transport
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.get(checked_url)
    except httpx.HTTPError as exc:
        return SignalServerConnectivityResult(
            ok=False,
            checked_url=checked_url,
            message=f"连接失败: {exc}",
            status_code=None,
        )

    if response.is_success:
        return SignalServerConnectivityResult(
            ok=True,
            checked_url=checked_url,
            message="连接正常",
            status_code=response.status_code,
        )

    return SignalServerConnectivityResult(
        ok=False,
        checked_url=checked_url,
        message=f"连接失败: HTTP {response.status_code}",
        status_code=response.status_code,
    )
