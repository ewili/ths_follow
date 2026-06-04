# 📋 执行计划 — US-001: 喊单/跟单倍数模式

> 关联用户故事：[US-001-multiplier-follow-mode.md](./US-001-multiplier-follow-mode.md)

## 目标

在喊单端和跟单端增加"倍数模式"作为跟单方式的替代选项，使跟单端可直接以 `喊单手数 × 倍数` 进行跟单，无需拉取资金数据，减少 GUI 调用和验证码触发。

## 现状分析

- **当前仅支持资金比例模式**：喊单端 `SignalService.get_entrusts()` 会同时拉取 balance + position + entrusts 三类数据来计算 `cash_ratio` / `position_ratio`
- **跟单端 `FollowEngine._one_round()`** 每轮都调用 `trader.get_follow_snapshot()` 拉取本地 balance + position + entrusts
- **`SignalRuntimeService`** 仅管理 `state/started_at/last_changed_at/schedule_active`，无模式概念
- **`FollowAction`** dataclass 仅有 `signal_cash_ratio` / `signal_position_ratio`，无 multiplier 信息
- **`order_executor`** 仅有 `_calc_buy_qty_ratio` 和 `_calc_sell_qty_by_position_ratio` 两个计算函数
- **`follow_records` 表** 当前迁移代码会**主动删除** `follow_mode`/`follow_multiplier` 列（见 `follow-client/app/db/repository.py:24-89`），需要调整迁移逻辑

## 关键发现与注意事项

1. **`follow_records` 迁移逻辑冲突**：当前 `follow-client/app/db/repository.py:24-89` 的 `_migrate()` 会**主动重建** `follow_records` 表并丢弃 `follow_mode`/`follow_multiplier` 列。Step 5 必须修改此逻辑，改为保留这两列。
2. **`SignalEntrustDTO.entrust_qty` 已存在**：用户故事中提到"新增 `entrust_qty` 字段"，但该字段在喊单端和跟单端的 DTO 中均已存在，无需新增。
3. **`_ensure_snapshot_cached` 是关键适配点**：喊单端 `SignalService._ensure_snapshot_cached()` 目前总是拉取 balance+position，倍数模式下需要条件跳过。
4. **跟单端本地拉取策略**：倍数模式下跟单端仍需拉取本地持仓（卖出需知道可用股数），但**不拉 balance**。`trader.get_follow_snapshot()` 需支持参数控制是否拉 balance。

## 执行步骤

### Step 1: 喊单端 — 数据模型与持久化层

- **操作**：
  1. `signal-server/app/models/config.py`：`SystemConfigDTO` 和 `SystemConfigUpdate` 新增 `signal_mode: Literal["ratio", "multiplier"] = "ratio"` 字段
  2. `signal-server/app/db/schema.sql`：`system_config` 表新增 `signal_mode TEXT NOT NULL DEFAULT 'ratio' CHECK (signal_mode IN ('ratio', 'multiplier'))` 列
  3. `signal-server/app/db/repository.py`：`_migrate()` 中追加 `signal_mode` 列迁移；`load_config()` / `save_config()` 适配新字段
- **涉及文件**: `signal-server/app/models/config.py`, `signal-server/app/db/schema.sql`, `signal-server/app/db/repository.py`
- **影响范围**: 喊单端配置读写
- **风险**: 低 — 遵循已有迁移模式，新字段有默认值 `ratio`
- **依赖**: 无

### Step 2: 喊单端 — 运行态管理 + 模式接口

- **操作**：
  1. `signal-server/app/models/system_status.py`：`SignalRuntimeStatus` 新增 `signal_mode: Literal["ratio", "multiplier"] = "ratio"` 字段；新增 `SignalModeResponse` 模型
  2. `signal-server/app/services/signal_runtime_service.py`：`__init__` 新增 `_signal_mode` 属性；`start()` 接收 `signal_mode` 参数并记录；`get_status()` 返回模式信息；新增 `get_mode()` 方法
  3. `signal-server/app/api/signal.py`：新增 `GET /api/signal/mode` 端点返回当前模式；`POST /api/signal/start` 接收 `signal_mode` 参数
- **涉及文件**: `signal-server/app/models/system_status.py`, `signal-server/app/services/signal_runtime_service.py`, `signal-server/app/api/signal.py`
- **影响范围**: 喊单端启停逻辑、状态查询
- **风险**: 低 — 新增字段不影响现有逻辑
- **依赖**: Step 1

### Step 3: 喊单端 — SignalService 倍数模式适配

- **操作**：
  1. `signal-server/app/services/signal_service.py`：
     - `get_entrusts()` 方法：倍数模式下跳过 balance/position 拉取和 ratio 计算，`cash_ratio`/`position_ratio` 返回 `None`
     - `_build_entrust_dto()` 函数：新增 `signal_mode` 参数，倍数模式下跳过 ratio 计算
     - `_assemble_valid_entrust_dtos()` 函数：透传 `signal_mode`
  2. `signal-server/app/api/signal.py`：`get_entrusts()` 中传入模式信息；降级缓存回退时也需适配
- **涉及文件**: `signal-server/app/services/signal_service.py`, `signal-server/app/api/signal.py`
- **影响范围**: 喊单端委托数据组装逻辑（核心路径）
- **风险**: 中 — 需确保 ratio 模式完全不变；倍数模式下 `cash_ratio`/`position_ratio` 必须 `null`；`entrust_qty` 字段已有，无需新增
- **依赖**: Step 2

### Step 4: 喊单端前端 — 模式选择控件

- **操作**：
  1. `signal-server/web/src/types/config.ts`：新增 `SignalMode` 类型和 `signal_mode` 字段
  2. `signal-server/web/src/types/signal.ts`（如存在）：`SignalRuntimeStatus` 新增 `signal_mode` 字段
  3. `signal-server/web/src/components/SignalControl.vue`：新增模式选择 Radio/Select 控件；运行中禁用模式切换；启动时传递 `signal_mode` 参数
  4. `signal-server/web/src/api/signal.ts`：`startSignal()` 接收 `signalMode` 参数
- **涉及文件**: `signal-server/web/src/types/config.ts`, `signal-server/web/src/components/SignalControl.vue`, `signal-server/web/src/api/signal.ts`, 可能还有 `signal-server/web/src/types/signal.ts`
- **影响范围**: 喊单端前端 UI
- **风险**: 低
- **依赖**: Step 2

### Step 5: 跟单端 — 数据模型与持久化层

- **操作**：
  1. `follow-client/app/models/config.py`：`FollowConfigDTO` 和 `FollowConfigUpdate` 新增 `follow_mode: Literal["ratio", "multiplier"] = "ratio"` 和 `follow_multiplier: float = 1.0` 字段；`follow_multiplier` 增加范围校验 `Field(1.0, ge=0.1, le=100)`
  2. `follow-client/app/db/schema.sql`：`follow_config` 表新增 `follow_mode` 和 `follow_multiplier` 列；`follow_records` 表新增 `follow_mode` 和 `follow_multiplier` 列
  3. `follow-client/app/db/repository.py`：
     - **关键**：修改 `_migrate()` 中 `follow_records` 的重建逻辑——**不再删除** `follow_mode`/`follow_multiplier` 列，改为保留并添加
     - `load_config()` / `save_config()` 适配新字段
     - `insert_follow_record()` 适配新字段
- **涉及文件**: `follow-client/app/models/config.py`, `follow-client/app/db/schema.sql`, `follow-client/app/db/repository.py`
- **影响范围**: 跟单端配置读写 + 跟单记录写入
- **风险**: 中 — 需修改 `follow_records` 迁移逻辑，当前代码会删除 `follow_mode`/`follow_multiplier` 列，必须改为保留
- **依赖**: 无

### Step 6: 跟单端 — FollowAction 与 DTO 适配

- **操作**：
  1. `follow-client/app/models/follow.py`：
     - `FollowAction` dataclass 新增 `follow_mode: Literal["ratio", "multiplier"] = "ratio"` 和 `follow_multiplier: float = 1.0` 字段
     - `FollowStatusResponse` 新增 `follow_mode` 和 `follow_multiplier` 字段
     - `FollowRecordItem` 新增 `follow_mode` 和 `follow_multiplier` 字段
  2. `follow-client/app/services/signal_client.py`：新增 `fetch_signal_mode()` 函数，调用 `GET /api/signal/mode`
- **涉及文件**: `follow-client/app/models/follow.py`, `follow-client/app/services/signal_client.py`
- **影响范围**: 跟单指令数据模型 + 喊单端模式查询
- **风险**: 低
- **依赖**: Step 2 (需要喊单端 `/api/signal/mode` 接口)

### Step 7: 跟单端 — 引擎与对比逻辑适配

- **操作**：
  1. `follow-client/app/services/follow_engine.py`：
     - `start()` 新增模式校验——调用 `signal_client.fetch_signal_mode()` 检查与本地 `follow_mode` 是否匹配，不匹配则抛出异常
     - `_one_round()` 新增每轮模式一致性校验，不匹配则自动 `stop()`
     - 倍数模式下不拉取 `local_balance_dict`（但需拉本地持仓用于卖出）
     - 传递 `follow_mode`/`follow_multiplier` 到 `comparator` 和 `order_executor`
  2. `follow-client/app/services/comparator.py`：`compare_and_decide()` 新增 `follow_mode`/`follow_multiplier` 参数，生成 `FollowAction` 时携带
  3. `follow-client/app/services/order_executor.py`：
     - 新增 `_calc_buy_qty_multiplier(multiplier, entrust_qty)` 函数：`floor(entrust_qty × multiplier / 100) × 100`，最小 100
     - 新增 `_calc_sell_qty_multiplier(multiplier, entrust_qty, available_qty)` 函数：`min(floor(entrust_qty × multiplier / 100) × 100, available_qty)`，不足 100 股全部卖出
     - `execute_buy()` / `execute_sell()` 根据 `action.follow_mode` 选择计算方式
     - `_write_record()` 新增 `follow_mode`/`follow_multiplier` 字段写入
  4. `follow-client/app/api/follow.py`：`start_follow()` 接口新增模式校验逻辑
- **涉及文件**: `follow-client/app/services/follow_engine.py`, `follow-client/app/services/comparator.py`, `follow-client/app/services/order_executor.py`, `follow-client/app/api/follow.py`
- **影响范围**: 跟单核心业务逻辑（最高风险路径）
- **风险**: 高 — 跟单引擎是核心循环，需确保 ratio 模式完全不受影响
- **依赖**: Step 5, Step 6

### Step 8: 跟单端前端 — 模式选择与倍数输入

- **操作**：
  1. `follow-client/web/src/types/config.ts`：新增 `FollowMode` 类型和 `follow_mode`/`follow_multiplier` 字段
  2. `follow-client/web/src/types/follow.ts`（如存在）：`FollowStatusResponse` 新增字段
  3. `follow-client/web/src/components/FollowConfigPanel.vue`：新增"跟单模式"选择（Radio: 资金比例/倍数）和"跟单倍数"输入框（0.1~100，step=0.1）；跟单引擎运行时禁用
  4. `follow-client/web/src/components/FollowControlPanel.vue`：显示当前模式和倍数；引擎运行时禁用配置
  5. `follow-client/web/src/api/follow.ts`：`startFollow()` 可选传递模式参数
- **涉及文件**: `follow-client/web/src/types/config.ts`, `follow-client/web/src/components/FollowConfigPanel.vue`, `follow-client/web/src/components/FollowControlPanel.vue`, `follow-client/web/src/api/follow.ts`, 可能还有 `follow-client/web/src/types/follow.ts`
- **影响范围**: 跟单端前端 UI
- **风险**: 低
- **依赖**: Step 5, Step 7

### Step 9: 前端构建 + 端到端联调验证

- **操作**：
  1. 喊单端 `npm install && npm run build`
  2. 跟单端 `npm install && npm run build`
  3. 重启双端服务
  4. 验证 ratio 模式无回归
  5. 验证 multiplier 模式全流程
- **涉及文件**: 无新增，构建已有前端
- **影响范围**: 运行时验证
- **风险**: 低
- **依赖**: Step 4, Step 8

## 不在本次范围

- 不改变现有资金比例模式的任何行为
- 不实现按品种/合约分别设置倍数（全局一个值）
- 不处理模式切换对已有持仓的自动对齐
- 不修改 easytrader 底层交互逻辑
- 不修改 `easytrader_copy_patch.py` / `errors.py`（非 THS 交互层变更）

## 验证方案

- **Step 1-2 验证**：启动喊单端，确认 `GET /api/signal/mode` 返回 `ratio`（默认值）
- **Step 3 验证**：切换为 multiplier 模式后，`GET /api/signal/entrusts` 返回的 `cash_ratio`/`position_ratio` 为 `null`，且不触发 balance/position GUI 拉取（观察日志）
- **Step 5 验证**：跟单端配置接口能保存/读取 `follow_mode`/`follow_multiplier`
- **Step 7 验证**：
  - 倍数 1.5，喊单买入 300 股 → 跟单买入 400 股 ✅
  - 倍数 2.0，喊单卖出 1000 股，本地可用 1500 → 跟单卖出 1500 股 ✅
  - 两端模式不匹配 → 启动被拒绝 ✅
  - 运行中模式变更 → 跟单引擎自动停止 ✅
- **回归验证**：ratio 模式下所有现有行为不变
