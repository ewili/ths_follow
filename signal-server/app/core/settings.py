"""全局配置常量。"""

import sys
from pathlib import Path


def _get_base_dir() -> Path:
    """获取基础目录，支持 PyInstaller 打包。"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，使用 exe 所在目录
        return Path(sys.executable).parent
    else:
        # 开发环境
        return Path(__file__).resolve().parent.parent.parent


BASE_DIR = _get_base_dir()

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "signal_server.db"

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "signal_server.log"

# FastAPI 默认端口
SERVER_PORT = 8000
