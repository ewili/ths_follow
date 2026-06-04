"""统一错误码与异常映射。"""

from __future__ import annotations

from fastapi import HTTPException


# ── 错误码常量 ──────────────────────────────────────────────

THS_PATH_INVALID = "THS_PATH_INVALID"
THS_NOT_FOUND = "THS_NOT_FOUND"
THS_NOT_LOGGED_IN = "THS_NOT_LOGGED_IN"
THS_BUSY = "THS_BUSY"
THS_UNKNOWN = "THS_UNKNOWN"


# ── 自定义业务异常 ────────────────────────────────────────────

class ThsConnectError(HTTPException):
    """easytrader 连接阶段抛出的异常统一封装。"""

    def __init__(self, status_code: int, code: str, message: str, detail: str = ""):
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message, "detail": detail},
        )

    @classmethod
    def from_exception(cls, exc: Exception) -> "ThsConnectError":
        code, status, msg = _classify(exc)
        return cls(
            status_code=status,
            code=code,
            message=msg,
            detail=f"{exc.__class__.__name__}: {exc}",
        )


# ── 异常分类 ─────────────────────────────────────────────────

def _classify(exc: Exception) -> tuple[str, int, str]:
    """将 easytrader / pywinauto 异常映射为 (错误码, HTTP 状态, 用户提示)。"""
    exc_str = str(exc)
    exc_lower = exc_str.lower()
    type_name = type(exc).__name__

    # ValueError: "参数 exe_path 未设置"
    if isinstance(exc, ValueError) and "exe_path" in exc_str:
        return THS_PATH_INVALID, 400, "请填写 xiadan.exe 的绝对路径"

    # pywinauto.findwindows.ElementNotFoundError
    if type_name == "ElementNotFoundError":
        if "timeout" in exc_lower or "timed out" in exc_lower:
            return THS_NOT_FOUND, 404, "查询同花顺控件超时（可能窗口被遮挡或弹窗阻塞），请确认终端前台可见"
        return THS_NOT_FOUND, 404, "终端未找到或未登录，请确认同花顺已启动并完成登录"

    # pywinauto.application.ProcessNotFoundError
    if type_name == "ProcessNotFoundError":
        return THS_NOT_FOUND, 404, "终端进程未找到，请确认同花顺已启动并完成登录"

    # pywinauto.timings.TimeoutError
    if type_name == "TimeoutError" or (isinstance(exc, OSError) and "timeout" in exc_str.lower()):
        return THS_NOT_FOUND, 404, "连接同花顺终端超时，请确认终端已启动"

    # OSError [Errno 22]：可能是进程枚举失败，也可能是日志 flush（pywinauto 导入阶段）
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 22:
        if "flush" in exc_lower or "actionlogger" in exc_lower or "pywinauto" in exc_lower:
            return THS_UNKNOWN, 500, "终端自动化组件初始化失败，请重试；若仍失败请重启后端服务"
        return THS_NOT_FOUND, 404, "终端进程枚举失败，请确认同花顺已启动并完成登录"

    # pywinauto.application.AppNotConnected
    if type_name == "AppNotConnected":
        return THS_NOT_LOGGED_IN, 409, "终端未连接，请先启动并登录同花顺"

    # 窗口句柄已失效 / 连接对象仍在但底层窗口已关闭
    if "valid window handle" in exc_lower or "window handle" in exc_lower:
        return THS_NOT_LOGGED_IN, 409, "终端窗口已失效，请重新连接同花顺终端"

    # SetForegroundWindow 失败：窗口不在前台，GUI 操作被拒绝（临时性，可重试）
    if "setforegroundwindow" in exc_lower:
        return THS_BUSY, 409, "终端窗口未在前台，请确保同花顺客户端可见且未被遮挡"

    # SendInput 失败：键盘事件未成功注入（通常因窗口不在前台）
    if "sendinput" in exc_lower:
        return THS_BUSY, 409, "终端窗口未在前台，键盘输入被拒绝，请确保同花顺客户端可见"

    # ElementNotVisible：控件不可见（通常因弹窗遮挡主窗口），临时性可重试
    if "elementnotvisible" in exc_lower or type_name == "ElementNotVisible":
        return THS_BUSY, 409, "终端控件不可见（可能被弹窗遮挡），请确认同花顺客户端前台可见"

    return THS_UNKNOWN, 500, f"终端连接异常：{exc.__class__.__name__}: {exc}"


def map_exception_message(exc: Exception) -> str:
    """返回简短的中文错误描述，供 TraderService._last_error 存储。"""
    _, _, msg = _classify(exc)
    return msg
