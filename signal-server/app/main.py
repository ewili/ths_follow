"""FastAPI 入口 + lifespan。"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.config import router as system_router
from app.api.signal import router as signal_router
from app.api.stock import router as stock_router
from app.core.logging import setup_logging
from app.core.settings import BASE_DIR
from app.db.repository import init_db, load_config
from app.db import stock_repository
from app.services.runtime_metrics_service import RuntimeMetricsService
from app.services.signal_runtime_service import SignalRuntimeService
from app.services.signal_service import SignalService
from app.services.trader_service import TraderService
from app.tasks.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    cfg = load_config()
    if cfg.ths_exe_path:
        logger.info(
            "system_config 已配置 ths_exe_path=%s，可通过 POST /api/system/connect 接管",
            cfg.ths_exe_path,
        )
    else:
        logger.info("system_config 尚未配置 ths_exe_path，请先在 Web 界面配置路径")
    # 检查 stock_limit_prices 表状态，无数据时提示用户采集
    _latest_trade_date = stock_repository.get_latest_trade_date()
    if _latest_trade_date is None:
        logger.warning(
            "stock_limit_prices 表为空，委托查询将返回空列表，"
            "请通过 POST /api/stock/fetch 采集股票行情数据"
        )
    else:
        _stock_count = stock_repository.get_stock_count(_latest_trade_date)
        logger.info(
            "stock_limit_prices 已有数据 trade_date=%s count=%d",
            _latest_trade_date, _stock_count,
        )
    start_scheduler()
    yield
    stop_scheduler()
    await TraderService.get().disconnect()
    SignalRuntimeService.reset()
    SignalService.reset()
    RuntimeMetricsService.reset()


app = FastAPI(title="Signal Server", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(stock_router)
app.include_router(signal_router)

# PyInstaller 打包后静态资源在 _MEIPASS，开发环境在 BASE_DIR
_bundle_dir = getattr(sys, '_MEIPASS', None)
web_dist_dir = (Path(_bundle_dir) / "web" / "dist") if _bundle_dir else (BASE_DIR / "web" / "dist")
if web_dist_dir.exists():
    app.mount("/", StaticFiles(directory=web_dist_dir, html=True), name="web")
