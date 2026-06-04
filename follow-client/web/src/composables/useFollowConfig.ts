import { onMounted, ref } from 'vue'
import * as configApi from '@/api/config'
import type { FollowConfigDTO, FollowConfigUpdate } from '@/types/config'
import type { SignalServerConnectivityResult } from '@/types/config'

export function useFollowConfig() {
  const config = ref<FollowConfigDTO | null>(null)
  const loading = ref(false)
  const saveLoading = ref(false)
  const probeLoading = ref(false)
  const lastApiError = ref<unknown>(null)

  async function fetchConfig() {
    loading.value = true
    try {
      config.value = await configApi.getConfig()
      lastApiError.value = null
    } catch (err) {
      lastApiError.value = err
    } finally {
      loading.value = false
    }
  }

  async function saveConfig(data: FollowConfigUpdate) {
    saveLoading.value = true
    try {
      config.value = await configApi.updateConfig(data)
      lastApiError.value = null
      return true
    } catch (err) {
      lastApiError.value = err
      return false
    } finally {
      saveLoading.value = false
    }
  }

  async function testConnectivity(
    data: { signal_server_url: string },
  ): Promise<SignalServerConnectivityResult | null> {
    probeLoading.value = true
    try {
      const result = await configApi.testConnectivity(data)
      lastApiError.value = null
      return result
    } catch (err) {
      lastApiError.value = err
      return null
    } finally {
      probeLoading.value = false
    }
  }

  onMounted(() => {
    void fetchConfig()
  })

  return {
    config,
    loading,
    saveLoading,
    probeLoading,
    lastApiError,
    fetchConfig,
    saveConfig,
    testConnectivity,
  }
}
