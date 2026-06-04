import type { FollowStatusResponse } from '@/types/follow'
import { requestJson } from './http'

const BASE = '/api/follow'

export function getFollowStatus() {
  return fetch(`${BASE}/status`).then((r) => requestJson<FollowStatusResponse>(r))
}

export function startFollow(coldStartAlignExisting = false) {
  const qs = new URLSearchParams({
    cold_start_align_existing: String(coldStartAlignExisting),
  })
  return fetch(`${BASE}/start?${qs.toString()}`, { method: 'POST' }).then((r) =>
    requestJson<FollowStatusResponse>(r),
  )
}

export function stopFollow() {
  return fetch(`${BASE}/stop`, { method: 'POST' }).then((r) =>
    requestJson<FollowStatusResponse>(r),
  )
}
