import { onMounted, onUnmounted, ref } from 'vue'
import * as followApi from '@/api/follow'
import type { FollowStatusResponse } from '@/types/follow'

export function useFollowEngine() {
  const status = ref<FollowStatusResponse | null>(null)
  const startLoading = ref(false)
  const stopLoading = ref(false)
  const clearLoading = ref(false)
  const error = ref('')

  let timer: number | null = null

  async function refresh() {
    try {
      status.value = await followApi.getFollowStatus()
      error.value = ''
    } catch (err) {
      const e = err as { detail?: string; message?: string }
      error.value = e.detail ?? e.message ?? '获取跟单状态失败'
    }
  }

  async function start(coldStartAlignExisting: boolean) {
    startLoading.value = true
    try {
      status.value = await followApi.startFollow(coldStartAlignExisting)
      error.value = ''
      return true
    } catch (err) {
      const e = err as { detail?: string; message?: string }
      error.value = e.detail ?? e.message ?? '启动失败'
      return false
    } finally {
      startLoading.value = false
    }
  }

  async function stop() {
    stopLoading.value = true
    try {
      status.value = await followApi.stopFollow()
      error.value = ''
      return true
    } catch (err) {
      const e = err as { detail?: string; message?: string }
      error.value = e.detail ?? e.message ?? '停止失败'
      return false
    } finally {
      stopLoading.value = false
    }
  }

  async function clearTodayRecords() {
    clearLoading.value = true
    try {
      const result = await followApi.clearTodayRecords()
      error.value = ''
      await refresh()
      return result.deleted
    } catch (err) {
      const e = err as { detail?: string; message?: string }
      error.value = e.detail ?? e.message ?? '清空记录失败'
      return -1
    } finally {
      clearLoading.value = false
    }
  }

  onMounted(() => {
    void refresh()
    timer = window.setInterval(() => void refresh(), 3000)
  })

  onUnmounted(() => {
    if (timer !== null) clearInterval(timer)
  })

  return {
    status,
    startLoading,
    stopLoading,
    clearLoading,
    error,
    refresh,
    start,
    stop,
    clearTodayRecords,
  }
}
