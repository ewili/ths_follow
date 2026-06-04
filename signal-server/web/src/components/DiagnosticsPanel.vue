<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElButton, ElMessage, ElTable, ElTableColumn } from 'element-plus'
import { getDiagnostics } from '@/api/system'
import { getErrorMessage } from '@/api/http'
import type { DiagnosticSnapshot } from '@/types/system'

const diagnostics = ref<DiagnosticSnapshot>({
  gui_latency_p50_ms: 0,
  gui_latency_p95_ms: 0,
  cache_hit_rate: 0,
  cache_hits: 0,
  cache_misses: 0,
  captcha_count: 0,
  dialog_count: 0,
  avg_lock_wait_ms: 0,
  recent_gui_calls: [],
})

let timer: number | null = null

async function load(silent = false) {
  try {
    diagnostics.value = await getDiagnostics()
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
        <h2 class="panel-title">诊断面板</h2>
        <p class="panel-subtitle">用最近调用样本判断锁竞争和缓存命中情况。</p>
      </div>
      <ElButton text @click="load()">刷新</ElButton>
    </div>

    <div class="metrics-grid">
      <div class="metric-card">
        <span>缓存命中率</span>
        <strong>{{ (diagnostics.cache_hit_rate * 100).toFixed(1) }}%</strong>
        <small>{{ diagnostics.cache_hits }} hit / {{ diagnostics.cache_misses }} miss</small>
      </div>
      <div class="metric-card">
        <span>平均 Lock 等待</span>
        <strong>{{ diagnostics.avg_lock_wait_ms.toFixed(1) }} ms</strong>
        <small>越高说明 GUI 串行化压力越大</small>
      </div>
      <div class="metric-card">
        <span>验证码触发</span>
        <strong>{{ diagnostics.captcha_count }}</strong>
        <small>当前仅内存累计</small>
      </div>
      <div class="metric-card">
        <span>对话框异常</span>
        <strong>{{ diagnostics.dialog_count }}</strong>
        <small>自动映射为登录/窗口问题</small>
      </div>
    </div>

    <ElTable
      :data="diagnostics.recent_gui_calls"
      size="small"
      border
      style="margin-top: 16px"
      :header-cell-style="{ background: '#f5f7fa', fontWeight: 600 }"
    >
      <ElTableColumn prop="operation" label="调用" min-width="120" />
      <ElTableColumn prop="gui_elapsed_ms" label="GUI 耗时(ms)" width="130" align="right" />
      <ElTableColumn prop="lock_wait_ms" label="Lock 等待(ms)" width="140" align="right" />
    </ElTable>
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

.metrics-grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.metric-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  background: var(--panel-muted);
}

.metric-card span {
  display: block;
  font-size: 12px;
  color: var(--muted);
}

.metric-card strong {
  display: block;
  margin-top: 8px;
  font-size: 20px;
}

.metric-card small {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: var(--muted);
}

@media (max-width: 720px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }
}
</style>
