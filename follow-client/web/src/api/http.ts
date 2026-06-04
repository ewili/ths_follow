export interface ApiErrorDetail {
  detail?: unknown
  message?: string
}

export async function parseApiError(response: Response): Promise<ApiErrorDetail> {
  try {
    const body = await response.json()
    return body as ApiErrorDetail
  } catch {
    return { message: `HTTP ${response.status}` }
  }
}

export async function requestJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw await parseApiError(response)
  }
  return response.json() as Promise<T>
}

export function getErrorMessage(err: unknown): string {
  if (!err || typeof err !== 'object') {
    return '请求失败'
  }
  const e = err as ApiErrorDetail
  const detail = e.detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; message?: string }
    return first.msg ?? first.message ?? '提交失败'
  }
  if (typeof detail === 'object' && detail !== null) {
    const d = detail as { msg?: string; message?: string }
    return d.msg ?? d.message ?? '提交失败'
  }
  if (typeof detail === 'string' && detail) {
    return detail
  }
  return e.message ?? '请求失败'
}
