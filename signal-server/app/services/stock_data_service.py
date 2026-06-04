"""股票列表与涨跌停价采集服务（US-002）。"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime

import akshare as ak
import pandas as pd

from app.db import stock_repository

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAYS = [1, 2, 4]  # 秒，递增退避


# ── 纯函数（方便单测） ──────────────────────────────────────


def calc_limit_prices(close_price: float) -> tuple[float, float]:
    """计算涨停价和跌停价（主板 10%，截断到分）。

    涨停价向下截断（确保不超涨停），跌停价向上截断（确保不低于跌停）。

    Returns:
        (limitup_price, limitdown_price)
    """
    limitup = math.floor(close_price * 1.10 * 100) / 100
    limitdown = math.ceil(close_price * 0.90 * 100) / 100
    return limitup, limitdown


def filter_mainboard(df: pd.DataFrame) -> pd.DataFrame:
    """过滤仅保留主板股票（代码以 00 或 60 开头），同时排除 ST 股票。

    期望 DataFrame 中有 '代码' 列和 '名称' 列。
    """
    if df.empty or "代码" not in df.columns:
        return df.iloc[0:0]
    code_mask = df["代码"].str.startswith("00") | df["代码"].str.startswith("60")
    st_mask = df["名称"].str.upper().str.contains("ST") if "名称" in df.columns else False
    return df[code_mask & ~st_mask].copy()


# ── 采集主流程 ───────────────────────────────────────────────


def _try_fetch(api_func, api_name: str) -> pd.DataFrame | None:
    """尝试通过指定 akshare 接口获取数据，失败返回 None。"""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            df = api_func()
            if df is not None and not df.empty:
                return df
            logger.warning(
                "event=stock_fetch_empty_api api=%s attempt=%d/%d 返回空数据",
                api_name, attempt, _MAX_RETRIES,
            )
        except Exception as exc:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt - 1]
                logger.warning(
                    "event=stock_fetch_retry api=%s attempt=%d/%d delay=%ds error=%s",
                    api_name, attempt, _MAX_RETRIES, delay, exc,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "event=stock_fetch_api_failed api=%s 已重试 %d 次: %s",
                    api_name, _MAX_RETRIES, exc,
                )
    return None


def fetch_and_save() -> dict:
    """从新浪财经（akshare）抓取全 A 股行情，过滤主板，计算涨跌停价并写入 SQLite。

    主接口为 stock_zh_a_spot（新浪），失败后降级尝试 stock_zh_a_spot_em（东方财富）。

    Returns:
        {"success": True/False, "count": int, "trade_date": str, "message": str}
    """
    logger.info("event=stock_fetch_start 开始采集股票行情数据")

    # 主接口：新浪财经
    df = _try_fetch(ak.stock_zh_a_spot, "sina")
    used_api = "sina"

    # 降级备选：东方财富
    if df is None:
        logger.warning("event=stock_fetch_fallback 新浪接口失败，尝试东方财富接口")
        df = _try_fetch(ak.stock_zh_a_spot_em, "eastmoney")
        used_api = "eastmoney"

    if df is None or df.empty:
        msg = "所有 akshare 接口均失败（可能为非交易日或接口异常）"
        logger.warning("event=stock_fetch_error %s", msg)
        return {"success": False, "count": 0, "trade_date": None, "message": msg}

    # stock_zh_a_spot（新浪）的代码列带交易所前缀（如 sh600000），需剥离为纯数字代码
    # stock_zh_a_spot_em（东方财富）的代码列已是纯数字，无需处理
    if used_api == "sina" and "代码" in df.columns:
        df["代码"] = df["代码"].str.replace(r"^[a-zA-Z]+", "", regex=True)

    # 过滤主板
    mainboard = filter_mainboard(df)
    if mainboard.empty:
        msg = "过滤后无主板股票数据"
        logger.warning("event=stock_fetch_empty %s", msg)
        return {"success": False, "count": 0, "trade_date": None, "message": msg}

    # 确定交易日期：使用当天日期
    trade_date = datetime.now().strftime("%Y-%m-%d")

    # 构造写入记录
    records = []
    for _, row in mainboard.iterrows():
        code = str(row["代码"])
        name = str(row.get("名称", ""))
        close_price = float(row.get("最新价", 0))
        if close_price <= 0:
            continue
        limitup, limitdown = calc_limit_prices(close_price)
        records.append(
            {
                "stock_code": code,
                "stock_name": name,
                "close_price": close_price,
                "limitup_price": limitup,
                "limitdown_price": limitdown,
                "trade_date": trade_date,
            }
        )

    if not records:
        msg = "所有主板股票收盘价均无效，跳过写入"
        logger.warning("event=stock_fetch_empty %s", msg)
        return {"success": False, "count": 0, "trade_date": trade_date, "message": msg}

    # 原子替换全表：库中始终只保留最近一次采集的数据，避免历史累积导致
    # 跟单端在任务失败时拿到陈旧涨跌停（详见 docs/design/US-003-signal-order-query-api.md §6.3）
    count = stock_repository.replace_all_stock_prices(records)
    logger.info(
        "event=stock_fetch_done trade_date=%s count=%d 采集完成（全表替换）",
        trade_date,
        count,
    )
    return {
        "success": True,
        "count": count,
        "trade_date": trade_date,
        "message": f"成功采集 {count} 只主板股票",
    }
