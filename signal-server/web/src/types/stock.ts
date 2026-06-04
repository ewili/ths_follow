export interface StockPriceDTO {
  stock_code: string
  stock_name: string
  close_price: number
  limitup_price: number
  limitdown_price: number
  trade_date: string
  updated_at: string
}

export interface StockPriceListResponse {
  items: StockPriceDTO[]
  total: number
  trade_date: string | null
  page: number
  size: number
}

export interface StockFetchResponse {
  success: boolean
  count: number
  trade_date: string | null
  message: string
}

export interface StockStatusResponse {
  latest_trade_date: string | null
  stock_count: number
  scheduler_running: boolean
}
