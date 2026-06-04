"""日志配置：控制台 + 按天 rotate 文件。"""

import logging
import logging.handlers

from app.core.settings import LOG_FILE


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if getattr(setup_logging, "_configured", False):
        root.setLevel(level)
        return

    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    setup_logging._configured = True
