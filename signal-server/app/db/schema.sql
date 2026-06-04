CREATE TABLE IF NOT EXISTS system_config (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    ths_exe_path    TEXT    NOT NULL DEFAULT '',
    use_type_keys   INTEGER NOT NULL DEFAULT 0,
    grid_strategy   TEXT    NOT NULL DEFAULT 'Copy'
                    CHECK (grid_strategy IN ('Copy', 'Xls', 'WMCopy')),
    captcha_mode               TEXT    NOT NULL DEFAULT 'local'
                               CHECK (captcha_mode IN ('local', 'vlm', 'auto')),
    vlm_api_key                TEXT    NOT NULL DEFAULT '',
    captcha_auto_fail_threshold INTEGER NOT NULL DEFAULT 3
                               CHECK (captcha_auto_fail_threshold BETWEEN 1 AND 10),
    schedule_enabled           INTEGER NOT NULL DEFAULT 0,
    schedule_weekdays          TEXT    NOT NULL DEFAULT '',
    schedule_time_ranges       TEXT    NOT NULL DEFAULT '',
    history_entrust_period     TEXT    NOT NULL DEFAULT '当日'
                               CHECK (history_entrust_period IN ('当日', '近一周', '近一月', '近三月', '近一年')),
    updated_at                 TEXT    NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO system_config (id) VALUES (1);

CREATE TABLE IF NOT EXISTS stock_limit_prices (
    stock_code      TEXT    NOT NULL,
    stock_name      TEXT    NOT NULL DEFAULT '',
    close_price     REAL    NOT NULL,
    limitup_price   REAL    NOT NULL,
    limitdown_price REAL    NOT NULL,
    trade_date      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (stock_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_slp_trade_date ON stock_limit_prices (trade_date);
