import type {
  StockFetchResponse,
  StockPriceListResponse,
  StockStatusResponse,
} from '@/types/stock'
import { requestJson } from './http'

const BASE = '/api/stock'

export function getStockPrices(params: {
  page?: number
  size?: number
  keyword?: string
  trade_date?: string
}) {
  const search = new URLSearchParams()
  if (params.page) search.set('page', String(params.page))
  if (params.size) search.set('size', String(params.size))
  if (params.keyword) search.set('keyword', params.keyword)
  if (params.trade_date) search.set('trade_date', params.trade_date)
  return fetch(`${BASE}/prices?${search.toString()}`).then((r) =>
    requestJson<StockPriceListResponse>(r),
  )
}

export function triggerFetch() {
  return fetch(`${BASE}/fetch`, { method: 'POST' }).then((r) => {
    if (!r.ok) {
      return r.json().then((body) => {
        throw body
      })
    }
    return r.json() as Promise<StockFetchResponse>
  })
}

export function getStockStatus() {
  return fetch(`${BASE}/status`).then((r) => requestJson<StockStatusResponse>(r))
}
