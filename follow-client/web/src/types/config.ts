export type GridStrategy = 'Copy' | 'Xls' | 'WMCopy'
export type CaptchaMode = 'local' | 'vlm' | 'auto'
export type HistoryEntrustPeriod = '当日' | '近一周' | '近一月' | '近三月' | '近一年'
export type EntrustSource = 'today' | 'history'

export interface TimeRange {
  start: string
  end: string
}

export interface FollowConfigDTO {
  signal_server_url: string
  poll_interval_ms: number
  local_ths_exe_path: string
  cold_start_align_existing: boolean
  use_type_keys: boolean
  grid_strategy: GridStrategy
  captcha_mode: CaptchaMode
  vlm_api_key: string
  captcha_auto_fail_threshold: number
  captcha_vlm_call_count: number
  schedule_enabled: boolean
  schedule_weekdays: number[]
  schedule_time_ranges: TimeRange[]
  history_entrust_period: HistoryEntrustPeriod
  entrust_source: EntrustSource
  updated_at: string
}

export interface FollowConfigUpdate {
  signal_server_url: string
  poll_interval_ms: number
  local_ths_exe_path: string
  cold_start_align_existing: boolean
  use_type_keys: boolean
  grid_strategy: GridStrategy
  captcha_mode: CaptchaMode
  vlm_api_key: string
  captcha_auto_fail_threshold: number
  captcha_vlm_call_count: number
  schedule_enabled: boolean
  schedule_weekdays: number[]
  schedule_time_ranges: TimeRange[]
  history_entrust_period: HistoryEntrustPeriod
  entrust_source: EntrustSource
}

export interface SignalServerConnectivityCheck {
  signal_server_url: string
}

export interface SignalServerConnectivityResult {
  ok: boolean
  message: string
}
