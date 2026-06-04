"""SQLite 持久层：system_config 单行表的 CRUD。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.core import settings
from app.models.config import SystemConfigDTO, SystemConfigUpdate

_SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(settings.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """幂等地为旧库追加新列（SQLite 不支持 IF NOT EXISTS on column）。"""
    import logging
    _logger = logging.getLogger(__name__)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(system_config)").fetchall()}
    for col, ddl in [
        ("captcha_mode", "TEXT NOT NULL DEFAULT 'local' CHECK (captcha_mode IN ('local', 'vlm', 'auto'))"),
        ("vlm_api_key", "TEXT NOT NULL DEFAULT ''"),
        ("captcha_auto_fail_threshold", "INTEGER NOT NULL DEFAULT 3 CHECK (captcha_auto_fail_threshold BETWEEN 1 AND 10)"),
        ("schedule_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("schedule_weekdays", "TEXT NOT NULL DEFAULT ''"),
        ("schedule_time_ranges", "TEXT NOT NULL DEFAULT ''"),
        ("history_entrust_period", "TEXT NOT NULL DEFAULT '当日' CHECK (history_entrust_period IN ('当日', '近一周', '近一月', '近三月', '近一年'))"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE system_config ADD COLUMN {col} {ddl}")
            _logger.info("migrate: added column %s to system_config", col)

    # 修复 captcha_mode CHECK 约束：旧库 ALTER TABLE ADD COLUMN 时约束只有 ('local','vlm')，
    # 缺少 'auto'。SQLite 不支持 ALTER COLUMN，需重建表来修复。
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='system_config'"
    ).fetchone()
    if table_sql and "('local', 'vlm')" in table_sql[0] and "'auto'" not in table_sql[0].split("captcha_mode")[1].split(")")[0]:
        _logger.info("migrate: rebuilding system_config to fix captcha_mode CHECK constraint")
        conn.execute("ALTER TABLE system_config RENAME TO _system_config_old")
        conn.execute("""
            CREATE TABLE system_config (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                ths_exe_path    TEXT    NOT NULL DEFAULT '',
                use_type_keys   INTEGER NOT NULL DEFAULT 0,
                grid_strategy   TEXT    NOT NULL DEFAULT 'Copy'
                                CHECK (grid_strategy IN ('Copy', 'Xls', 'WMCopy')),
                captcha_mode    TEXT    NOT NULL DEFAULT 'local'
                                CHECK (captcha_mode IN ('local', 'vlm', 'auto')),
                vlm_api_key     TEXT    NOT NULL DEFAULT '',
                captcha_auto_fail_threshold INTEGER NOT NULL DEFAULT 3
                                CHECK (captcha_auto_fail_threshold BETWEEN 1 AND 10),
                schedule_enabled INTEGER NOT NULL DEFAULT 0,
                schedule_weekdays TEXT   NOT NULL DEFAULT '',
                schedule_time_ranges TEXT NOT NULL DEFAULT '',
                history_entrust_period TEXT NOT NULL DEFAULT '当日'
                                CHECK (history_entrust_period IN ('当日', '近一周', '近一月', '近三月', '近一年')),
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        old_cols = [row[1] for row in conn.execute("PRAGMA table_info(_system_config_old)").fetchall()]
        new_cols = [row[1] for row in conn.execute("PRAGMA table_info(system_config)").fetchall()]
        common = [c for c in old_cols if c in new_cols]
        cols_str = ", ".join(common)
        conn.execute(f"INSERT INTO system_config ({cols_str}) SELECT {cols_str} FROM _system_config_old")
        conn.execute("DROP TABLE _system_config_old")
        conn.execute("INSERT OR IGNORE INTO system_config (id) VALUES (1)")
        conn.commit()


def init_db() -> None:
    """启动时执行 schema.sql，幂等。"""
    conn = _get_conn()
    try:
        conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.commit()
        _migrate(conn)
    finally:
        conn.close()


def reset_db() -> None:
    """测试用：删除表并重建，确保干净状态。"""
    conn = _get_conn()
    try:
        conn.execute("DROP TABLE IF EXISTS stock_limit_prices")
        conn.execute("DROP TABLE IF EXISTS system_config")
        conn.commit()
        init_db()
    finally:
        conn.close()


def load_config() -> SystemConfigDTO:
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM system_config WHERE id = 1").fetchone()
        return SystemConfigDTO(
            ths_exe_path=row["ths_exe_path"],
            use_type_keys=bool(row["use_type_keys"]),
            grid_strategy=row["grid_strategy"],
            captcha_mode=row["captcha_mode"] if "captcha_mode" in row.keys() else "local",
            vlm_api_key=row["vlm_api_key"] if "vlm_api_key" in row.keys() else "",
            captcha_auto_fail_threshold=row["captcha_auto_fail_threshold"] if "captcha_auto_fail_threshold" in row.keys() else 3,
            schedule_enabled=bool(row["schedule_enabled"]) if "schedule_enabled" in row.keys() else False,
            schedule_weekdays=json.loads(row["schedule_weekdays"]) if "schedule_weekdays" in row.keys() and row["schedule_weekdays"] else [],
            schedule_time_ranges=json.loads(row["schedule_time_ranges"]) if "schedule_time_ranges" in row.keys() and row["schedule_time_ranges"] else [],
            history_entrust_period=row["history_entrust_period"] if "history_entrust_period" in row.keys() else "当日",
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
    finally:
        conn.close()


def save_config(data: SystemConfigUpdate) -> SystemConfigDTO:
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = _get_conn()
    try:
        conn.execute(
            """
            UPDATE system_config
               SET ths_exe_path  = ?,
                   use_type_keys = ?,
                   grid_strategy = ?,
                   captcha_mode  = ?,
                   vlm_api_key   = ?,
                   captcha_auto_fail_threshold = ?,
                   schedule_enabled = ?,
                   schedule_weekdays = ?,
                   schedule_time_ranges = ?,
                   history_entrust_period = ?,
                   updated_at    = ?
             WHERE id = 1
            """,
            (
                data.ths_exe_path,
                int(data.use_type_keys),
                data.grid_strategy,
                data.captcha_mode,
                data.vlm_api_key,
                data.captcha_auto_fail_threshold,
                int(data.schedule_enabled),
                json.dumps(data.schedule_weekdays),
                json.dumps([r.model_dump() for r in data.schedule_time_ranges]),
                data.history_entrust_period,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return load_config()
