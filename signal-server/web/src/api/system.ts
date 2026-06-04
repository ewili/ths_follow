import type {
  SystemConfigResponse,
  SystemConfigUpdate,
} from '@/types/config'
import type {
  DashboardStatusResponse,
  DiagnosticSnapshot,
  OperationLogResponse,
} from '@/types/system'
import { requestJson } from './http'

const BASE = '/api/system'

export function getConfig() {
  return fetch(`${BASE}/config`).then((r) => requestJson<SystemConfigResponse>(r))
}

export function updateConfig(data: SystemConfigUpdate) {
  return fetch(`${BASE}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then((r) => requestJson<SystemConfigResponse>(r))
}

export function connectTerminal() {
  return fetch(`${BASE}/connect`, { method: 'POST' }).then((r) =>
    requestJson<SystemConfigResponse>(r),
  )
}

export function disconnectTerminal() {
  return fetch(`${BASE}/disconnect`, { method: 'POST' }).then((r) =>
    requestJson<SystemConfigResponse>(r),
  )
}

export function healthCheck() {
  return fetch(`${BASE}/health`).then((r) => requestJson<SystemConfigResponse>(r))
}

export function getDashboardStatus() {
  return fetch(`${BASE}/status`).then((r) => requestJson<DashboardStatusResponse>(r))
}

export function getDiagnostics() {
  return fetch(`${BASE}/diagnostics`).then((r) => requestJson<DiagnosticSnapshot>(r))
}

export function getLogs(params?: { page?: number; size?: number; keyword?: string }) {
  const search = new URLSearchParams()
  search.set('page', String(params?.page ?? 1))
  search.set('size', String(params?.size ?? 50))
  if (params?.keyword?.trim()) {
    search.set('keyword', params.keyword.trim())
  }
  return fetch(`${BASE}/logs?${search.toString()}`).then((r) =>
    requestJson<OperationLogResponse>(r),
  )
}
