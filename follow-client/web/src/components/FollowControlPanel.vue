<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElCheckbox,
  ElMessage,
  ElMessageBox,
  ElTag,
} from 'element-plus'
import { useFollowEngine } from '@/composables/useFollowEngine'
import { useLocalTrader } from '@/composables/useLocalTrader'

const {
  status: followStatus,
  startLoading,
  stopLoading,
  clearLoading,
  error: followError,
  start,
  stop,
  clearTodayRecords,
} = useFollowEngine()

const {
  status: traderStatus,
  connectLoading,
  disconnectLoading,
  error: traderError,
  connect,
  disconnect,
} = useLocalTrader()

const coldStartAlign = ref(false)

const isRunning = computed(() => followStatus.value?.running ?? false)
const traderState = computed(() => traderStatus.value?.state ?? 'disconnected')
const traderConnected = computed(() => traderState.value === 'connected')
const todayRecordsCount = computed(() => followStatus.value?.today_records_count ?? 0)

// 当勾选冷启动对齐且引擎未运行时，显示记录相关提示区
const showColdStartBlock = computed(
  () => coldStartAlign.value && !isRunning.value,
)

function formatTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString('zh-CN') : '-'
}

async function onConnect() {
  const ok = await connect()
  if (traderError.value) {
    ElMessage.error(traderError.value)
  } else if (ok) {
    ElMessage.success('终端连接成功')
  }
}

async function onDisconnect() {
  await disconnect()
  if (!traderError.value) {
    ElMessage.info('终端已断开')
  }
}

async function onStart() {
  if (!traderConnected.value) {
    ElMessage.warning('请先连接本地同花顺终端')
    return
  }
  const ok = await start(coldStartAlign.value)
  if (followError.value) {
    ElMessage.error(followError.value)
  } else if (ok) {
    ElMessage.success('跟单引擎已启动')
  }
}

async function onStop() {
  const ok = await stop()
  if (followError.value) {
    ElMessage.error(followError.value)
  } else if (ok) {
    ElMessage.success('跟单引擎已停止')
  }
}

async function onClearTodayRecords() {
  try {
    await ElMessageBox.confirm(
      `确定清空今日全部 ${todayRecordsCount.value} 条跟单记录？\n清空后，存量对齐模式将能重新跟随之前已标记为"已跟随"的委托。`,
      '清空今日跟单记录',
      { confirmButtonText: '确定清空', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return // 用户取消
  }
  const deleted = await clearTodayRecords()
  if (deleted >= 0) {
    ElMessage.success(`已清空 ${deleted} 条今日跟单记录`)
  } else if (followError.value) {
    ElMessage.error(followError.value)
  }
}
</script>

<template>
  <ElCard class="control-card" shadow="hover">
    <template #header>
      <div class="card-header">
        <div>
          <div class="title">跟单引擎控制</div>
          <div class="subtitle">启动后将按比例自动跟随喊单端的委托。</div>
        </div>
        <ElTag :type="isRunning ? 'success' : 'info'" size="large" class="status-tag">
          {{ isRunning ? '运行中' : '已停止' }}
        </ElTag>
      </div>
    </template>

    <div class="trader-block">
      <div class="trader-row">
        <div class="trader-info">
          <span class="trader-label">本地同花顺终端</span>
          <ElTag
            :type="
              traderState === 'connected'
                ? 'success'
                : traderState === 'error'
                  ? 'danger'
                  : 'info'
            "
            size="small"
          >
            {{
              traderState === 'connected'
                ? '已连接'
                : traderState === 'error'
                  ? '错误'
                  : '未连接'
            }}
          </ElTag>
          <span v-if="traderStatus?.last_connect_at" class="trader-time">
            {{ formatTime(traderStatus.last_connect_at) }}
          </span>
        </div>
        <div class="trader-actions">
          <ElButton
            v-if="traderState !== 'connected'"
            type="primary"
            size="small"
            :loading="connectLoading"
            @click="onConnect"
          >
            连接终端
          </ElButton>
          <ElButton
            v-else
            size="small"
            :loading="disconnectLoading"
            @click="onDisconnect"
          >
            断开
          </ElButton>
        </div>
      </div>
      <div v-if="traderError" class="trader-error">{{ traderError }}</div>
      <div v-if="traderStatus?.last_error" class="trader-error">
        {{ traderStatus.last_error }}
      </div>
    </div>

    <div v-if="isRunning && followStatus" class="status-block">
      <div class="stat-item">
        <span class="stat-label">启动时间</span>
        <span class="stat-value">{{ formatTime(followStatus.start_time) }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">存量对齐</span>
        <span class="stat-value">
          {{ followStatus.cold_start_align_existing ? '已开启' : '已关闭' }}
        </span>
      </div>
      <div class="stat-item">
        <span class="stat-label">跟单模式</span>
        <span class="stat-value">
          {{ followStatus.follow_mode === 'multiplier' ? '倍数' : '资金比例' }}
        </span>
      </div>
      <div v-if="followStatus.follow_mode === 'multiplier'" class="stat-item">
        <span class="stat-label">跟单倍数</span>
        <span class="stat-value">{{ followStatus.follow_multiplier }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">今日记录</span>
        <span class="stat-value">{{ todayRecordsCount }} 条</span>
      </div>
    </div>

    <div v-if="!isRunning" class="start-options">
      <ElCheckbox v-model="coldStartAlign">
        启动时对齐存量委托 (cold_start_align_existing)
      </ElCheckbox>
      <div class="field-warning">
        默认关闭。开启后可能跟入喊单端已存在的存量委托。
      </div>
      <div v-if="showColdStartBlock" class="cold-start-block">
        <template v-if="todayRecordsCount > 0">
          <div class="warning-text">
            当前有 {{ todayRecordsCount }} 条今日跟单记录，可能导致防重复机制误判而跳过存量委托。
          </div>
          <ElButton
            type="warning"
            size="small"
            :loading="clearLoading"
            @click="onClearTodayRecords"
          >
            清空今日记录
          </ElButton>
        </template>
        <div v-else class="no-records-hint">
          当前无今日跟单记录，存量对齐无需清空。
        </div>
      </div>
    </div>

    <div v-if="followError" class="error-msg">{{ followError }}</div>

    <div v-if="!isRunning && !traderConnected" class="field-warning">
      请先连接本地同花顺终端后再启动跟单。
    </div>

    <div class="actions">
      <ElButton
        v-if="isRunning"
        type="danger"
        size="large"
        :loading="stopLoading"
        @click="onStop"
      >
        停止跟单
      </ElButton>
      <ElButton
        v-else
        type="primary"
        size="large"
        :loading="startLoading"
        :disabled="!traderConnected"
        @click="onStart"
      >
        启动跟单
      </ElButton>
    </div>
  </ElCard>
</template>

<style scoped>
.control-card {
  border-radius: 12px;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
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

.trader-block {
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.trader-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.trader-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.trader-label {
  font-size: 14px;
  font-weight: 500;
}

.trader-time {
  font-size: 12px;
  color: var(--muted);
}

.trader-error {
  margin-top: 8px;
  font-size: 12px;
  color: #f56c6c;
}

.status-block {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.stat-label {
  display: block;
  font-size: 12px;
  color: var(--muted);
}

.stat-value {
  display: block;
  margin-top: 6px;
  font-size: 15px;
  font-weight: 600;
}

.start-options {
  margin-bottom: 12px;
}

.field-warning {
  margin-top: 6px;
  font-size: 12px;
  color: #e6a23c;
}

.cold-start-block {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
  padding: 8px 12px;
  background: #fdf6ec;
  border: 1px solid #f5dab1;
  border-radius: 6px;
}

.cold-start-block .warning-text {
  font-size: 12px;
  color: #e6a23c;
  line-height: 1.5;
}

.no-records-hint {
  font-size: 12px;
  color: #67c23a;
  line-height: 1.5;
}

.error-msg {
  margin-bottom: 12px;
  color: #f56c6c;
  font-size: 13px;
}

.actions {
  display: flex;
  gap: 10px;
}
</style>
