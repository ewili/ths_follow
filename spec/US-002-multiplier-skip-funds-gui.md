# US-002: 倍数模式下跳过资金股票页 GUI 拉取

## 用户故事

作为 **跟单系统运维人员**，
我想要 **倍数模式下喊单端和跟单端都不去同花顺「资金股票」页面拉取不需要的资金数据**，
以便于 **真正减少 GUI 调用次数和验证码触发频率**，而非仅丢弃返回值却仍执行 GUI 操作。

## 背景与动机

US-001 实现了倍数模式，但在数据拉取层面存在遗漏：

1. **喊单端 `_get_or_fetch()` 无模式感知**：虽然 `get_entrusts()` 正确传了 `include_funds=False`，但 `_get_or_fetch()` 内部再次调用 `_ensure_snapshot_cached()` 时没传 `include_funds`，默认为 `True`，缓存过期后仍会切到资金股票页
2. **跟单端 `get_follow_snapshot()` 无条件拉资金股票页**：虽然 `_one_round()` 丢弃了 balance 返回值，但 `fetch_funds_stock()` 已经执行了 GUI 操作（切页 + Copy），白白浪费一次 GUI 调用

## 问题定位

### Bug 1：喊单端 `_get_or_fetch()` 无模式感知

**文件**：`signal-server/app/services/signal_service.py` 第 257-259 行

```python
async def _get_or_fetch(self, key, fetch_fn):
    if key in ("entrusts", "balance", "position"):
        include_entrusts = key == "entrusts"
        await self._ensure_snapshot_cached(include_entrusts=include_entrusts)
        # ☝️ 没传 include_funds！默认 True → 会拉资金股票页
```

虽然 `get_entrusts()` 第 385 行正确传了 `include_funds=False`：

```python
await self._ensure_snapshot_cached(include_entrusts=True, include_funds=False)
```

但紧接着第 386 行又调了 `_get_or_fetch("entrusts", ...)`，而 `_get_or_fetch` 内部的 `_ensure_snapshot_cached` 没传 `include_funds`，默认为 `True`，导致缓存 TTL 过期后仍会切到资金股票页。

### Bug 2：跟单端 `get_follow_snapshot()` 无条件拉资金股票页

**文件**：`follow-client/app/services/local_trader_service.py` 第 397-402 行

```python
def _snapshot() -> tuple[list[dict], list[dict], dict]:
    balance, positions = fetch_funds_stock(self._trader)  # ← 无条件切资金股票页
    entrusts = fetch_today_entrusts(self._trader)
    return positions, entrusts, balance
```

虽然 `follow_engine.py` 第 212-217 行倍数模式下丢弃了 balance：

```python
if self._follow_mode == "multiplier":
    local_positions, local_entrusts, _ = await trader.get_follow_snapshot()
    local_balance_dict = {}
```

但 GUI 操作已经执行了——`fetch_funds_stock` 已经切到了资金股票页。

## 验收标准

- [ ] 喊单端倍数模式下，`/api/signal/entrusts` 不触发 `fetch_funds_stock` GUI 调用，仅拉取当日委托
- [ ] 喊单端倍数模式下，`/api/signal/balance` 和 `/api/signal/positions` 手动请求仍正常拉取（符合 US-001 验收标准）
- [ ] 喊单端资金比例模式行为完全不变，无回归
- [ ] 跟单端倍数模式下，`get_follow_snapshot(include_balance=False)` 不缓存 balance 数据
- [ ] 跟单端倍数模式下，`local_follow_snapshot` 日志输出 `include_balance=False`
- [ ] 跟单端资金比例模式行为完全不变，无回归

## 技术方案

### Step 1: 喊单端 — `_get_or_fetch()` 增加模式感知

**文件**：`signal-server/app/services/signal_service.py`

**改动**：`_get_or_fetch()` 第 257-259 行

```python
# 改动前
if key in ("entrusts", "balance", "position"):
    include_entrusts = key == "entrusts"
    await self._ensure_snapshot_cached(include_entrusts=include_entrusts)

# 改动后
if key in ("entrusts", "balance", "position"):
    include_entrusts = key == "entrusts"
    include_funds = key in ("balance", "position")
    await self._ensure_snapshot_cached(
        include_entrusts=include_entrusts,
        include_funds=include_funds,
    )
```

**逻辑说明**：
- `key == "entrusts"` → `include_funds=False`，不拉资金股票页
- `key == "balance"` 或 `key == "position"` → `include_funds=True`，仍拉资金股票页（手动 API 请求需要）

**影响范围**：喊单端所有数据拉取路径
**风险**：低

### Step 2: 跟单端 — `get_follow_snapshot()` 增加 `include_balance` 参数

**文件**：`follow-client/app/services/local_trader_service.py`

**改动**：`get_follow_snapshot()` 方法签名和内部逻辑

```python
# 改动后
async def get_follow_snapshot(
    self,
    include_balance: bool = True,
) -> tuple[list[dict], list[dict], dict]:
    """单次锁内拉取持仓 + 当日委托（+可选资金），减少复制触发的验证码次数。

    返回 (positions, today_entrusts, balance)。
    include_balance=False 时跳过资金数据缓存，仍读持仓（卖出需可用股数）。
    """
    if self._is_schedule_paused():
        return [], [], {}
    self._require_trader()

    cache_keys = ("position", "entrusts", "balance") if include_balance else ("position", "entrusts")
    if all(self._cache_valid_key(k) for k in cache_keys):
        positions = self._cache["position"][1]
        entrusts = self._cache["entrusts"][1]
        balance = self._cache["balance"][1] if include_balance and self._cache_valid_key("balance") else {}
        return positions, entrusts, balance

    if include_balance:
        def _snapshot() -> tuple[list[dict], list[dict], dict]:
            from app.utils.ths_gui_fetch import fetch_funds_stock, fetch_today_entrusts
            balance, positions = fetch_funds_stock(self._trader)
            entrusts = fetch_today_entrusts(self._trader)
            return positions, entrusts, balance
    else:
        def _snapshot() -> tuple[list[dict], list[dict], dict]:
            from app.utils.ths_gui_fetch import fetch_funds_stock, fetch_today_entrusts
            _, positions = fetch_funds_stock(self._trader)
            entrusts = fetch_today_entrusts(self._trader)
            return positions, entrusts, {}

    positions, entrusts, balance = await self._run_blocking(
        _snapshot, "follow_snapshot"
    )
    expires = time.monotonic() + _TTL_SECONDS
    if include_balance and balance:
        self._cache["balance"] = (expires, balance)
    self._cache["position"] = (expires, positions)
    self._cache["entrusts"] = (expires, entrusts)
    logger.info(
        "event=local_follow_snapshot include_balance=%s cached position=%d entrusts=%d",
        include_balance, len(positions), len(entrusts),
    )
    return positions, entrusts, balance
```

**注意**：跟单端倍数模式仍需持仓数据（卖出时需知道可用股数），所以 `fetch_funds_stock` 仍需调用以切到资金股票页读持仓。跳过的只是 balance 的缓存写入。实际上 GUI 调用次数并没有减少——资金股票页和委托页各一次。真正的节省在于不缓存不用的 balance 数据，避免后续请求误用过期 balance。

**影响范围**：跟单端数据拉取
**风险**：中 — 需确保缓存逻辑正确

### Step 3: 跟单端 — `follow_engine.py` 倍数模式传 `include_balance=False`

**文件**：`follow-client/app/services/follow_engine.py`

**改动**：`_one_round()` 第 212-215 行

```python
# 改动前
if self._follow_mode == "multiplier":
    local_positions, local_entrusts, _ = (
        await trader.get_follow_snapshot()
    )

# 改动后
if self._follow_mode == "multiplier":
    local_positions, local_entrusts, _ = (
        await trader.get_follow_snapshot(include_balance=False)
    )
```

**影响范围**：跟单引擎轮询逻辑
**风险**：低 — 仅参数传递
**依赖**：Step 2

## 涉及文件

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `signal-server/app/services/signal_service.py` | 修改 | `_get_or_fetch()` 中根据 key 类型决定 `include_funds` |
| `follow-client/app/services/local_trader_service.py` | 修改 | `get_follow_snapshot()` 新增 `include_balance` 参数 |
| `follow-client/app/services/follow_engine.py` | 修改 | 倍数模式传 `include_balance=False` |

## 边界与异常场景

| 场景 | 处理方式 |
|------|----------|
| 喊单端倍数模式 + 手动请求 `/api/signal/balance` | `include_funds=True`，正常拉取 |
| 喊单端倍数模式 + 手动请求 `/api/signal/positions` | `include_funds=True`，正常拉取 |
| 喊单端倍数模式 + 跟单端请求 `/api/signal/entrusts` | `include_funds=False`，不拉资金股票页 |
| 跟单端倍数模式 + 卖出委托 | 仍拉持仓（`fetch_funds_stock` 读持仓），不缓存 balance |
| 缓存全命中（1s TTL 内） | 直接返回缓存，不触发任何 GUI 操作 |
| `include_balance=False` 但 balance 缓存已有值 | 不使用也不更新 balance 缓存 |

## 进一步优化（不在本次范围）

- 新增 `fetch_positions_only` 函数：不读 `_get_balance_from_statics()`，省去静态控件读取时间（约 0.1-0.3 秒），但切页和 Copy 仍需执行
- 跟单端倍数模式下持仓和委托分开拉取：分别走 `get_positions()` + `get_today_entrusts()` 独立缓存路径，但会增加锁获取次数

## 验证方案

1. **喊单端倍数模式**：启动喊单（倍数模式），跟单端请求 `/api/signal/entrusts`，观察日志应只有 `entrusts` 的 GUI 拉取，无 `funds_snapshot` 或 `fetch_funds_stock` 调用
2. **喊单端手动请求**：倍数模式下手动请求 `/api/signal/balance` 和 `/api/signal/positions`，应正常返回数据
3. **跟单端倍数模式**：启动跟单引擎（倍数模式），观察 `local_follow_snapshot` 日志应输出 `include_balance=False`
4. **跟单端资金比例模式**：功能不受影响，行为与修复前完全一致
