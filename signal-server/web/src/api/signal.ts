import type { SignalRuntimeStatus } from '@/types/signal'
import { requestJson } from './http'

const BASE = '/api/signal'

export function getSignalStatus() {
  return fetch(`${BASE}/status`).then((r) => requestJson<SignalRuntimeStatus>(r))
}

export function getSignalMode() {
  return fetch(`${BASE}/mode`).then((r) =>
    requestJson<{ signal_mode: 'ratio' | 'multiplier' }>(r),
  )
}

export function startSignal() {
  return fetch(`${BASE}/start`, { method: 'POST' }).then((r) =>
    requestJson<SignalRuntimeStatus>(r),
  )
}

export function stopSignal() {
  return fetch(`${BASE}/stop`, { method: 'POST' }).then((r) =>
    requestJson<SignalRuntimeStatus>(r),
  )
}
