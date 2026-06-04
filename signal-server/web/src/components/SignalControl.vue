<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElButton, ElMessage, ElRadioGroup, ElRadioButton } from 'element-plus'
import { getSignalStatus, startSignal, stopSignal } from '@/api/signal'
import { getDashboardStatus } from '@/api/system'
import { getErrorMessage } from '@/api/http'
import type { SignalRuntimeStatus } from '@/types/signal'
import type { ConnectionStatus } from '@/types/config'
import StatusBadge from './StatusBadge.vue'

const status = ref<SignalRuntimeStatus>({
  state: 'stopped',
  started_at: null,
  last_changed_at: null,
  schedule_active: true,
  signal_mode: 'ratio',
})

const connection = ref<ConnectionStatus>({
  state: 'disconnected',
  last_error: null,
  last_connect_at: null,
})

const selectedMode = ref<'ratio' | 'multiplier'>('ratio')
const action = ref<'start' | 'stop' | ''>('')

let connectionTimer: number | null = null

const terminalConnected = computed(() => connection.value.state === 'connected')

const label = computed(() => (status.value.state === 'running' ? '运行中' : '已停止'))

const hint = computed(() =>
  status.value.state === 'running'
    ? '跟单端现在可以基于 Signal Server 的运行态进行消费。'
    : '停止后不会清空已保存配置，但运行态会立即切回停止。',
)

const isRunning = computed(() => status.value.state === 'running')

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '--'
}

async function refresh() {
  try {
    status.value = await getSignalStatus()
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  }
}

async function refreshConnection(silent = false) {
  try {
    const dashboard = await getDashboardStatus()
    connection.value = dashboard.connection
  } catch (err) {
    if (!silent) {
      ElMessage.error(getErrorMessage(err))
    }
  }
}

async function onStart() {
  if (!terminalConnected.value) {
    ElMessage.warning('请先连接同花顺终端')
    return
  }
  action.value = 'start'
  try {
    status.value = await startSignal(selectedMode.value)
    ElMessage.success('喊单已启动')
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    action.value = ''
  }
}

async function onStop() {
  action.value = 'stop'
  try {
    status.value = await stopSignal()
    ElMessage.info('喊单已停止')
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    action.value = ''
  }
}

// 运行中时，同步显示当前模式；停止时允许选择
watch(
  () => status.value.signal_mode,
  (mode) => {
    if (isRunning.value) {
      selectedMode.value = mode
    }
  },
)

onMounted(() => {
  void refresh()
  void refreshConnection(true)
  connectionTimer = window.setInterval(() => void refreshConnection(true), 5000)
})

onUnmounted(() => {
  if (connectionTimer !== null) clearInterval(connectionTimer)
})
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <div>
        <h2 class="panel-title">喊单启停控制</h2>
        <p class="panel-subtitle">运行态只保存在内存中，服务重启后默认恢复为停止。</p>
      </div>
      <div class="status-pill" :class="status.state">
        <StatusBadge :state="status.state" />
        <span>{{ label }}</span>
      </div>
    </div>

    <div class="timeline">
      <div class="timeline-item">
        <span>最近变更</span>
        <strong>{{ formatTime(status.last_changed_at) }}</strong>
      </div>
      <div class="timeline-item">
        <span>启动时间</span>
        <strong>{{ formatTime(status.started_at) }}</strong>
      </div>
    </div>

    <!-- 喊单模式选择 -->
    <div class="mode-section">
      <div class="mode-label">喊单模式</div>
      <ElRadioGroup v-model="selectedMode" :disabled="isRunning" size="default">
        <ElRadioButton value="ratio">资金比例</ElRadioButton>
        <ElRadioButton value="multiplier">倍数</ElRadioButton>
      </ElRadioGroup>
      <div class="mode-hint">
        <template v-if="selectedMode === 'ratio'">
          资金比例模式：委托按总资产占比换算，跟单端需拉取资金数据。
        </template>
        <template v-else>
          倍数模式：仅拉取委托数据，减少 GUI 调用和验证码触发，跟单端按倍数跟单。
        </template>
      </div>
    </div>

    <div class="hint" :class="status.state">{{ hint }}</div>

    <div
      v-if="status.state !== 'running' && !terminalConnected"
      class="hint stopped terminal-hint"
    >
      请先连接同花顺终端后再启动喊单。
    </div>

    <div class="actions">
      <ElButton
        type="success"
        :disabled="status.state === 'running' || !terminalConnected"
        :loading="action === 'start'"
        @click="onStart"
      >
        启动喊单
      </ElButton>
      <ElButton
        type="danger"
        :disabled="status.state !== 'running'"
        :loading="action === 'stop'"
        @click="onStop"
      >
        停止喊单
      </ElButton>
      <ElButton @click="refresh">刷新状态</ElButton>
    </div>
  </div>
</template>

<style scoped>
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-title {
  margin: 0;
  font-size: 18px;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 13px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--panel-muted);
  white-space: nowrap;
}

.status-pill.running {
  background: var(--success-soft);
}

.status-pill.stopped {
  background: var(--warning-soft);
}

.timeline {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 18px;
}

.timeline-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  background: var(--panel-muted);
}

.timeline-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
}

.timeline-item strong {
  display: block;
  margin-top: 8px;
  font-size: 16px;
}

.mode-section {
  margin-top: 18px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-muted);
}

.mode-label {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 10px;
}

.mode-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.hint {
  margin-top: 16px;
  padding: 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  color: #435466;
}

.hint.running {
  background: var(--success-soft);
}

.hint.stopped {
  background: var(--warning-soft);
}

.terminal-hint {
  margin-top: 12px;
  color: #b88230;
}

.actions {
  margin-top: 18px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

@media (max-width: 720px) {
  .timeline {
    grid-template-columns: 1fr;
  }
}
</style>
