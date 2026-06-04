export interface ApiErrorDetail {
  code?: string
  message?: string
  detail?: string
  msg?: string
}

export async function parseApiError(response: Response): Promise<ApiErrorDetail> {
  try {
    const body = await response.json()
    const detail = body.detail ?? body
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string; message?: string }
      return {
        code: 'VALIDATION_ERROR',
        message: first.msg ?? first.message ?? '请求参数错误',
        detail: JSON.stringify(detail),
      }
    }
    if (typeof detail === 'object' && detail !== null) {
      return detail as ApiErrorDetail
    }
    if (typeof detail === 'string') {
      return { message: detail }
    }
    return body as ApiErrorDetail
  } catch {
    return {
      code: 'UNKNOWN',
      message: `HTTP ${response.status}`,
      detail: '',
    }
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
  return e.message ?? e.detail ?? e.msg ?? '请求失败'
}
