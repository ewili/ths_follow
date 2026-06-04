<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElButton, ElMessage } from 'element-plus'
import { getDashboardStatus } from '@/api/system'
import { getErrorMessage } from '@/api/http'
import type { DashboardStatusResponse } from '@/types/system'
import StatusBadge from './StatusBadge.vue'

const status = ref<DashboardStatusResponse>({
  connection: { state: 'disconnected', last_error: null, last_connect_at: null },
  signal: {
    state: 'stopped',
    started_at: null,
    last_changed_at: null,
    schedule_active: true,
  },
  latest_stock_trade_date: null,
  stock_count: 0,
  balance_fetched_at: null,
  position_fetched_at: null,
  entrusts_fetched_at: null,
  gui_latency_p50_ms: 0,
  gui_latency_p95_ms: 0,
})

const connectionLabel = computed(() => {
  const map: Record<string, string> = {
    disconnected: '未连接',
    connected: '已连接',
    error: '连接异常',
  }
  return map[status.value.connection.state] ?? status.value.connection.state
})

const signalLabel = computed(() =>
  status.value.signal.state === 'running' ? '运行中' : '已停止',
)

let timer: number | null = null

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '--'
}

async function load(silent = false) {
  try {
    status.value = await getDashboardStatus()
  } catch (err) {
    if (!silent) {
      ElMessage.error(getErrorMessage(err))
    }
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => void load(true), 5000)
})

onUnmounted(() => {
  if (timer !== null) clearInterval(timer)
})
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <div>
        <h2 class="panel-title">系统概览</h2>
        <p class="panel-subtitle">首页直接暴露连接、喊单和采集状态。</p>
      </div>
      <ElButton text @click="load()">刷新</ElButton>
    </div>

    <div class="stats-grid">
      <article class="stat-card">
        <div class="stat-label">终端连接</div>
        <div class="stat-main">
          <StatusBadge :state="status.connection.state" size="large" />
          <span>{{ connectionLabel }}</span>
        </div>
        <div class="stat-sub">{{ formatTime(status.connection.last_connect_at) }}</div>
      </article>

      <article class="stat-card">
        <div class="stat-label">喊单状态</div>
        <div class="stat-main">
          <StatusBadge :state="status.signal.state" size="large" />
          <span>{{ signalLabel }}</span>
        </div>
        <div class="stat-sub">{{ formatTime(status.signal.last_changed_at) }}</div>
      </article>

      <article
        class="stat-card"
        :class="{ warning: !status.latest_stock_trade_date }"
      >
        <div class="stat-label">最近采集日期</div>
        <div class="stat-value">{{ status.latest_stock_trade_date || '--' }}</div>
        <div v-if="status.latest_stock_trade_date" class="stat-sub">
          主板股票 {{ status.stock_count }} 只
        </div>
        <div v-else class="stat-sub warning-text">
          未采集行情数据，委托查询将返回空列表
        </div>
      </article>

      <article class="stat-card accent">
        <div class="stat-label">trader 延迟</div>
        <div class="latency-row">
          <span>P50 {{ status.gui_latency_p50_ms.toFixed(1) }} ms</span>
          <span>P95 {{ status.gui_latency_p95_ms.toFixed(1) }} ms</span>
        </div>
        <div class="stat-sub">统计口径：最近 50 次 GUI 调用</div>
      </article>
    </div>

    <div class="snapshot">
      <div class="snapshot-title">最近数据拉取</div>
      <div class="snapshot-list">
        <div class="snapshot-item">
          <span>资金</span>
          <strong>{{ formatTime(status.balance_fetched_at) }}</strong>
        </div>
        <div class="snapshot-item">
          <span>持仓</span>
          <strong>{{ formatTime(status.position_fetched_at) }}</strong>
        </div>
        <div class="snapshot-item">
          <span>委托</span>
          <strong>{{ formatTime(status.entrusts_fetched_at) }}</strong>
        </div>
      </div>
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

.stats-grid {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.stat-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  background: var(--panel-muted);
}

.stat-card.accent {
  background: var(--accent-soft);
  border-color: #c5d6ff;
}

.stat-card.warning {
  border-color: #f56c6c;
  background: #fef0f0;
}

.warning-text {
  color: #f56c6c !important;
  font-weight: 600;
}

.stat-label {
  font-size: 12px;
  color: var(--muted);
}

.stat-main,
.latency-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  font-size: 20px;
  font-weight: 700;
}

.latency-row {
  justify-content: space-between;
  font-size: 16px;
}

.stat-value {
  margin-top: 10px;
  font-size: 22px;
  font-weight: 700;
}

.stat-sub {
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}

.snapshot {
  margin-top: 18px;
  border-top: 1px solid var(--border);
  padding-top: 18px;
}

.snapshot-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}

.snapshot-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.snapshot-item {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
}

.snapshot-item span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}

.snapshot-item strong {
  display: block;
  margin-top: 8px;
  font-size: 14px;
}

@media (max-width: 720px) {
  .stats-grid,
  .snapshot-list {
    grid-template-columns: 1fr;
  }
}
</style>
