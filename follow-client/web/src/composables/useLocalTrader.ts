import { onMounted, onUnmounted, ref } from 'vue'
import * as traderApi from '@/api/trader'
import type { TraderStatusResponse } from '@/types/follow'

export function useLocalTrader() {
  const status = ref<TraderStatusResponse | null>(null)
  const connectLoading = ref(false)
  const disconnectLoading = ref(false)
  const error = ref('')

  let timer: number | null = null

  async function refresh() {
    try {
      status.value = await traderApi.getTraderStatus()
    } catch {
      /* ignore polling errors */
    }
  }

  async function connect() {
    connectLoading.value = true
    error.value = ''
    try {
      status.value = await traderApi.connectTrader()
      return true
    } catch (err) {
      const e = err as { detail?: string; message?: string }
      error.value = e.detail ?? e.message ?? '连接失败'
      return false
    } finally {
      connectLoading.value = false
    }
  }

  async function disconnect() {
    disconnectLoading.value = true
    error.value = ''
    try {
      status.value = await traderApi.disconnectTrader()
      return true
    } catch (err) {
      const e = err as { detail?: string; message?: string }
      error.value = e.detail ?? e.message ?? '断开失败'
      return false
    } finally {
      disconnectLoading.value = false
    }
  }

  onMounted(() => {
    void refresh()
    timer = window.setInterval(() => void refresh(), 5000)
  })

  onUnmounted(() => {
    if (timer !== null) clearInterval(timer)
  })

  return {
    status,
    connectLoading,
    disconnectLoading,
    error,
    connect,
    disconnect,
  }
}
