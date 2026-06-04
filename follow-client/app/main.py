"""FastAPI 入口。"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.config import router as config_router
from app.api.follow import router as follow_router
from app.api.trader import router as trader_router
from app.core.logging import setup_logging
from app.core.settings import BASE_DIR
from app.db.repository import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    yield


app = FastAPI(title="Follow Client", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(trader_router)
app.include_router(follow_router)

# PyInstaller 打包后静态资源在 _MEIPASS，开发环境在 BASE_DIR
_bundle_dir = getattr(sys, '_MEIPASS', None)
web_dist_dir = (Path(_bundle_dir) / "web" / "dist") if _bundle_dir else (BASE_DIR / "web" / "dist")
if web_dist_dir.exists():
    app.mount("/", StaticFiles(directory=web_dist_dir, html=True), name="web")
