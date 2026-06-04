CREATE TABLE IF NOT EXISTS follow_config (
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
    updated_at                 TEXT    NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO follow_config (id) VALUES (1);

-- 幂等地为旧库追加新列（SQLite 不支持 IF NOT EXISTS on column）
-- 首次建库时这两列已存在，ALTER 对已有列会失败并被 executescript 忽略
-- 故通过独立事务处理（repository.py 的 _migrate 函数负责）

CREATE TABLE IF NOT EXISTS follow_records (
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
    status                TEXT    NOT NULL CHECK (status IN ('pending', 'success', 'warn', 'failed')),
    entrust_no            TEXT,
    error_code            TEXT,
    detail                TEXT,
    created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_records_signal_no
    ON follow_records(signal_entrust_no, action);
CREATE INDEX IF NOT EXISTS idx_follow_records_created_at
    ON follow_records(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_follow_records_stock_code
    ON follow_records(stock_code);
