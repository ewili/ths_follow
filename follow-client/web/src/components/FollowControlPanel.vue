<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElCheckbox,
  ElMessage,
  ElTag,
} from 'element-plus'
import { useFollowEngine } from '@/composables/useFollowEngine'
import { useLocalTrader } from '@/composables/useLocalTrader'

const {
  status: followStatus,
  startLoading,
  stopLoading,
  error: followError,
  start,
  stop,
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
    </div>

    <div v-if="!isRunning" class="start-options">
      <ElCheckbox v-model="coldStartAlign">
        启动时对齐存量委托 (cold_start_align_existing)
      </ElCheckbox>
      <div class="field-warning">
        默认关闭。开启后可能跟入喊单端已存在的存量委托。
      </div>
    </div>

    <div v-if="followError" class="error-msg">{{ followError }}</div>

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
