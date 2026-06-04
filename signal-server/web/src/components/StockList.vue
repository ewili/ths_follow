<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  ElButton,
  ElCard,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElPagination,
  ElTable,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import { getStockPrices, getStockStatus, triggerFetch } from '@/api/stock'
import { getErrorMessage } from '@/api/http'
import type { StockPriceDTO, StockStatusResponse } from '@/types/stock'

const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const items = ref<StockPriceDTO[]>([])
const loading = ref(false)
const fetching = ref(false)
const fetchStatus = ref<StockStatusResponse>({
  latest_trade_date: null,
  stock_count: 0,
  scheduler_running: false,
})

async function loadList() {
  loading.value = true
  try {
    const res = await getStockPrices({
      page: page.value,
      size: pageSize.value,
      keyword: keyword.value || undefined,
    })
    items.value = res.items
    total.value = res.total
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    loading.value = false
  }
}

async function loadStatus() {
  try {
    fetchStatus.value = await getStockStatus()
  } catch {
    /* ignore */
  }
}

function onSearch() {
  page.value = 1
  void loadList()
}

function onPageChange(p: number) {
  page.value = p
  void loadList()
}

function onSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
  void loadList()
}

async function onFetch() {
  fetching.value = true
  try {
    const res = await triggerFetch()
    if (res.success) {
      ElMessage.success(res.message || `成功采集 ${res.count} 只股票`)
      await loadList()
      await loadStatus()
    } else {
      await ElMessageBox.alert(res.message || '采集未成功', '无法采集', {
        type: 'warning',
        confirmButtonText: '知道了',
      })
    }
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    fetching.value = false
  }
}

onMounted(() => {
  void loadList()
  void loadStatus()
})
</script>

<template>
  <ElCard class="stock-card" shadow="hover">
    <template #header>
      <div class="card-header">
        <span class="title">股票涨跌停价</span>
        <div class="header-right">
          <ElTag v-if="fetchStatus.scheduler_running" type="success" size="small">
            定时采集运行中
          </ElTag>
          <ElTag v-else type="info" size="small">定时采集未启用</ElTag>
        </div>
      </div>
    </template>

    <div class="toolbar">
      <ElInput
        v-model="keyword"
        placeholder="搜索代码或名称"
        clearable
        style="width: 240px"
        @keyup.enter="onSearch"
        @clear="onSearch"
      >
        <template #prefix>
          <Search />
        </template>
      </ElInput>
      <div class="toolbar-right">
        <div v-if="fetchStatus.latest_trade_date" class="status-info">
          <span class="status-label">最近交易日：</span>
          <span class="status-value">{{ fetchStatus.latest_trade_date }}</span>
          <span class="status-label" style="margin-left: 12px">股票数：</span>
          <span class="status-value">{{ fetchStatus.stock_count }}</span>
        </div>
        <ElButton type="primary" :loading="fetching" @click="onFetch">手动采集</ElButton>
      </div>
    </div>

    <ElTable
      v-loading="loading"
      :data="items"
      border
      style="margin-top: 16px"
      :header-cell-style="{ background: '#f5f7fa', fontWeight: 600 }"
    >
      <ElTableColumn prop="stock_code" label="代码" width="100" />
      <ElTableColumn prop="stock_name" label="名称" min-width="120" />
      <ElTableColumn prop="close_price" label="收盘价" width="100" align="right" />
      <ElTableColumn prop="limitup_price" label="涨停价" width="100" align="right">
        <template #default="{ row }">
          <span class="price-up">{{ row.limitup_price }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="limitdown_price" label="跌停价" width="100" align="right">
        <template #default="{ row }">
          <span class="price-down">{{ row.limitdown_price }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="trade_date" label="交易日" width="110" />
    </ElTable>

    <div class="pagination-wrap">
      <ElPagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        background
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-sizes="[20, 50, 100, 200]"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </ElCard>
</template>

<style scoped>
.stock-card {
  border-radius: 12px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-header .title {
  font-size: 18px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.status-info {
  font-size: 13px;
  color: #606266;
}

.status-label {
  color: #909399;
}

.status-value {
  font-weight: 600;
  color: #303133;
}

.price-up {
  color: #f56c6c;
  font-weight: 500;
}

.price-down {
  color: #67c23a;
  font-weight: 500;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
