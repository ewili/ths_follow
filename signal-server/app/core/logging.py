"""日志配置：控制台 + 按天/大小双重 rotate 文件。"""

import logging
import logging.handlers
from pathlib import Path

from app.core.settings import LOG_FILE


def _patch_handler_flush_for_windows() -> None:
    """避免 pywinauto 导入时 ActionLogger.flush 在部分环境下 OSError [Errno 22]。"""
    if getattr(logging.Handler, "_ths_flush_patched", False):
        return
    _orig_flush = logging.Handler.flush

    def _safe_flush(self) -> None:
        try:
            _orig_flush(self)
        except OSError as exc:
            if getattr(exc, "errno", None) != 22:
                raise

    logging.Handler.flush = _safe_flush  # type: ignore[method-assign]
    logging.Handler._ths_flush_patched = True


def setup_logging(level: int = logging.INFO) -> None:
    _patch_handler_flush_for_windows()
    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # 文件（按天 rotate，最多保留 30 天，单文件最大 10 MB）
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
