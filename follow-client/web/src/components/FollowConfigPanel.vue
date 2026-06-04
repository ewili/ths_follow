<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import {
  ElButton,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
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
import { getErrorMessage } from '@/api/http'
import { useFollowConfig } from '@/composables/useFollowConfig'
import type { EntrustSource, FollowConfigUpdate, HistoryEntrustPeriod } from '@/types/config'

const { config, saveLoading, probeLoading, lastApiError, saveConfig, testConnectivity } =
  useFollowConfig()

const form = reactive({
  signal_server_url: '',
  poll_interval_ms: 500,
  local_ths_exe_path: '',
  use_type_keys: false,
  grid_strategy: 'Copy' as FollowConfigUpdate['grid_strategy'],
  captcha_mode: 'local' as FollowConfigUpdate['captcha_mode'],
  vlm_api_key: '',
  captcha_auto_fail_threshold: 3,
  schedule_enabled: false,
  schedule_weekdays: [1, 2, 3, 4, 5] as number[],
  schedule_time_ranges: [
    { start: '09:30', end: '11:30' },
    { start: '13:00', end: '15:00' },
  ],
  history_entrust_period: '当日' as HistoryEntrustPeriod,
  entrust_source: 'today' as EntrustSource,
})

const urlError = computed(() => {
  const v = form.signal_server_url.trim()
  if (!v) return '请输入喊单服务端地址'
  try {
    const u = new URL(v)
    if (!['http:', 'https:'].includes(u.protocol)) {
      return '地址必须以 http:// 或 https:// 开头'
    }
    if (!u.port) return '地址必须包含端口号'
  } catch {
    return '请输入合法的 URL'
  }
  return ''
})

const pollError = computed(() => {
  if (!Number.isInteger(form.poll_interval_ms)) return '拉取间隔必须是整数'
  if (form.poll_interval_ms < 100 || form.poll_interval_ms > 5000) {
    return '拉取间隔必须在 100 到 5000 之间'
  }
  return ''
})

const pathError = computed(() => {
  const v = form.local_ths_exe_path.trim()
  if (!v) return '请输入本地同花顺路径'
  if (!v.toLowerCase().endsWith('xiadan.exe')) return '路径必须以 xiadan.exe 结尾'
  return ''
})

const serverError = computed(() => getErrorMessage(lastApiError.value))

const canSubmit = computed(() => !urlError.value && !pollError.value && !pathError.value)

watch(
  config,
  (cfg) => {
    if (!cfg) return
    form.signal_server_url = cfg.signal_server_url
    form.poll_interval_ms = cfg.poll_interval_ms
    form.local_ths_exe_path = cfg.local_ths_exe_path
    form.use_type_keys = cfg.use_type_keys
    form.grid_strategy = cfg.grid_strategy
    form.captcha_mode = cfg.captcha_mode
    form.vlm_api_key = cfg.vlm_api_key
    form.captcha_auto_fail_threshold = cfg.captcha_auto_fail_threshold
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
    form.history_entrust_period = cfg.history_entrust_period || '当日'
    form.entrust_source = cfg.entrust_source || 'today'
  },
  { immediate: true },
)

function formatSavedTime(value: string) {
  return new Date(value).toLocaleString('zh-CN')
}

function buildPayload(): FollowConfigUpdate {
  return {
    signal_server_url: form.signal_server_url.trim(),
    poll_interval_ms: form.poll_interval_ms,
    local_ths_exe_path: form.local_ths_exe_path.trim(),
    cold_start_align_existing: config.value?.cold_start_align_existing ?? false,
    use_type_keys: form.use_type_keys,
    grid_strategy: form.grid_strategy,
    captcha_mode: form.captcha_mode,
    vlm_api_key: form.vlm_api_key,
    captcha_auto_fail_threshold: form.captcha_auto_fail_threshold,
    schedule_enabled: form.schedule_enabled,
    schedule_weekdays: form.schedule_enabled ? [...form.schedule_weekdays] : [],
    schedule_time_ranges: form.schedule_enabled
      ? form.schedule_time_ranges.map((r) => ({ ...r }))
      : [],
    history_entrust_period:
      form.entrust_source === 'history' ? form.history_entrust_period : '当日',
    entrust_source: form.entrust_source,
  }
}

async function onSave() {
  if (!canSubmit.value) return
  const ok = await saveConfig(buildPayload())
  if (ok) {
    ElMessage.success('配置已保存')
  } else {
    ElMessage.error(serverError.value || '保存失败')
  }
}

async function onTestConnectivity() {
  if (urlError.value) return
  const result = await testConnectivity({
    signal_server_url: form.signal_server_url.trim(),
  })
  if (!result) {
    ElMessage.error(serverError.value || '连接测试失败')
    return
  }
  if (result.ok) {
    ElMessage.success(result.message)
  } else {
    ElMessage.error(result.message)
  }
}

function addTimeRange() {
  form.schedule_time_ranges.push({ start: '09:30', end: '11:30' })
}

function removeTimeRange(index: number) {
  form.schedule_time_ranges.splice(index, 1)
}
</script>

<template>
  <ElCard class="config-card" shadow="hover" v-loading="!config">
    <template #header>
      <div class="card-header">
        <div>
          <div class="title">跟单参数配置</div>
          <div class="subtitle">配置喊单端地址、本地同花顺路径和跟单轮询参数。</div>
        </div>
        <span v-if="config?.updated_at" class="saved-time">
          最后保存：{{ formatSavedTime(config.updated_at) }}
        </span>
      </div>
    </template>

    <ElForm label-width="170px" @submit.prevent>
      <ElFormItem label="喊单服务端地址">
        <ElInput
          v-model="form.signal_server_url"
          placeholder="http://192.168.1.100:8000"
          clearable
          :class="{ 'is-error': !!urlError }"
        />
        <div v-if="urlError" class="field-error">{{ urlError }}</div>
      </ElFormItem>

      <ElFormItem label="拉取间隔 (ms)">
        <ElInputNumber
          v-model="form.poll_interval_ms"
          :min="100"
          :max="5000"
          :step="100"
          :precision="0"
          controls-position="right"
        />
        <div class="field-help">
          默认 500ms。该值是最小轮询间隔，不代表最终 GUI 实际频率。
        </div>
        <div v-if="pollError" class="field-error">{{ pollError }}</div>
      </ElFormItem>

      <ElFormItem label="本地同花顺路径">
        <ElInput
          v-model="form.local_ths_exe_path"
          placeholder="C:\\THS\\xiadan.exe"
          clearable
          :class="{ 'is-error': !!pathError }"
        />
        <div v-if="pathError" class="field-error">{{ pathError }}</div>
      </ElFormItem>

      <ElFormItem label="兼容性设置">
        <div class="compat-group">
          <div class="compat-item">
            <span class="compat-label">键盘输入模式 (use_type_keys)</span>
            <ElSwitch v-model="form.use_type_keys" />
          </div>
          <div class="compat-item">
            <span class="compat-label">表格抓取策略 (grid_strategy)</span>
            <ElSelect v-model="form.grid_strategy" style="width: 160px">
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

      <ElFormItem label="委托来源">
        <ElSelect v-model="form.entrust_source" style="width: 160px">
          <ElOption label="当日委托" value="today" />
          <ElOption label="历史委托" value="history" />
        </ElSelect>
        <div v-if="form.entrust_source === 'history'" class="field-help" style="margin-top: 8px">
          启动后将按配置自动对齐喊单端历史委托进行跟单。
        </div>
      </ElFormItem>

      <ElFormItem v-if="form.entrust_source === 'history'" label="历史委托周期">
        <ElSelect v-model="form.history_entrust_period" style="width: 160px">
          <ElOption label="当日" value="当日" />
          <ElOption label="近一周" value="近一周" />
          <ElOption label="近一月" value="近一月" />
          <ElOption label="近三月" value="近三月" />
          <ElOption label="近一年" value="近一年" />
        </ElSelect>
      </ElFormItem>

      <div v-if="serverError && lastApiError" class="server-error">{{ serverError }}</div>

      <div class="action-buttons">
        <ElButton
          type="primary"
          :loading="saveLoading"
          :disabled="!canSubmit"
          @click="onSave"
        >
          保存配置
        </ElButton>
        <ElButton
          :loading="probeLoading"
          :disabled="!!urlError"
          @click="onTestConnectivity"
        >
          测试连接
        </ElButton>
      </div>
    </ElForm>
  </ElCard>
</template>

<style scoped>
.config-card {
  border-radius: 12px;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.title {
  font-size: 18px;
  font-weight: 600;
}

.subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: var(--muted);
}

.saved-time {
  font-size: 12px;
  color: var(--muted);
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
  line-height: 1.6;
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

.server-error {
  margin-bottom: 12px;
  color: #f56c6c;
  font-size: 13px;
}

.action-buttons {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
}
</style>
