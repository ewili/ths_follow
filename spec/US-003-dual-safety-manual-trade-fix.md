# US-003: 双重保险区分手动委托与跟单委托

## 用户故事

作为 **跟单系统运维人员**，
我想要 **跟单引擎的双重保险逻辑只匹配跟单系统自己下的委托，不误判用户手动交易的委托**，
以便于 **手动交易不会遮挡同股票同方向的跟单信号，避免漏单**。

## 背景与动机

`comparator.py` 步骤 2（买入）和步骤 3（卖出）各有"双重保险"逻辑，按 **股票代码 + 方向 + 非终态** 模糊匹配本地委托，无法区分"跟单系统下的委托"和"用户手动下的委托"。

### 实际日志

```
2026-06-05 17:04:09 WARNING [app.services.comparator] local_buy_exists_but_no_record stock=002636 signal_no=24132 local_no=1074733
2026-06-05 17:04:09 WARNING [app.services.comparator] local_buy_exists_but_no_record stock=000070 signal_no=13948 local_no=696178
2026-06-05 17:04:09 WARNING [app.services.comparator] local_buy_exists_but_no_record stock=002636 signal_no=8829 local_no=1074733
```

用户手动买入 002636（合同编号 1074733）后，同股票同方向的所有跟单信号都被跳过，且每轮循环都打印 WARNING。

### 根因分析

`_find_local_entrust()` 按 `stock_code + direction + 非终态` 模糊匹配，命中了手动委托，导致 `continue` 跳过跟单。而 `follow_records` 表中 `entrust_no` 列记录了跟单系统成功下单的合同编号，是区分跟单委托与手动委托的关键。

## 问题定位

### Bug：双重保险无法区分手动委托

**文件**：`follow-client/app/services/comparator.py` 第 154-167 行（买入）和第 200-209 行（卖出）

买入双重保险（第 154-167 行）：

```python
# 双重保险：本地已有匹配买单且未撤，跳过（防止崩溃后重复下单）
local_buy = _find_local_entrust(
    local_entrusts,
    stock_code=sig.stock_code,
    direction="买入",
    exclude_statuses=_SETTLED_STATUSES,
)
if local_buy:
    local_no = str(local_buy.get(_KEY_ENTRUST_NO, ""))
    logger.warning(
        "local_buy_exists_but_no_record stock=%s signal_no=%s local_no=%s",
        sig.stock_code, sig.entrust_no, local_no
    )
    continue  # ← 手动委托也会触发跳过，导致漏单
```

卖出双重保险（第 200-209 行）同理：

```python
# 双重保险：本地已有匹配卖单且未撤，跳过
local_sell = _find_local_entrust(
    local_entrusts,
    stock_code=sig.stock_code,
    direction="卖出",
    exclude_statuses={"已撤", "部撤"},
)
if local_sell:
    logger.debug("local_sell_exists skip stock=%s", sig.stock_code)
    continue  # ← 手动卖单也会触发跳过
```

## 修复方案

### 核心思路

双重保险改为"从 `follow_records` 中取当日已成功的 `entrust_no` 集合，只在本地委托中检查这些跟单系统委托是否仍存在且未终态"，手动委托因不在 `follow_records` 中而被忽略。

### Step 1: 新增 `repository.get_today_successful_entrust_nos()`

**文件**：`follow-client/app/db/repository.py`

新增方法，查询当日所有 `status='success'` 且 `action IN ('buy','sell')` 的 `entrust_no` 及其 `stock_code`，返回 `dict[str, str]`（entrust_no → stock_code 映射）。

```python
def get_today_successful_entrust_nos() -> dict[str, str]:
    """返回当日所有成功跟随的本地委托编号映射（entrust_no → stock_code）。"""
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
            """,
            (today,),
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    finally:
        conn.close()
```

返回 `dict[str, str]` 而非 `set[str]` 的原因：双重保险需要同时校验 entrust_no 和 stock_code，防止跨股票误判。

### Step 2: 修改 `compare_and_decide()` 签名和双重保险逻辑

**文件**：`follow-client/app/services/comparator.py`

1. 新增参数 `followed_entrust_nos: dict[str, str]`（entrust_no → stock_code 映射）
2. 步骤 2 买入双重保险：从 `local_entrusts` 中筛选 `合同编号 in followed_entrust_nos` 且同股票且方向为买入且非终态的委托
3. 步骤 3 卖出双重保险：同理改为合同编号精确匹配 + 同股票校验
4. 移除 `local_buy_exists_but_no_record` WARNING（手动委托不再误判）

修改后的买入双重保险：

```python
# 双重保险：跟单系统已下过且本地仍有未终态的买单 → 跳过（防止崩溃后重复下单）
# 只检查 follow_records 中已成功的委托，忽略用户手动交易的委托
local_buy = _find_followed_local_entrust(
    local_entrusts,
    followed_entrust_nos=followed_entrust_nos,
    stock_code=sig.stock_code,
    direction="买入",
    exclude_statuses=_SETTLED_STATUSES,
)
if local_buy:
    local_no = str(local_buy.get(_KEY_ENTRUST_NO, ""))
    logger.debug(
        "local_buy_exists_in_follow_records stock=%s signal_no=%s local_no=%s",
        sig.stock_code, sig.entrust_no, local_no
    )
    continue
```

新增辅助函数 `_find_followed_local_entrust()`：

```python
def _find_followed_local_entrust(
    local_entrusts: list[dict],
    followed_entrust_nos: dict[str, str],  # entrust_no → stock_code
    stock_code: str,
    direction: str,
    exclude_statuses: set[str],
) -> Optional[dict]:
    """在本地当日委托中找匹配的跟单系统委托（合同编号 + 同股票 + 方向 + 非终态）。"""
    for e in local_entrusts:
        no = str(e.get(_KEY_ENTRUST_NO, e.get("entrust_no", "")))
        raw_dir = str(e.get(_KEY_DIRECTION, e.get("direction", "")))
        status = _normalize_status(str(e.get(_KEY_STATUS, e.get("status", ""))))
        matched_stock = followed_entrust_nos.get(no)
        if (
            matched_stock is not None
            and matched_stock == stock_code
            and _local_direction(raw_dir) == direction
            and status not in exclude_statuses
        ):
            return e
    return None
```

### Step 3: 在 `follow_engine._one_round()` 中调用新方法并传参

**文件**：`follow-client/app/services/follow_engine.py`

在 `comparator.compare_and_decide()` 调用前查询并传入：

```python
# 3. 对比决策
followed_entrust_nos = repository.get_today_successful_entrust_nos()
actions = comparator.compare_and_decide(
    signal_entrusts=signal_entrusts,
    local_positions=local_positions,
    local_entrusts=local_entrusts,
    has_followed=repository.has_followed,
    start_timestamp=self._start_timestamp,
    follow_mode=self._follow_mode,
    follow_multiplier=self._follow_multiplier,
    followed_entrust_nos=followed_entrust_nos,
)
```

### Step 4: 调整日志

- 移除 `local_buy_exists_but_no_record` WARNING（此场景不再出现）
- 跟单委托仍在本地未终态时，用 DEBUG 级别记录
- 卖出双重保险日志从 DEBUG 改为带合同编号的 DEBUG，便于排查

## 涉及文件

| 文件 | 修改内容 |
|------|----------|
| `follow-client/app/db/repository.py` | 新增 `get_today_successful_entrust_nos()` |
| `follow-client/app/services/comparator.py` | 新增 `followed_entrust_nos` 参数 + `_find_followed_local_entrust()` + 替换双重保险逻辑 |
| `follow-client/app/services/follow_engine.py` | 调用新 repository 方法并传参 |

## 不在本次范围

- 不涉及前端变更
- 不涉及喊单端（signal-server）变更
- 不修改 `follow_records` 表结构
- 不修改 `_find_local_entrust()` 原有函数（步骤 1 撤单跟随仍使用）

## 验证方案

1. 启动跟单端，手动在同花顺买入某股票
2. 确认喊单端出现同股票买入信号时，跟单端**不再跳过**，正常下单
3. 确认日志中不再出现 `local_buy_exists_but_no_record` WARNING
4. 模拟崩溃恢复场景：跟单下单成功后重启引擎，确认 `has_followed()` 返回 True，不会重复下单
5. 确认卖出步骤同理不受手动卖单遮挡
