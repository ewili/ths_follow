import type { TraderStatusResponse } from '@/types/follow'
import { requestJson } from './http'

const BASE = '/api/trader'

export function getTraderStatus() {
  return fetch(`${BASE}/status`).then((r) => requestJson<TraderStatusResponse>(r))
}

export function connectTrader() {
  return fetch(`${BASE}/connect`, { method: 'POST' }).then(async (r) => {
    if (!r.ok) {
      throw await r.json().catch(() => ({}))
    }
    return r.json() as Promise<TraderStatusResponse>
  })
}

export function disconnectTrader() {
  return fetch(`${BASE}/disconnect`, { method: 'POST' }).then((r) =>
    requestJson<TraderStatusResponse>(r),
  )
}
