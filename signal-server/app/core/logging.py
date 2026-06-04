"""日志配置：控制台 + 按天/大小双重 rotate 文件。"""

import logging
import logging.handlers
from pathlib import Path

from app.core.settings import LOG_FILE


def setup_logging(level: int = logging.INFO) -> None:
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
