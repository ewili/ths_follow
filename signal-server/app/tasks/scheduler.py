"""APScheduler 定时任务调度（US-002）。

每日 15:30 触发股票行情采集。
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.stock_data_service import fetch_and_save
from app.services.trader_service import TraderService

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_stock_fetch() -> None:
    """调度器回调：执行采集并记录结果。"""
    try:
        result = await asyncio.to_thread(fetch_and_save)
        if result["success"]:
            logger.info(
                "event=scheduled_fetch_done trade_date=%s count=%d",
                result["trade_date"],
                result["count"],
            )
        else:
            logger.warning(
                "event=scheduled_fetch_failed message=%s",
                result["message"],
            )
    except Exception:
        logger.exception("event=scheduled_fetch_exception 定时采集异常")


async def _run_ths_health_check() -> None:
    """调度器回调：检查同花顺连接健康状态。"""
    try:
        trader_svc = TraderService.get()
        if trader_svc.trader is None:
            return
        
        status = await trader_svc.health_probe()
        if status.state == "error":
            logger.warning(
                "event=ths_health_check_failed last_error=%s",
                status.last_error
            )
        else:
            logger.debug("event=ths_health_check_ok")
    except Exception:
        logger.exception("event=ths_health_check_exception 健康检查异常")


def start_scheduler() -> None:
    """启动 APScheduler，注册每日 15:30 采集任务。"""
    global _scheduler
    if _scheduler is not None:
        logger.warning("Scheduler 已在运行中，跳过重复启动")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_stock_fetch,
        trigger=CronTrigger(hour=15, minute=30),
        id="daily_stock_fetch",
        name="每日股票行情采集",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_ths_health_check,
        trigger="interval",
        minutes=5,
        id="ths_health_check",
        name="同花顺连接健康检查",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("event=scheduler_started 定时任务已启动（每日 15:30 采集 + 每 5 分钟健康检查）")


def stop_scheduler() -> None:
    """优雅关闭调度器。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("event=scheduler_stopped 定时任务已停止")


def is_scheduler_running() -> bool:
    """返回调度器是否正在运行。"""
    return _scheduler is not None and _scheduler.running
