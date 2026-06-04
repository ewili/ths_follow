import { onMounted, ref } from 'vue'
import * as systemApi from '@/api/system'
import type { SystemConfigDTO, SystemConfigUpdate } from '@/types/config'
import type { ConnectionStatus } from '@/types/config'

export function useSystemConfig() {
  const config = ref<SystemConfigDTO | null>(null)
  const status = ref<ConnectionStatus>({
    state: 'disconnected',
    last_error: null,
    last_connect_at: null,
  })
  const loading = ref(false)
  const saveLoading = ref(false)
  const actionLoading = ref(false)

  function applyResponse(res: Awaited<ReturnType<typeof systemApi.getConfig>>) {
    config.value = res.config
    status.value = res.status
  }

  async function fetchConfig() {
    loading.value = true
    try {
      applyResponse(await systemApi.getConfig())
    } finally {
      loading.value = false
    }
  }

  async function saveConfig(data: SystemConfigUpdate) {
    saveLoading.value = true
    try {
      applyResponse(await systemApi.updateConfig(data))
      return true
    } catch {
      return false
    } finally {
      saveLoading.value = false
    }
  }

  async function connect() {
    actionLoading.value = true
    try {
      applyResponse(await systemApi.connectTerminal())
      return true
    } catch {
      return false
    } finally {
      actionLoading.value = false
    }
  }

  async function disconnect() {
    actionLoading.value = true
    try {
      applyResponse(await systemApi.disconnectTerminal())
      return true
    } catch {
      return false
    } finally {
      actionLoading.value = false
    }
  }

  async function health() {
    actionLoading.value = true
    try {
      applyResponse(await systemApi.healthCheck())
      return true
    } catch {
      return false
    } finally {
      actionLoading.value = false
    }
  }

  onMounted(() => {
    void fetchConfig()
  })

  return {
    config,
    status,
    loading,
    saveLoading,
    actionLoading,
    fetchConfig,
    saveConfig,
    connect,
    disconnect,
    health,
  }
}
