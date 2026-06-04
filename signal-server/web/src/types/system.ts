import type { ConnectionStatus } from './config'

export type SignalRuntimeState = 'stopped' | 'running'

export interface SignalRuntimeStatus {
  state: SignalRuntimeState
  started_at: string | null
  last_changed_at: string | null
  schedule_active: boolean
  signal_mode: 'ratio' | 'multiplier'
}

export interface DashboardStatusResponse {
  connection: ConnectionStatus
  signal: SignalRuntimeStatus
  latest_stock_trade_date: string | null
  stock_count: number
  balance_fetched_at: string | null
  position_fetched_at: string | null
  entrusts_fetched_at: string | null
  gui_latency_p50_ms: number
  gui_latency_p95_ms: number
}

export interface DiagnosticSnapshot {
  gui_latency_p50_ms: number
  gui_latency_p95_ms: number
  cache_hit_rate: number
  cache_hits: number
  cache_misses: number
  captcha_count: number
  dialog_count: number
  avg_lock_wait_ms: number
  recent_gui_calls: Array<{
    operation: string
    gui_elapsed_ms: number
    lock_wait_ms: number
  }>
}

export interface OperationLogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
}

export interface OperationLogResponse {
  items: OperationLogEntry[]
  total: number
  page: number
  size: number
}
