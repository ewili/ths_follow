# US-004: _patched_copy_get 首次 type_keys 弹窗重试

## 用户故事

作为 **跟单系统运维人员**，
我想要 **Grid Copy 操作在弹窗遮挡导致 ElementNotVisible 时自动关闭弹窗并重试**，
以便于 **临时提示弹窗（如「令牌认证失败」）不会导致整轮跟单失败**。

## 背景与动机

跟单端运行时，同花顺会偶尔弹出提示对话框（如「令牌认证失败」「现有成交价格预警服务」等）。
`close_pop_dialog` 补丁已能正确识别并关闭这类弹窗，但存在时序竞争：

1. `_bring_to_foreground` 失败（窗口被弹窗遮挡无法置前）
2. `_switch_left_menus` 调用 `close_pop_dialog` 点击「确定」关闭弹窗
3. 弹窗尚未完全消失（或新弹窗又出现），Grid 控件仍不可见
4. `_patched_copy_get` 首次 `grid.type_keys("^A^C")` 抛出 `ElementNotVisible`
5. 异常未被捕获，整条调用链（`fetch_funds_stock` → `_snapshot` → `get_follow_snapshot` → `_one_round`）全部失败

## 问题定位

**文件**：`follow-client/app/utils/easytrader_copy_patch.py`（及 signal-server 对应文件）

`_patched_copy_get` 第 1157 行：

```python
grid.type_keys("^A^C", set_foreground=False, pause=0.2)  # ← 无 try-except
```

对比第 1171-1182 行的重试逻辑，那里已有 try-except 包裹 `grid.type_keys`，
说明作者已意识到此异常，但首次 `type_keys` 调用遗漏了。

## 验收标准

- [ ] `_patched_copy_get` 首次 `grid.type_keys` 捕获 `ElementNotVisible` / `ElementNotEnabled`
- [ ] 捕获后调用 `close_pop_dialog()` 关闭弹窗，等待 0.5 秒后重试
- [ ] 最多重试 2 次（共 3 次尝试），仍失败则抛出原始异常
- [ ] 非 `ElementNotVisible` / `ElementNotEnabled` 异常直接上抛，不重试
- [ ] 正常路径（无弹窗）性能无回归
- [ ] 双端 `easytrader_copy_patch.py` 同步

## 技术方案

### Step 1: 修改 `_patched_copy_get` 首次 `type_keys` 调用

**改动前**：

```python
grid.type_keys("^A^C", set_foreground=False, pause=0.2)
```

**改动后**：

```python
for _copy_attempt in range(3):
    try:
        grid.type_keys("^A^C", set_foreground=False, pause=0.2)
        break
    except Exception as _copy_exc:
        if _copy_attempt >= 2:
            _log(
                logging.ERROR,
                "Copy.get: grid.type_keys failed after %d attempts: %s",
                _copy_attempt + 1,
                _copy_exc,
            )
            raise
        exc_name = type(_copy_exc).__name__
        if exc_name not in ("ElementNotVisible", "ElementNotEnabled"):
            raise
        _log(
            logging.WARNING,
            "Copy.get: grid not visible/enabled (%s), closing pop dialog and retrying (attempt %d)",
            exc_name,
            _copy_attempt + 1,
        )
        try:
            self._trader.close_pop_dialog()
        except Exception:
            pass
        self._trader.wait(0.5)
```

### Step 2: 双端同步

确认 `signal-server/app/utils/easytrader_copy_patch.py` 中 `_patched_copy_get` 同步修改。

## 涉及文件

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
| `follow-client/app/utils/easytrader_copy_patch.py` | 修改 | `_patched_copy_get` 首次 type_keys 增加弹窗重试 |
| `signal-server/app/utils/easytrader_copy_patch.py` | 修改 | 同步修改 |

## 边界与异常场景

| 场景 | 处理方式 |
|------|----------|
| 无弹窗，Grid 正常可见 | 首次 type_keys 成功，不进入重试 |
| 弹窗遮挡，close_pop_dialog 关闭后恢复 | 第 2-3 次 type_keys 成功 |
| 弹窗连续出现，3 次都失败 | 抛出原始 ElementNotVisible，follow_engine 捕获后 return False |
| 其他异常（如 RuntimeError） | 直接上抛，不重试 |

## 验证方案

1. 启动跟单端，等待「令牌认证失败」弹窗出现时观察日志
2. 预期日志：`Copy.get: grid not visible/enabled (ElementNotVisible), closing pop dialog and retrying (attempt 1)`
3. 重试成功后：`_format_grid_data` 正常返回数据
4. 无弹窗时：无额外日志，性能无回归
