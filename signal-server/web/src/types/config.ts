export type GridStrategy = 'Copy' | 'Xls' | 'WMCopy'
export type CaptchaMode = 'local' | 'vlm' | 'auto'
export type HistoryEntrustPeriod = '当日' | '近一周' | '近一月' | '近三月' | '近一年'
export type ConnectionState = 'disconnected' | 'connected' | 'error'

export interface TimeRange {
  start: string
  end: string
}

export interface SystemConfigDTO {
  ths_exe_path: string
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
  updated_at: string
}

export interface SystemConfigUpdate {
  ths_exe_path: string
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
}

export interface ConnectionStatus {
  state: ConnectionState
  last_error: string | null
  last_connect_at: string | null
}

export interface SystemConfigResponse {
  config: SystemConfigDTO
  status: ConnectionStatus
}
