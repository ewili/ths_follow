"""SQLite 持久层：follow_config 单行表 CRUD + follow_records 日志。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from app.core import settings
from app.models.config import FollowConfigDTO, FollowConfigUpdate

_SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """幂等地迁移：重建 follow_records 表（保留 follow_mode/follow_multiplier 列 + 支持 pending 状态）。"""
    import logging
    _logger = logging.getLogger(__name__)

    sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='follow_records'"
    ).fetchone()

    need_rebuild = False
    if sql_row:
        ddl = sql_row[0]
        # 旧表不支持 pending 状态时需重建
        if "'pending'" not in ddl:
            need_rebuild = True
        # 旧表缺少 follow_mode 列时需重建
        if "follow_mode" not in ddl:
            need_rebuild = True

    if need_rebuild:
        conn.execute("ALTER TABLE follow_records RENAME TO follow_records_old")

        conn.execute("""
            CREATE TABLE follow_records (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code            TEXT    NOT NULL,
                stock_name            TEXT    NOT NULL,
                action                TEXT    NOT NULL CHECK (action IN ('buy', 'sell', 'cancel')),
                signal_entrust_no     TEXT    NOT NULL,
                signal_entrust_time   TEXT    NOT NULL,
                signal_original_price REAL    NOT NULL,
                signal_entrust_qty    INTEGER NOT NULL,
                limit_price           REAL,
                quantity              INTEGER,
                signal_ratio          REAL,
                follow_mode           TEXT    CHECK (follow_mode IN ('ratio', 'multiplier')),
                follow_multiplier     REAL,
                status                TEXT    NOT NULL CHECK (status IN ('pending', 'success', 'warn', 'failed')),
                entrust_no            TEXT,
                error_code            TEXT,
                detail                TEXT,
                created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # 复制历史数据（保留 follow_mode/follow_multiplier 列，如存在）
        old_cols = [row[1] for row in conn.execute("PRAGMA table_info(follow_records_old)").fetchall()]
        new_cols = [row[1] for row in conn.execute("PRAGMA table_info(follow_records)").fetchall()]
        common = [c for c in old_cols if c in new_cols]
        cols_str = ", ".join(common)
        conn.execute(f"""
            INSERT INTO follow_records
                ({cols_str})
            SELECT {cols_str}
            FROM follow_records_old
            WHERE status != 'pending'
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_records_signal_no
                ON follow_records(signal_entrust_no, action)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_follow_records_created_at
                ON follow_records(created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_follow_records_stock_code
                ON follow_records(stock_code)
        """)

        conn.execute("DROP TABLE follow_records_old")

        _logger.info("migrate: follow_records rebuilt (with follow_mode/follow_multiplier columns)")

    # 清理孤儿的 pending 记录（崩溃遗留）
    deleted = conn.execute(
        "DELETE FROM follow_records WHERE status = 'pending'"
    ).rowcount
    if deleted > 0:
        _logger.info("cleanup_orphan_pending_records count=%d", deleted)

    # follow_config 表列迁移：追加 captcha_mode / vlm_api_key
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(follow_config)").fetchall()}
    for col, ddl in [
        ("captcha_mode", "TEXT NOT NULL DEFAULT 'local' CHECK (captcha_mode IN ('local', 'vlm', 'auto'))"),
        ("vlm_api_key", "TEXT NOT NULL DEFAULT ''"),
        ("captcha_auto_fail_threshold", "INTEGER NOT NULL DEFAULT 3 CHECK (captcha_auto_fail_threshold BETWEEN 1 AND 10)"),
        ("captcha_vlm_call_count", "INTEGER NOT NULL DEFAULT 3 CHECK (captcha_vlm_call_count BETWEEN 1 AND 10)"),
        ("schedule_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("schedule_weekdays", "TEXT NOT NULL DEFAULT ''"),
        ("schedule_time_ranges", "TEXT NOT NULL DEFAULT ''"),
        ("history_entrust_period", "TEXT NOT NULL DEFAULT '当日' CHECK (history_entrust_period IN ('当日', '近一周', '近一月', '近三月', '近一年'))"),
        ("entrust_source", "TEXT NOT NULL DEFAULT 'today' CHECK (entrust_source IN ('today', 'history'))"),
        ("follow_mode", "TEXT NOT NULL DEFAULT 'ratio' CHECK (follow_mode IN ('ratio', 'multiplier'))"),
        ("follow_multiplier", "REAL NOT NULL DEFAULT 1.0 CHECK (follow_multiplier BETWEEN 0.1 AND 100)"),
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE follow_config ADD COLUMN {col} {ddl}")
            _logger.info("migrate: added column %s to follow_config", col)

    # 修复 captcha_mode CHECK 约束：旧库 ALTER TABLE ADD COLUMN 时约束只有 ('local','vlm')，
    # 缺少 'auto'。SQLite 不支持 ALTER COLUMN，需重建表来修复。
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='follow_config'"
    ).fetchone()
    if table_sql and "('local', 'vlm')" in table_sql[0] and "'auto'" not in table_sql[0].split("captcha_mode")[1].split(")")[0]:
        _logger.info("migrate: rebuilding follow_config to fix captcha_mode CHECK constraint")
        conn.execute("ALTER TABLE follow_config RENAME TO _follow_config_old")
        conn.execute("""
            CREATE TABLE follow_config (
                id                         INTEGER PRIMARY KEY CHECK (id = 1),
                signal_server_url          TEXT    NOT NULL DEFAULT '',
                poll_interval_ms           INTEGER NOT NULL DEFAULT 500
                                           CHECK (poll_interval_ms BETWEEN 100 AND 5000),
                local_ths_exe_path         TEXT    NOT NULL DEFAULT '',
                cold_start_align_existing  INTEGER NOT NULL DEFAULT 0,
                use_type_keys              INTEGER NOT NULL DEFAULT 0,
                grid_strategy              TEXT    NOT NULL DEFAULT 'Copy'
                                           CHECK (grid_strategy IN ('Copy', 'Xls', 'WMCopy')),
                captcha_mode               TEXT    NOT NULL DEFAULT 'local'
                                           CHECK (captcha_mode IN ('local', 'vlm', 'auto')),
                vlm_api_key                TEXT    NOT NULL DEFAULT '',
                captcha_auto_fail_threshold INTEGER NOT NULL DEFAULT 3
                                           CHECK (captcha_auto_fail_threshold BETWEEN 1 AND 10),
                captcha_vlm_call_count     INTEGER NOT NULL DEFAULT 3
                                           CHECK (captcha_vlm_call_count BETWEEN 1 AND 10),
                schedule_enabled           INTEGER NOT NULL DEFAULT 0,
                schedule_weekdays          TEXT    NOT NULL DEFAULT '',
                schedule_time_ranges       TEXT    NOT NULL DEFAULT '',
                history_entrust_period     TEXT    NOT NULL DEFAULT '当日'
                                           CHECK (history_entrust_period IN ('当日', '近一周', '近一月', '近三月', '近一年')),
                entrust_source             TEXT    NOT NULL DEFAULT 'today'
                                           CHECK (entrust_source IN ('today', 'history')),
                follow_mode                TEXT    NOT NULL DEFAULT 'ratio'
                                           CHECK (follow_mode IN ('ratio', 'multiplier')),
                follow_multiplier          REAL    NOT NULL DEFAULT 1.0
                                           CHECK (follow_multiplier BETWEEN 0.1 AND 100),
                updated_at                 TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        old_cols = [row[1] for row in conn.execute("PRAGMA table_info(_follow_config_old)").fetchall()]
        new_cols = [row[1] for row in conn.execute("PRAGMA table_info(follow_config)").fetchall()]
        common = [c for c in old_cols if c in new_cols]
        cols_str = ", ".join(common)
        conn.execute(f"INSERT INTO follow_config ({cols_str}) SELECT {cols_str} FROM _follow_config_old")
        conn.execute("DROP TABLE _follow_config_old")
        conn.execute("INSERT OR IGNORE INTO follow_config (id) VALUES (1)")
        conn.commit()


def init_db() -> None:
    """启动时执行 schema.sql，幂等；再执行列迁移。"""
    conn = _get_conn()
    try:
        conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.commit()
        _migrate(conn)
    finally:
        conn.close()


def reset_db() -> None:
    """测试用：删除表并重建。"""
    conn = _get_conn()
    try:
        conn.execute("DROP TABLE IF EXISTS follow_config")
        conn.execute("DROP TABLE IF EXISTS follow_records")
        conn.commit()
        init_db()
    finally:
        conn.close()


# ── follow_config ────────────────────────────────────────────


def load_config() -> FollowConfigDTO:
    from app.models.config import FollowConfigDTO
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM follow_config WHERE id = 1").fetchone()
        return FollowConfigDTO(
            signal_server_url=row["signal_server_url"],
            poll_interval_ms=row["poll_interval_ms"],
            local_ths_exe_path=row["local_ths_exe_path"],
            cold_start_align_existing=bool(row["cold_start_align_existing"]),
            use_type_keys=bool(row["use_type_keys"]),
            grid_strategy=row["grid_strategy"],
            captcha_mode=row["captcha_mode"] if "captcha_mode" in row.keys() else "local",
            vlm_api_key=row["vlm_api_key"] if "vlm_api_key" in row.keys() else "",
            captcha_auto_fail_threshold=row["captcha_auto_fail_threshold"] if "captcha_auto_fail_threshold" in row.keys() else 3,
            captcha_vlm_call_count=row["captcha_vlm_call_count"] if "captcha_vlm_call_count" in row.keys() else 3,
            schedule_enabled=bool(row["schedule_enabled"]) if "schedule_enabled" in row.keys() else False,
            schedule_weekdays=json.loads(row["schedule_weekdays"]) if "schedule_weekdays" in row.keys() and row["schedule_weekdays"] else [],
            schedule_time_ranges=json.loads(row["schedule_time_ranges"]) if "schedule_time_ranges" in row.keys() and row["schedule_time_ranges"] else [],
            history_entrust_period=row["history_entrust_period"] if "history_entrust_period" in row.keys() else "当日",
            entrust_source=row["entrust_source"] if "entrust_source" in row.keys() else "today",
            follow_mode=row["follow_mode"] if "follow_mode" in row.keys() else "ratio",
            follow_multiplier=row["follow_multiplier"] if "follow_multiplier" in row.keys() else 1.0,
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    finally:
        conn.close()


def save_config(data: FollowConfigUpdate) -> FollowConfigDTO:
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE follow_config
               SET signal_server_url = ?,
                   poll_interval_ms = ?,
                   local_ths_exe_path = ?,
                   cold_start_align_existing = ?,
                   use_type_keys = ?,
                   grid_strategy = ?,
                   captcha_mode = ?,
                   vlm_api_key = ?,
                   captcha_auto_fail_threshold = ?,
                   captcha_vlm_call_count = ?,
                   schedule_enabled = ?,
                   schedule_weekdays = ?,
                   schedule_time_ranges = ?,
                   history_entrust_period = ?,
                   entrust_source = ?,
                   follow_mode = ?,
                   follow_multiplier = ?,
                   updated_at = ?
             WHERE id = 1
            """,
            (
                data.signal_server_url,
                data.poll_interval_ms,
                data.local_ths_exe_path,
                int(data.cold_start_align_existing),
                int(data.use_type_keys),
                data.grid_strategy,
                data.captcha_mode,
                data.vlm_api_key,
                data.captcha_auto_fail_threshold,
                data.captcha_vlm_call_count,
                int(data.schedule_enabled),
                json.dumps(data.schedule_weekdays),
                json.dumps([r.model_dump() for r in data.schedule_time_ranges]),
                data.history_entrust_period,
                data.entrust_source,
                data.follow_mode,
                data.follow_multiplier,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return load_config()


# ── follow_records ───────────────────────────────────────────


def insert_follow_record(record: dict) -> int:
    """写入跟单操作日志，返回新行 id。
    record 字段与 follow_records 表列一一对应（除 id / created_at）。
    """
    conn = _get_conn()
    try:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO follow_records
                (stock_code, stock_name, action,
                 signal_entrust_no, signal_entrust_time,
                 signal_original_price, signal_entrust_qty,
                 limit_price, quantity,
                 signal_ratio,
                 follow_mode, follow_multiplier,
                 status, entrust_no, error_code, detail)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["stock_code"],
                record["stock_name"],
                record["action"],
                record["signal_entrust_no"],
                record["signal_entrust_time"],
                record["signal_original_price"],
                record["signal_entrust_qty"],
                record.get("limit_price"),
                record.get("quantity"),
                record.get("signal_ratio"),
                record.get("follow_mode"),
                record.get("follow_multiplier"),
                record["status"],
                record.get("entrust_no"),
                record.get("error_code"),
                record.get("detail"),
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0
    finally:
        conn.close()


def update_follow_record(
    signal_entrust_no: str,
    action: str,
    *,
    status: str,
    entrust_no: Optional[str] = None,
    error_code: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """更新已有的跟单记录状态（用于先写后执行模式）。
    
    Args:
        signal_entrust_no: 喊单委托编号
        action: 操作类型（buy/sell/cancel）
        status: 新状态（success/failed/warn）
        entrust_no: 本地委托编号（成功时填充）
        error_code: 错误代码（失败时填充）
        detail: 详细信息
    """
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE follow_records
            SET status = ?, entrust_no = ?, error_code = ?, detail = ?
            WHERE signal_entrust_no = ? AND action = ?
            """,
            (status, entrust_no, error_code, detail, signal_entrust_no, action),
        )
        conn.commit()
    finally:
        conn.close()


def get_today_records() -> list[dict]:
    """返回当日（UTC 日期）所有跟单记录，按 created_at DESC。"""
    today = date.today().isoformat()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM follow_records WHERE created_at >= ? ORDER BY created_at DESC",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def has_followed(signal_entrust_no: str, action: str) -> bool:
    """判断某笔喊单委托是否已跟随成功（status='success'）。"""
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT 1 FROM follow_records
             WHERE signal_entrust_no = ? AND action = ? AND status = 'success'
             LIMIT 1
            """,
            (signal_entrust_no, action),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_today_records_count() -> int:
    """返回当日跟单记录数量。"""
    today = date.today().isoformat()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM follow_records WHERE created_at >= ?",
            (today,),
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def delete_today_records() -> int:
    """清空当日所有跟单记录，返回删除行数。

    用于冷启动存量对齐前清除旧记录，避免 has_followed() 防重复误判。
    """
    today = date.today().isoformat()
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM follow_records WHERE created_at >= ?",
            (today,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_records_page(
    page: int = 1,
    size: int = 50,
    stock_code: Optional[str] = None,
) -> tuple[list[dict], int]:
    """分页查询跟单记录，返回 (items, total)。"""
    conn = _get_conn()
    try:
        where = "WHERE stock_code = ?" if stock_code else ""
        params_count = (stock_code,) if stock_code else ()
        total = conn.execute(
            f"SELECT COUNT(*) FROM follow_records {where}", params_count
        ).fetchone()[0]

        offset = (page - 1) * size
        params = (*params_count, size, offset)
        rows = conn.execute(
            f"SELECT * FROM follow_records {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_today_successful_entrust_nos() -> dict[str, str]:
    """返回当日所有成功跟随的本地委托编号映射（entrust_no → stock_code）。

    用于双重保险逻辑：只匹配跟单系统自己下的委托，忽略用户手动交易。
    同时保留 stock_code 映射，确保双重保险不会跨股票误判。
    """
    today = date.today().isoformat()
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT entrust_no, stock_code FROM follow_records
            WHERE created_at >= ?
              AND action IN ('buy', 'sell')
              AND status = 'success'
              AND entrust_no IS NOT NULL
              AND entrust_no != ''
            """,
            (today,),
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()


def get_local_entrust_nos_by_signal(signal_entrust_no: str) -> list[str]:
    """查询与喊单委托关联的所有本地委托编号（仅成功跟随的 buy/sell 记录）。
    
    Args:
        signal_entrust_no: 喊单委托编号
    
    Returns:
        本地委托编号列表（去重后，按创建时间正序）
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT entrust_no FROM follow_records
            WHERE signal_entrust_no = ?
              AND action IN ('buy', 'sell')
              AND status = 'success'
              AND entrust_no IS NOT NULL
              AND entrust_no != ''
            ORDER BY created_at ASC
            """,
            (signal_entrust_no,),
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()
