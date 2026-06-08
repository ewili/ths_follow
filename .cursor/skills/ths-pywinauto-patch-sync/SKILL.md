---
name: ths-pywinauto-patch-sync
description: 同步 signal-server 与 follow-client 双端的 easytrader_copy_patch.py 和 errors.py 补丁，确保 THS 交互逻辑一致。
disable-model-invocation: true
---

# pywinauto 补丁双端同步

当修改 `signal-server/` 下的 `easytrader_copy_patch.py` 或 `errors.py` 时，必须检查 `follow-client/` 下对应文件是否需要同步，反之亦然。

## 适用场景

- 修改 `_type_captcha_via_wm_char` 或 `_type_edit_via_wm_char` 输入逻辑
- 修改 `_classify()` 异常映射（`errors.py`）
- 新增/修改 pywinauto monkey patch
- 修改验证码处理流程（OCR、重试策略等）

## 同步检查清单

1. **对比两端文件差异**：用 diff 比对 `signal-server/app/utils/easytrader_copy_patch.py` 与 `follow-client/app/utils/easytrader_copy_patch.py`
2. **检查 errors.py**：对比 `signal-server/app/models/errors.py` 与 `follow-client/app/models/errors.py` 的 `_classify` 函数（注意：follow-client 可能没有此文件，只检查 signal-server）
3. **检查 trader_service / local_trader_service**：验证双端的 `_bring_to_foreground()` **不包含**验证码自动处理逻辑（参见规则 `python-portable-runtime.mdc` → "验证码处理入口约束"），`_run_blocking()` 的置前 op_name 列表**不包含** `health_probe`
4. **检查 monkey patch 完整性**：确认两端都有 `_patch_pywinauto_process_get_modules`、`_patch_switch_left_menus`、`_patch_type_edit_control_keys` 等补丁，不能只同步部分
5. **逐项确认**：对每处修改，明确标记 ✓（已同步）或 ✗（仅一端有/需手动同步）
6. **验证**：修改后重启双端服务，调用各端 API 验证无回退：
   - 喊单：`/api/signal/balance`、`/api/signal/positions`、`/api/signal/entrusts`
   - 跟单：`/api/trader/balance`、`/api/trader/positions`、`/api/trader/entrusts`

## 常见差异来源

- signal-server 先修，follow-client 漏跟（最常见）
- follow-client `local_trader_service.py` 有内联验证码处理逻辑（`_handle_captcha_dialog`），signal-server 也有——双端均应移除，验证码处理统一由 `easytrader_copy_patch.py` 的 Copy 策略层和 close_pop_dialog 补丁承担
- `_bring_to_foreground()` 中残留验证码检测/处理代码——按规则必须移除，否则全局锁阻塞
- `_run_blocking()` 的置前 op_name 列表误含 `health_probe`——health_probe 无需置前
- `WM_CLEAR` vs 无 `WM_CLEAR`：signal-server 已去掉 `WM_CLEAR`，follow-client 可能仍保留旧逻辑
- 整段补丁缺失：如 `_patch_pywinauto_process_get_modules` 曾只存在于 signal-server，follow-client 完全缺失
- follow-client 没有 `errors.py`：异常分类逻辑可能在不同位置或不复存在
