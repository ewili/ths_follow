<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMenu, ElMenuItem } from 'element-plus'
import DashboardOverview from '@/components/DashboardOverview.vue'
import DiagnosticsPanel from '@/components/DiagnosticsPanel.vue'
import ThsConnection from '@/components/ThsConnection.vue'
import SignalControl from '@/components/SignalControl.vue'
import StockList from '@/components/StockList.vue'
import OperationLogPanel from '@/components/OperationLogPanel.vue'

type ActiveView = 'overview' | 'connection' | 'control' | 'stocks' | 'logs'

const activeView = ref<ActiveView>('overview')

const viewMeta: Record<ActiveView, { title: string; subtitle: string }> = {
  overview: {
    title: '系统仪表盘',
    subtitle: '查看连接状态、喊单运行态和 trader 性能指标。',
  },
  connection: {
    title: '终端连接配置',
    subtitle: '管理 xiadan.exe 路径和同花顺兼容性参数。',
  },
  control: {
    title: '喊单控制',
    subtitle: '手动启停喊单服务，明确当前运行态。',
  },
  stocks: {
    title: '股票涨跌停价',
    subtitle: '查看当日主板股票涨跌停价，并支持手动采集。',
  },
  logs: {
    title: '操作日志',
    subtitle: '快速排查连接、采集和接口调用异常。',
  },
}

const pageTitle = computed(() => viewMeta[activeView.value].title)
const pageSubtitle = computed(() => viewMeta[activeView.value].subtitle)

function onSelect(index: string) {
  activeView.value = index as ActiveView
}
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">SS</div>
        <div>
          <div class="brand-title">Signal Server</div>
          <div class="brand-subtitle">喊单端本地管理台</div>
        </div>
      </div>
      <ElMenu :default-active="activeView" class="nav" @select="onSelect">
        <ElMenuItem index="overview">仪表盘</ElMenuItem>
        <ElMenuItem index="connection">终端连接</ElMenuItem>
        <ElMenuItem index="control">喊单控制</ElMenuItem>
        <ElMenuItem index="stocks">股票列表</ElMenuItem>
        <ElMenuItem index="logs">操作日志</ElMenuItem>
      </ElMenu>
    </aside>

    <main class="main">
      <header class="main-header">
        <div>
          <h1 class="page-title">{{ pageTitle }}</h1>
          <p class="page-subtitle">{{ pageSubtitle }}</p>
        </div>
      </header>

      <section v-if="activeView === 'overview'" class="view-grid">
        <DashboardOverview />
        <DiagnosticsPanel />
      </section>
      <section v-else-if="activeView === 'connection'" class="view-single">
        <ThsConnection />
      </section>
      <section v-else-if="activeView === 'control'" class="view-single">
        <SignalControl />
      </section>
      <section v-else-if="activeView === 'stocks'" class="view-single">
        <StockList />
      </section>
      <section v-else class="view-single">
        <OperationLogPanel />
      </section>
    </main>
  </div>
</template>
