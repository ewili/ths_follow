---
name: ths-follow-clear-logs-on-start
description: >-
  Deletes runtime log files under signal-server/logs and follow-client/logs
  before starting or restarting ths_follow services. Use when booting the
  project, restarting uvicorn, running start.bat, or any step in
  ths-follow-local-dev that starts backends—always run this first.
---

# 启动/重启前清空日志

双端日志目录（`settings.LOG_DIR`）：

| 端 | 目录 | 主文件 |
|----|------|--------|
| 喊单 | `signal-server/logs/` | `signal_server.log` |
| 跟单 | `follow-client/logs/` | `follow_client.log` |

`TimedRotatingFileHandler` 还会产生带日期后缀的备份（如 `signal_server.log.2026-06-04`），一并删除。

## 何时执行（强制）

在以下操作**之前**必须先清空日志，不得跳过：

- 首次启动或**重启**任一后端（uvicorn、`start.bat`、换端口后重开）
- 用户说「启动项目」「重启服务」「重新跑」等
- 按 **`ths-follow-local-dev`** 启动双端前的第一步

仅改前端 `npm run dev`、不启后端时**不必**清日志。

## 执行方式

在仓库根目录运行（Agent 必须用 Shell 实际执行，不要只口头说明）：

```powershell
Set-Location "D:\ewili\fileDoc\code\ths_follow"   # 改为本机仓库根路径
& ".cursor\skills\ths-follow-clear-logs-on-start\scripts\clear-logs.ps1"
```

无文件时提示 `No log files to remove`；有删除时列出路径。若日志被占用（后端仍在跑），脚本 exit 1 并提示先停 uvicorn——**清日志必须在停服之后、启服之前**。

## 不要删除

- `data/` 下 SQLite（`.db`）
- `python311/`、`web/dist/` 等（见规则 **`python-portable-runtime`**）

## 与 start.bat 的关系

各端 `start.bat`（若存在）可能已含清日志逻辑；Agent 用 uvicorn 或技能启动时**仍须**运行本脚本，保证与 bat 行为一致。
