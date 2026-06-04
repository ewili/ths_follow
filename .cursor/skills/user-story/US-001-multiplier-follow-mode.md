# US-001: 喊单/跟单倍数模式

## 用户故事

作为 **跟单系统运维人员**，
我想要 **在喊单端和跟单端增加"倍数模式"作为跟单方式的替代选项**，
以便于 **在不需要同花顺账户资金数据的情况下，直接以喊单手数乘以倍数进行跟单，减少 GUI 调用次数和验证码触发**。

## 背景与动机

当前系统仅支持**资金比例模式**：喊单端计算 `cash_ratio = 委托价 × 委托量 / 总资产`，跟单端用 `ratio × 本地总资产 / 涨停价` 计算跟单买入股数。此模式存在以下痛点：

1. **依赖资金数据**：每次获取委托必须同时拉取 `balance + position + entrusts` 三类数据，倍数模式下仅需要 `entrusts`，可减少 2/3 的 GUI 调用
2. **验证码恶性循环**：GUI 操作频繁触发 THS 验证码弹窗，减少 GUI 调用能大幅降低验证码频率
3. **场景不匹配**：部分用户希望简单直接地以"喊单手数 × N 倍"方式跟单，不需要资金比例换算

## 功能描述

### 核心流程

1. **喊单端**：在配置/启动界面增加"喊单模式"选择（`ratio` 资金比例 / `multiplier` 倍数），启动时选定，运行中不可修改
2. **喊单端**：倍数模式下，`/api/signal/entrusts` 和 `/api/signal/history-entrusts-dto` 接口不再计算 `cash_ratio` / `position_ratio`（返回 `null`），不再拉取 balance 和 position 数据，仅拉取 entrusts；接口新增 `entrust_qty` 字段（原始委托股数，已有字段直接暴露）
3. **喊单端**：新增 `/api/signal/mode` 接口，返回当前喊单模式，供跟单端启动时校验
4. **跟单端**：在配置界面增加"跟单模式"选择（`ratio` 资金比例 / `multiplier` 倍数）和"跟单倍数"输入框（0.1~100，允许小数），启动时选定，运行中不可修改
5. **跟单端**：强制两端模式一致——启动跟单引擎时调用 `/api/signal/mode` 校验跟单端模式必须与喊单端模式匹配，不匹配则拒绝启动并提示
6. **跟单端**：跟单引擎运行中每轮校验模式一致性，发现不匹配则**自动停止**
7. **跟单端**：倍数模式下，买入股数 = `喊单买入股数 × 倍数`，向下取整到 100 整数倍，不足 100 股按 100 股；卖出股数 = `喊单卖出股数 × 倍数`，向下取整到 100 整数倍，但不超过本地可用持仓

### 交互细节

| 触发条件 | 操作 | 期望结果 |
|----------|------|----------|
| 喊单端配置页面 | 选择"倍数模式"并启动喊单 | entrusts 接口仅拉委托数据，cash_ratio/position_ratio 为 null |
| 喊单端配置页面 | 选择"资金比例模式"并启动喊单 | 行为与现有完全一致 |
| 跟单端配置页面 | 选择"倍数模式"，输入倍数（如 2.0） | 保存到 follow_config 表 |
| 跟单端启动跟单引擎 | 跟单模式=multiplier，但喊单端=ratio | 拒绝启动，提示"喊单端为资金比例模式，请切换为资金比例模式或联系喊单端切换" |
| 跟单端倍数模式收到买单 | 喊单买入 300 股，倍数 1.5 | 300 × 1.5 = 450，向下取整到 400 股 |
| 跟单端倍数模式收到卖单 | 喊单卖出 1000 股，倍数 2.0，本地可用 1500 | min(1000 × 2 = 2000, 1500) = 1500 股全部卖出 |
| 运行中尝试修改模式 | 修改配置中的模式字段 | 前端禁用模式切换控件（需先停止引擎） |
| 跟单引擎运行中，喊单端重启切换模式 | 跟单引擎检测到模式不匹配 | 跟单引擎自动停止，前端显示"喊单端模式已变更，跟单已自动停止" |

## 验收标准

- [ ] 喊单端倍数模式下，`/api/signal/entrusts` 不触发 balance/position 的 GUI 拉取，仅拉取 entrusts
- [ ] 喊单端倍数模式下，DTO 的 `cash_ratio` 和 `position_ratio` 为 `null`
- [ ] 喊单端倍数模式下，`/api/signal/balance` 和 `/api/signal/positions` 接口仍可用（手动请求时正常拉取），但跟单引擎不再调用
- [ ] 喊单端新增 `/api/signal/mode` 接口，返回当前模式（`ratio` / `multiplier`）
- [ ] 跟单端倍数模式下，买入股数 = `floor(entrust_qty × multiplier / 100) × 100`，最小 100 股
- [ ] 跟单端倍数模式下，卖出股数 = `min(floor(entrust_qty × multiplier / 100) × 100, available_qty)`，不足 100 股时全部卖出
- [ ] 跟单端倍数模式下，不拉取本地 balance 数据（total_assets 不再使用），但仍拉取本地持仓（卖出需知道可用股数）
- [ ] 两端模式不匹配时，启动跟单引擎返回错误提示
- [ ] 跟单引擎运行中检测到模式不匹配时，自动停止并提示
- [ ] 跟单引擎运行时，前端禁用模式切换和倍数修改
- [ ] 倍数取值范围 0.1~100，支持小数（精度 1 位小数）
- [ ] 资金比例模式的行为与现有完全一致，无回归
- [ ] 跟单记录表中新增 follow_mode 和 follow_multiplier 字段记录跟单模式

## 边界与异常场景

| 场景 | 处理方式 |
|------|----------|
| 倍数 0.1，喊单买入 100 股 → 计算 10 股 | 向下取整为 0，兜底按 100 股下单（与现有 ratio 模式兜底一致） |
| 倍数模式下，喊单端 entrusts 返回空列表 | 正常处理，本轮无跟单动作 |
| 倍数模式下，喊单端 cash_ratio/position_ratio 为 null | 跟单端忽略这两个字段，直接使用 entrust_qty |
| 跟单引擎启动时无法获取喊单端模式（网络异常） | 拒绝启动，提示"无法获取喊单端模式，请检查网络连接" |
| 模式切换后，已有持仓/委托记录 | 切换模式不影响历史记录，新记录使用新模式标记 |
| 喊单端中途停止后切换模式重启 | 跟单引擎下轮检测到模式不匹配，自动停止 |
| 倍数模式下卖出，计算值超过本地可用持仓 | 取 min(计算值, 可用持仓)，如可用持仓不足 100 股则全部卖出 |

## 技术方案

### 涉及端

- [x] 喊单端 (signal-server)
- [x] 跟单端 (follow-client)

### 影响文件

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| **喊单端** | | |
| `signal-server/app/models/config.py` | 修改 | `SystemConfigDTO`/`SystemConfigUpdate` 新增 `signal_mode: Literal["ratio", "multiplier"]` 字段 |
| `signal-server/app/db/schema.sql` | 修改 | `system_config` 表新增 `signal_mode` 列 |
| `signal-server/app/db/repository.py` | 修改 | `load_config` / `save_config` 适配新字段，迁移逻辑 |
| `signal-server/app/services/signal_service.py` | 修改 | `get_entrusts()` 在 multiplier 模式下跳过 balance/position 拉取和 ratio 计算 |
| `signal-server/app/api/signal.py` | 修改 | 新增 `/api/signal/mode` 端点；`/start` 接收模式参数 |
| `signal-server/app/models/system_status.py` | 修改 | 新增 `SignalModeResponse` 模型 |
| `signal-server/app/services/signal_runtime_service.py` | 修改 | 启动时记录模式，运行中不可修改；`get_status` 返回模式 |
| `signal-server/web/src/types/config.ts` | 修改 | 新增 `SignalMode` 类型和 `signal_mode` 字段 |
| `signal-server/web/src/components/SignalControl.vue` | 修改 | 新增模式选择控件（运行时禁用） |
| **跟单端** | | |
| `follow-client/app/models/config.py` | 修改 | `FollowConfigDTO`/`FollowConfigUpdate` 新增 `follow_mode` 和 `follow_multiplier` 字段 |
| `follow-client/app/db/schema.sql` | 修改 | `follow_config` 表新增 `follow_mode`、`follow_multiplier` 列 |
| `follow-client/app/db/repository.py` | 修改 | `load_config` / `save_config` 适配新字段，迁移逻辑 |
| `follow-client/app/models/follow.py` | 修改 | `FollowStatusResponse` 新增 `follow_mode` 和 `follow_multiplier`；`FollowAction` 新增 `follow_mode` 和 `follow_multiplier` 字段 |
| `follow-client/app/services/follow_engine.py` | 修改 | 启动时校验模式匹配；运行中每轮校验，不匹配则自动停止；倍数模式下不拉 balance，传递模式到 comparator/order_executor |
| `follow-client/app/services/comparator.py` | 修改 | `compare_and_decide` 签名新增 `follow_mode` 参数，倍数模式时 FollowAction 携带 multiplier 信息 |
| `follow-client/app/services/order_executor.py` | 修改 | 新增 `_calc_buy_qty_multiplier` 和 `_calc_sell_qty_multiplier` 函数，根据模式选择计算方式 |
| `follow-client/app/services/signal_client.py` | 修改 | 新增 `fetch_signal_mode()` 函数，调用 `/api/signal/mode` 获取喊单端模式 |
| `follow-client/app/api/follow.py` | 修改 | `/start` 接口新增模式匹配校验逻辑 |
| `follow-client/app/db/repository.py` | 修改 | `follow_records` 表新增 `follow_mode` 和 `follow_multiplier` 列，写入记录时携带 |
| `follow-client/web/src/types/config.ts` | 修改 | 新增 `FollowMode` 类型和 `follow_mode`/`follow_multiplier` 字段 |
| `follow-client/web/src/components/FollowConfigPanel.vue` | 修改 | 新增模式选择和倍数输入控件 |
| `follow-client/web/src/components/FollowControlPanel.vue` | 修改 | 显示当前模式/倍数，运行时禁用配置 |

### 数据流

**资金比例模式（现有，不变）：**
```
喊单端: entrusts API → balance + position + entrusts GUI拉取 → 计算 cash_ratio/position_ratio → 返回 DTO
跟单端: signal_client 拉取 → comparator 生成 FollowAction(cash_ratio) → order_executor 用 ratio × total_assets 计算股数
```

**倍数模式（新增）：**
```
喊单端: entrusts API → 仅 entrusts GUI拉取 → cash_ratio/position_ratio=null → 返回 DTO（含 entrust_qty）
跟单端: signal_client 拉取 → 校验模式匹配 → comparator 生成 FollowAction(multiplier) → order_executor 用 entrust_qty × multiplier 计算股数
```

**模式校验：**
```
跟单端启动时: signal_client.fetch_signal_mode() → GET /api/signal/mode → 校验与本地 follow_mode 是否一致
跟单引擎每轮: _one_round 中调用 signal_client.fetch_signal_mode() 校验 → 不匹配则自动停止
```

### 现有架构适配

- **单例 Service 模式**：`SignalService.get()` / `FollowEngine.get()` 保持不变，模式作为 Service 内部状态管理
- **TTL 缓存策略**：倍数模式下 SignalService 的 balance/position 缓存不再主动填充，但缓存机制本身不变
- **THS GUI 互斥**：`with_lock()` 机制不变，只是倍数模式下调用量减少
- **配置持久化**：新增字段走现有 `load_config` / `save_config` + SQLite 迁移模式
- **跟单记录**：新增 `follow_mode` / `follow_multiplier` 字段记录，与现有 `signal_ratio` 字段互斥填充
- **前端禁用**：运行时禁用模式切换控件，复用现有的 `isRunning` 状态判断

## 不在范围内

- 不改变现有资金比例模式的任何行为
- 不实现按品种/合约分别设置倍数（全局一个值）
- 不处理模式切换对已有持仓的自动对齐（用户自行决策）
- 不修改 easytrader 底层交互逻辑（仅调整 Service 层调用策略）

## 依赖与风险

| 项目 | 说明 |
|------|------|
| 依赖 | 喊单端需新增 `/api/signal/mode` 端点供跟单端启动时和运行中校验 |
| 风险 | 喊单端中途停止后切换模式重启，跟单引擎会自动停止；用户需手动重启跟单引擎并确认模式匹配 |
| 兼容性 | 新增字段均有默认值（`ratio`），旧版跟单端对接新版喊单端时自动降级为比例模式 |
