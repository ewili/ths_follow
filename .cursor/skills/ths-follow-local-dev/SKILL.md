---
name: ths-follow-local-dev
description: >-
  Start, stop, and configure ths_follow locally (signal-server :8000,
  follow-client :8100, Vue web build, portable python311, THS xiadan connect).
  Use when the user asks to 启动项目, 停止项目, run dev servers, connect
  同花顺, or operate the Web/API without start.bat.
disable-model-invocation: true
---

# ths_follow 本地开发与启动

双端仓库：`signal-server/`（喊单）、`follow-client/`（跟单）。便携运行时与 ignore 约束见项目规则 **`python-portable-runtime`**。

## 前置

1. 各端目录下存在 `python311/python.exe`（未提交 Git；缺失时运行该端 `setup.bat`）。
2. **同花顺已启动并登录**（`hexin.exe` + `xiadan.exe` 在运行）。
3. 生产部署：两端应在**不同电脑**；本机同时跑双端仅用于开发联调。

## 启动后端

重启时必须严格按**三步序**执行，不可跳步：

1. **停旧进程** — 若端口 8000/8100 已被占用（`Get-Process python`），先 `Stop-Process` 结束旧 uvicorn，否则清日志会因文件被锁而失败。
2. **清日志** — 按项目 Skill **`ths-follow-clear-logs-on-start`** 执行 `scripts/clear-logs.ps1`（启动/重启必做）。
3. **启 uvicorn** — 在对应目录设置 `PYTHONPATH` 并用便携 Python 启动。

在对应目录设置 `PYTHONPATH` 为端目录根路径，用便携 Python 启动 uvicorn：

| 端 | 目录 | 端口 |
|----|------|------|
| 喊单 | `signal-server/` | 8000 |
| 跟单 | `follow-client/` | 8100 |

```powershell
Set-Location "D:\path\ths_follow\signal-server"
$env:PYTHONPATH = (Get-Location).Path
.\python311\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

跟单端将目录与端口改为 `follow-client`、`8100`。

也可双击各端 `start.bat`（通常也会清 `logs`；Agent 启动时仍应先跑 **`ths-follow-clear-logs-on-start`**）。

**端口占用**：先结束占用 8000/8100 的进程再重启，避免 `Errno 10048`。

## 停止后端

用户说「停止项目」「停服务」「关掉」时执行。

### 查找并终止 uvicorn 进程

```cmd
tasklist /FI "IMAGENAME eq python.exe" /FO TABLE
```

找到 PID 后逐个终止（**cmd 默认 shell 下 `&` 不能链式执行**，需逐条）

```cmd
taskkill /PID <PID1> /F
taskkill /PID <PID2> /F
```

### 验证已停止

```cmd
tasklist /FI "IMAGENAME eq python.exe" /FO TABLE
```

应返回「没有运行的任务匹配指定标准」。也可用便携 Python 探测端口：

```cmd
D:\path\ths_follow\signal-server\python311\python.exe -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/docs',timeout=3)" 2>nul && echo RUNNING || echo STOPPED
```

> **注意**：停止后端即可，不需要停同花顺（`xiadan.exe`/`hexin.exe`）。

## 前端 Web UI

`web/dist/` 不在 Git 中。根路径无 UI 时：

```powershell
Set-Location "...\signal-server\web"   # 或 follow-client\web
npm install
npm run build
```

构建完成后**重启**对应 uvicorn：`app.main` 在启动时检测 `web/dist` 才挂载静态资源。

开发模式（热更新）：`npm run dev` — 喊单 Vite `5173` 代理 `8000`，跟单 `5174` 代理 `8100`。

## 配置并连接同花顺（API）

从运行中的下单进程取路径（避免手输乱码）：

```powershell
$xiadan = (Get-Process xiadan -ErrorAction Stop | Select-Object -First 1).Path
```

**喊单端** — 先保存再连接：

```powershell
$body = @{
  ths_exe_path = $xiadan
  use_type_keys = $false
  grid_strategy = "Copy"
  captcha_mode = "local"
  history_entrust_period = "当日"
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/system/config" -Method PUT `
  -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/system/connect" -Method POST -TimeoutSec 120
```

**跟单端** — 保存配置（含喊单地址）后连接本地终端：

```powershell
$body = @{
  signal_server_url = "http://127.0.0.1:8000"
  poll_interval_ms = 500
  local_ths_exe_path = $xiadan
  grid_strategy = "Copy"
  history_entrust_period = "当日"
  entrust_source = "today"
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:8100/api/config" -Method PUT `
  -ContentType "application/json; charset=utf-8" `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
Invoke-RestMethod -Uri "http://127.0.0.1:8100/api/config/connectivity" -Method POST `
  -ContentType "application/json" -Body '{"signal_server_url":"http://127.0.0.1:8000"}'
Invoke-RestMethod -Uri "http://127.0.0.1:8100/api/trader/connect" -Method POST -TimeoutSec 120
```

连接成功：`GET .../api/system/config` 或仪表盘 `status.connection.state` 为 `connected`。

## 股票行情采集

`POST /api/stock/fetch` 在工作日 **15:00 前**会拒绝（盘中价算涨跌停不准确）。收盘后或周末可手动触发；表空时委托相关接口可能为空。

## 验证

| 检查 | URL |
|------|-----|
| 喊单 Web / API | http://127.0.0.1:8000/ 、/docs |
| 跟单 Web / API | http://127.0.0.1:8100/ 、/docs |
| 仪表盘状态 | `GET /api/system/status` |

**验证服务是否启动**（默认 shell 为 cmd 时，**不要用** `powershell -Command` 内联验证，`$r`/`$_.Exception` 等变量会被 cmd 吞掉导致语法错误）：

优先使用便携 Python（系统 PATH 可能无 Python）：

```cmd
D:\path\ths_follow\signal-server\python311\python.exe -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/docs',timeout=5); print('signal-server:', r.status); r=urllib.request.urlopen('http://127.0.0.1:8100/docs',timeout=5); print('follow-client:', r.status)"
```

若系统 PATH 有 Python 也可简写为 `python -c ...`。

返回 `200` 即服务正常。PowerShell 交互式会话中 `Invoke-WebRequest` 仍可用。

喊单引擎默认 `stopped`，需在 Web「喊单控制」或对应 API 手动启动。

## Windows PowerShell

本机默认 shell 可能不支持 `&&`；链式命令用 `;` 或分行执行。`&` 在 PowerShell 中报「不允许使用与号」，多条命令必须逐条执行。见全局规则 **`agent-workflow`**。

### cmd 下调用 PowerShell 的陷阱

默认 shell 为 `cmd.exe` 时，`powershell -Command "..."` 内联命令频繁出问题：

- `$env:PYTHONPATH`、`$body` 等 `$` 变量可能被 cmd 吞掉或误解析
- `| ConvertTo-Json` 等管道元素在分号 `;` 后可能报「不允许使用空管道元素」
- `ConvertTo-Json` 对中文输出编码不正确，终端显示乱码

**解决**：将多行脚本写入 `.ps1` 文件，用 `powershell -ExecutionPolicy Bypass -File "xxx.ps1"` 执行。调用 API 测试时优先用 Python 脚本（`urllib.request` + `json`），可正确处理 UTF-8 中文。
