export interface FollowStatusResponse {
  running: boolean
  cold_start_align_existing: boolean | null
  start_time: string | null
  follow_mode: 'ratio' | 'multiplier'
  follow_multiplier: number
}

export type TraderConnectionState = 'disconnected' | 'connected' | 'error'

export interface TraderStatusResponse {
  state: TraderConnectionState
  last_error: string | null
  last_connect_at: string | null
}
