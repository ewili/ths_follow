"""SQLite 持久层：stock_limit_prices 表的 CRUD。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from app.core import settings


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def upsert_stock_prices(records: list[dict]) -> int:
    """批量写入股票涨跌停价数据（INSERT OR REPLACE）。

    每条 record 需包含: stock_code, stock_name, close_price,
    limitup_price, limitdown_price, trade_date
    返回写入条数。
    """
    if not records:
        return 0

    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = _get_conn()
    try:
        conn.executemany(
            """
            INSERT OR REPLACE INTO stock_limit_prices
                (stock_code, stock_name, close_price,
                 limitup_price, limitdown_price, trade_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["stock_code"],
                    r["stock_name"],
                    r["close_price"],
                    r["limitup_price"],
                    r["limitdown_price"],
                    r["trade_date"],
                    now,
                )
                for r in records
            ],
        )
        conn.commit()
        return len(records)
    finally:
        conn.close()


def delete_by_trade_date(trade_date: str) -> int:
    """删除指定交易日的全部记录，返回删除条数。"""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM stock_limit_prices WHERE trade_date = ?",
            (trade_date,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def replace_all_stock_prices(records: list[dict]) -> int:
    """**原子替换**整张 stock_limit_prices 表：先清空再批量写入。

    采集业务语义为"库中始终只保留最近一次采集的数据"，因此每次定时任务都应
    覆盖整张表（而非按日期累积）。本方法在单个连接 + 显式事务中执行：

        BEGIN  →  DELETE FROM stock_limit_prices  →  INSERT OR REPLACE × N  →  COMMIT

    任意一步失败（如磁盘满 / 数据类型异常）都会 ROLLBACK，保证表不会处于
    "已被清空但新数据未写入" 的不可用状态。

    参数:
        records: 与 upsert_stock_prices 相同的字段约束（含 trade_date）

    返回:
        实际写入条数；records 为空时不做任何操作并返回 0
        （**特别保护**：禁止用空 records 把全表清空，否则任务失败时会让跟单端整体降级）

    说明:
        - SQLite 默认 isolation_level 即隐式事务模式，但显式 BEGIN/COMMIT 更可控
        - executemany 已经在事务内，连同 DELETE 一起原子提交
    """
    if not records:
        # 防御性兜底：空 records 视为"无效采集"，不动表
        return 0

    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = _get_conn()
    try:
        # 显式事务（覆盖默认的隐式 BEGIN，确保 DELETE 与 INSERT 在同一事务）
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM stock_limit_prices")
            conn.executemany(
                """
                INSERT OR REPLACE INTO stock_limit_prices
                    (stock_code, stock_name, close_price,
                     limitup_price, limitdown_price, trade_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r["stock_code"],
                        r["stock_name"],
                        r["close_price"],
                        r["limitup_price"],
                        r["limitdown_price"],
                        r["trade_date"],
                        now,
                    )
                    for r in records
                ],
            )
            conn.commit()
            return len(records)
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def get_latest_trade_date() -> Optional[str]:
    """返回库中最新的 trade_date，无数据时返回 None。"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT trade_date FROM stock_limit_prices ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        return row["trade_date"] if row else None
    finally:
        conn.close()


def get_stock_count(trade_date: str) -> int:
    """返回指定交易日的记录数。"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM stock_limit_prices WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def get_limit_prices_by_codes(
    stock_codes: list[str],
    trade_date: Optional[str] = None,
) -> tuple[dict[str, dict], Optional[str]]:
    """批量查询涨跌停价（US-003 SignalService 消费）。

    参数:
        stock_codes: 待查询股票代码列表（去重前后均可）
        trade_date: 指定交易日；None 时取库中最新交易日

    返回:
        (mapping, actual_trade_date)
        - mapping: {stock_code: {"limitup_price": float, "limitdown_price": float}}
                   未匹配的股票代码不在 mapping 中（由调用方降级为 has_limit_price=false）
        - actual_trade_date: 实际命中的交易日；无数据时为 None

    实现说明:
        - 单次 SQLite 查询 + IN 子句，命中内存页缓存 <1ms
        - 不在此处做缓存（DB 读太便宜，缓存反而引入失效风险）
    """
    if not stock_codes:
        return {}, None

    conn = _get_conn()
    try:
        if trade_date is None:
            trade_date = get_latest_trade_date()
        if trade_date is None:
            return {}, None

        # 去重并保留稳定顺序，便于占位符生成
        unique_codes = list(dict.fromkeys(stock_codes))
        placeholders = ",".join(["?"] * len(unique_codes))
        sql = (
            "SELECT stock_code, limitup_price, limitdown_price "
            "FROM stock_limit_prices "
            f"WHERE trade_date = ? AND stock_code IN ({placeholders})"
        )
        rows = conn.execute(sql, [trade_date, *unique_codes]).fetchall()

        mapping: dict[str, dict] = {
            r["stock_code"]: {
                "limitup_price": r["limitup_price"],
                "limitdown_price": r["limitdown_price"],
            }
            for r in rows
        }
        return mapping, trade_date
    finally:
        conn.close()


def get_latest_stocks(
    trade_date: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    keyword: Optional[str] = None,
) -> tuple[list[dict], int]:
    """查询指定日期（默认最新）的股票列表，支持分页和关键词搜索。

    返回 (records, total)。
    """
    conn = _get_conn()
    try:
        if trade_date is None:
            trade_date = get_latest_trade_date()
        if trade_date is None:
            return [], 0

        base_where = "WHERE trade_date = ?"
        params: list = [trade_date]

        if keyword:
            base_where += " AND (stock_code LIKE ? OR stock_name LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like])

        # total
        count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM stock_limit_prices {base_where}",
            params,
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        # page
        offset = (page - 1) * size
        rows = conn.execute(
            f"""SELECT * FROM stock_limit_prices {base_where}
                ORDER BY stock_code ASC
                LIMIT ? OFFSET ?""",
            params + [size, offset],
        ).fetchall()

        records = [dict(r) for r in rows]
        return records, total
    finally:
        conn.close()
