import type {
  FollowConfigDTO,
  FollowConfigUpdate,
  SignalServerConnectivityCheck,
  SignalServerConnectivityResult,
} from '@/types/config'
import { requestJson } from './http'

const BASE = '/api'

export function getConfig() {
  return fetch(`${BASE}/config`).then((r) => requestJson<FollowConfigDTO>(r))
}

export function updateConfig(data: FollowConfigUpdate) {
  return fetch(`${BASE}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then((r) => requestJson<FollowConfigDTO>(r))
}

export function testConnectivity(data: SignalServerConnectivityCheck) {
  return fetch(`${BASE}/config/connectivity`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then((r) => requestJson<SignalServerConnectivityResult>(r))
}
