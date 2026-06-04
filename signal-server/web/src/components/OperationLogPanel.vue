<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  ElButton,
  ElInput,
  ElMessage,
  ElPagination,
  ElTable,
  ElTableColumn,
} from 'element-plus'
import { getLogs } from '@/api/system'
import { getErrorMessage } from '@/api/http'
import type { OperationLogEntry } from '@/types/system'

const loading = ref(false)
const keyword = ref('')
const items = ref<OperationLogEntry[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)

async function load() {
  loading.value = true
  try {
    const res = await getLogs({
      page: page.value,
      size: pageSize.value,
      keyword: keyword.value,
    })
    items.value = res.items
    total.value = res.total
  } catch (err) {
    ElMessage.error(getErrorMessage(err))
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  void load()
}

function onPageChange(p: number) {
  page.value = p
  void load()
}

function onSizeChange(size: number) {
  pageSize.value = size
  page.value = 1
  void load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <div>
        <h2 class="panel-title">最近日志</h2>
        <p class="panel-subtitle">读取后端当前日志文件的最近记录，便于本地排障。</p>
      </div>
      <div class="toolbar">
        <ElInput
          v-model="keyword"
          placeholder="筛选关键字"
          clearable
          style="width: 220px"
          @keyup.enter="onSearch"
          @clear="onSearch"
        />
        <ElButton @click="onSearch">查询</ElButton>
        <ElButton @click="load">刷新</ElButton>
      </div>
    </div>

    <ElTable
      v-loading="loading"
      :data="items"
      border
      style="margin-top: 16px"
      :header-cell-style="{ background: '#f5f7fa', fontWeight: 600 }"
    >
      <ElTableColumn prop="timestamp" label="时间" width="180" />
      <ElTableColumn prop="level" label="级别" width="100" />
      <ElTableColumn prop="logger" label="模块" width="180" />
      <ElTableColumn prop="message" label="消息" min-width="480" show-overflow-tooltip />
    </ElTable>

    <div class="pagination">
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
  flex-wrap: wrap;
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

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
