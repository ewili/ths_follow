<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
  ElDivider,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElOption,
  ElSelect,
  ElSwitch,
  ElTimePicker,
} from 'element-plus'
import { useSystemConfig } from '@/composables/useSystemConfig'
import type { HistoryEntrustPeriod, SignalMode, SystemConfigUpdate } from '@/types/config'
import StatusBadge from './StatusBadge.vue'

const {
  config,
  status,
  saveLoading,
  actionLoading,
  saveConfig,
  connect,
  disconnect,
  health,
} = useSystemConfig()

const form = reactive({
  ths_exe_path: '',
  use_type_keys: false,
  grid_strategy: 'Copy' as SystemConfigUpdate['grid_strategy'],
  captcha_mode: 'local' as SystemConfigUpdate['captcha_mode'],
  vlm_api_key: '',
  captcha_auto_fail_threshold: 3,
  captcha_vlm_call_count: 3,
  schedule_enabled: false,
  schedule_weekdays: [1, 2, 3, 4, 5] as number[],
  schedule_time_ranges: [
    { start: '09:30', end: '11:30' },
    { start: '13:00', end: '15:00' },
  ],
  history_entrust_period: '当日' as HistoryEntrustPeriod,
  signal_mode: 'ratio' as SignalMode,
})

const pathError = computed(() => {
  const v = form.ths_exe_path.trim()
  if (!v) return '请输入终端路径'
  if (!v.toLowerCase().endsWith('xiadan.exe')) return '路径必须以 xiadan.exe 结尾'
  return ''
})

const canSave = computed(() => !pathError.value)

const hasSavedConfig = computed(() => Boolean(config.value?.ths_exe_path?.trim()))

watch(
  config,
  (cfg) => {
    if (!cfg) return
    form.ths_exe_path = cfg.ths_exe_path
    form.use_type_keys = cfg.use_type_keys
    form.grid_strategy = cfg.grid_strategy
    form.captcha_mode = cfg.captcha_mode
    form.vlm_api_key = cfg.vlm_api_key
    form.captcha_auto_fail_threshold = cfg.captcha_auto_fail_threshold
    form.captcha_vlm_call_count = cfg.captcha_vlm_call_count
    form.schedule_enabled = cfg.schedule_enabled
    form.schedule_weekdays =
      cfg.schedule_weekdays.length > 0 ? [...cfg.schedule_weekdays] : [1, 2, 3, 4, 5]
    form.schedule_time_ranges =
      cfg.schedule_time_ranges.length > 0
        ? cfg.schedule_time_ranges.map((r) => ({ ...r }))
        : [
            { start: '09:30', end: '11:30' },
            { start: '13:00', end: '15:00' },
          ]
    form.history_entrust_period = cfg.history_entrust_period
    form.signal_mode = cfg.signal_mode
  },
  { immediate: true },
)

function buildPayload(): SystemConfigUpdate {
  return {
    ths_exe_path: form.ths_exe_path.trim(),
    use_type_keys: form.use_type_keys,
    grid_strategy: form.grid_strategy,
    captcha_mode: form.captcha_mode,
    vlm_api_key: form.vlm_api_key,
    captcha_auto_fail_threshold: form.captcha_auto_fail_threshold,
    captcha_vlm_call_count: form.captcha_vlm_call_count,
    schedule_enabled: form.schedule_enabled,
    schedule_weekdays: form.schedule_enabled ? [...form.schedule_weekdays] : [],
    schedule_time_ranges: form.schedule_enabled
      ? form.schedule_time_ranges.map((r) => ({ ...r }))
      : [],
    history_entrust_period: form.history_entrust_period,
    signal_mode: form.signal_mode,
  }
}

async function onSave() {
  if (!canSave.value) return
  const ok = await saveConfig(buildPayload())
  if (ok) {
    ElMessage.success('配置已保存')
  } else {
    ElMessage.error('保存配置失败')
  }
}

async function onConnect() {
  const ok = await connect()
  if (ok) ElMessage.success('终端连接成功')
  else ElMessage.error('连接终端失败')
}

async function onDisconnect() {
  const ok = await disconnect()
  if (ok) ElMessage.info('已断开终端连接')
  else ElMessage.error('断开连接失败')
}

async function onHealth() {
  const ok = await health()
  if (ok) ElMessage.success('健康检查通过')
  else ElMessage.error('健康检查失败')
}

function addTimeRange() {
  form.schedule_time_ranges.push({ start: '09:30', end: '11:30' })
}

function removeTimeRange(index: number) {
  form.schedule_time_ranges.splice(index, 1)
}
</script>

<template>
  <ElCard class="ths-card" shadow="hover" v-loading="!config">
    <template #header>
      <div class="card-header">
        <div class="header-main">
          <span class="title">同花顺终端连接</span>
          <span v-if="hasSavedConfig" class="saved-tag">配置已保存</span>
        </div>
        <StatusBadge :state="status.state" />
      </div>
    </template>

    <ElForm label-width="140px" @submit.prevent>
      <ElFormItem label="终端路径">
        <ElInput
          v-model="form.ths_exe_path"
          placeholder="请粘贴 xiadan.exe 的完整路径"
          clearable
          :class="{ 'is-error': !!pathError }"
        />
        <div v-if="pathError" class="field-error">{{ pathError }}</div>
        <div class="field-help">
          <p>示例：<code>C:\同花顺软件\交易\xiadan.exe</code></p>
          <p>
            获取方法：在资源管理器中找到 <strong>xiadan.exe</strong> → 右键 →
            复制文件地址，粘贴到此处
          </p>
        </div>
      </ElFormItem>

      <ElFormItem label="兼容性设置">
        <div class="compat-group">
          <div class="compat-item">
            <span class="compat-label">键盘输入模式 (use_type_keys)</span>
            <ElSwitch v-model="form.use_type_keys" />
          </div>
          <div class="compat-item">
            <span class="compat-label">表格抓取策略 (grid_strategy)</span>
            <ElSelect v-model="form.grid_strategy" style="width: 140px">
              <ElOption label="Copy" value="Copy" />
              <ElOption label="Xls" value="Xls" />
              <ElOption label="WMCopy" value="WMCopy" />
            </ElSelect>
          </div>
        </div>
      </ElFormItem>

      <ElFormItem label="验证码识别模式">
        <div class="compat-group">
          <div class="compat-item">
            <span class="compat-label">识别方式</span>
            <ElSelect v-model="form.captcha_mode" style="width: 200px">
              <ElOption label="本地 ddddocr 投票" value="local" />
              <ElOption label="视觉大模型 (VLM)" value="vlm" />
              <ElOption label="自动切换 (auto)" value="auto" />
            </ElSelect>
          </div>
          <div v-if="form.captcha_mode === 'auto'" class="compat-item">
            <span class="compat-label">连续失败切换阈值</span>
            <ElInputNumber
              v-model="form.captcha_auto_fail_threshold"
              :min="1"
              :max="10"
              :step="1"
              controls-position="right"
              style="width: 120px"
            />
          </div>
          <div
            v-if="form.captcha_mode === 'vlm' || form.captcha_mode === 'auto'"
            class="compat-item"
          >
            <span class="compat-label">VLM 投票次数</span>
            <ElInputNumber
              v-model="form.captcha_vlm_call_count"
              :min="1"
              :max="10"
              :step="1"
              controls-position="right"
              style="width: 120px"
            />
          </div>
          <div
            v-if="form.captcha_mode === 'vlm' || form.captcha_mode === 'auto'"
            class="compat-item"
          >
            <span class="compat-label">DashScope API Key</span>
            <ElInput
              v-model="form.vlm_api_key"
              placeholder="sk-xxx"
              type="password"
              show-password
              style="width: 260px"
            />
          </div>
        </div>
        <div class="field-help">
          本地模式使用 ddddocr 多方法投票；VLM 模式调用阿里云 DashScope（可配置投票次数）；
          auto 模式 ddddocr 优先，连续失败达阈值后切换 VLM。
        </div>
      </ElFormItem>

      <ElFormItem label="运行时段控制">
        <div class="compat-group">
          <div class="compat-item">
            <span class="compat-label">启用时段控制</span>
            <ElSwitch v-model="form.schedule_enabled" />
          </div>
          <template v-if="form.schedule_enabled">
            <div class="compat-item" style="align-items: flex-start">
              <span class="compat-label">运行星期</span>
              <ElCheckboxGroup v-model="form.schedule_weekdays">
                <ElCheckbox :value="1">周一</ElCheckbox>
                <ElCheckbox :value="2">周二</ElCheckbox>
                <ElCheckbox :value="3">周三</ElCheckbox>
                <ElCheckbox :value="4">周四</ElCheckbox>
                <ElCheckbox :value="5">周五</ElCheckbox>
                <ElCheckbox :value="6">周六</ElCheckbox>
                <ElCheckbox :value="7">周日</ElCheckbox>
              </ElCheckboxGroup>
            </div>
            <div class="time-ranges-block">
              <div class="compat-label" style="margin-bottom: 8px">运行时间段</div>
              <div
                v-for="(_, index) in form.schedule_time_ranges"
                :key="index"
                class="time-range-row"
              >
                <ElTimePicker
                  v-model="form.schedule_time_ranges[index].start"
                  format="HH:mm"
                  value-format="HH:mm"
                  placeholder="开始"
                />
                <span>至</span>
                <ElTimePicker
                  v-model="form.schedule_time_ranges[index].end"
                  format="HH:mm"
                  value-format="HH:mm"
                  placeholder="结束"
                />
                <ElButton
                  v-if="form.schedule_time_ranges.length > 1"
                  text
                  type="danger"
                  @click="removeTimeRange(index)"
                >
                  删除
                </ElButton>
              </div>
              <ElButton text type="primary" @click="addTimeRange">添加时段</ElButton>
            </div>
          </template>
        </div>
      </ElFormItem>

      <ElFormItem label="历史委托默认周期">
        <ElSelect v-model="form.history_entrust_period" style="width: 160px">
          <ElOption label="当日" value="当日" />
          <ElOption label="近一周" value="近一周" />
          <ElOption label="近一月" value="近一月" />
          <ElOption label="近三月" value="近三月" />
          <ElOption label="近一年" value="近一年" />
        </ElSelect>
      </ElFormItem>

      <ElFormItem label="喊单模式">
        <div class="compat-group">
          <div class="compat-item">
            <ElSelect v-model="form.signal_mode" style="width: 160px">
              <ElOption label="资金比例" value="ratio" />
              <ElOption label="倍数" value="multiplier" />
            </ElSelect>
          </div>
        </div>
        <div class="field-help">
          <p>资金比例模式：委托按总资产占比换算，跟单端需拉取资金数据。</p>
          <p>倍数模式：仅拉取委托数据，减少 GUI 调用和验证码触发，跟单端按倍数跟单。</p>
        </div>
      </ElFormItem>

      <ElDivider />

      <div class="actions">
        <ElButton
          type="primary"
          :loading="saveLoading"
          :disabled="!canSave"
          @click="onSave"
        >
          保存配置
        </ElButton>
        <ElButton
          type="success"
          :loading="actionLoading"
          :disabled="status.state === 'connected'"
          @click="onConnect"
        >
          连接终端
        </ElButton>
        <ElButton
          :loading="actionLoading"
          :disabled="status.state !== 'connected'"
          @click="onDisconnect"
        >
          断开连接
        </ElButton>
        <ElButton
          :loading="actionLoading"
          :disabled="status.state !== 'connected'"
          @click="onHealth"
        >
          健康检查
        </ElButton>
      </div>

      <div v-if="status.last_error" class="field-error" style="margin-top: 12px">
        {{ status.last_error }}
      </div>
    </ElForm>
  </ElCard>
</template>

<style scoped>
.ths-card {
  border-radius: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-main {
  display: flex;
  align-items: center;
  gap: 10px;
}

.card-header .title {
  font-size: 18px;
  font-weight: 600;
}

.saved-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  color: #0f766e;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
}

.compat-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.compat-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.compat-label {
  font-size: 13px;
  color: #606266;
}

.field-error {
  color: #f56c6c;
  font-size: 12px;
  margin-top: 4px;
}

.field-help {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.8;
}

.field-help p {
  margin: 0;
}

.field-help code {
  background: #f4f4f5;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: Consolas, monospace;
}

:deep(.is-error .el-input__wrapper) {
  box-shadow: 0 0 0 1px #f56c6c inset;
}

.time-ranges-block {
  width: 100%;
}

.time-range-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
</style>
