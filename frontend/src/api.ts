const BASE = '/api/demo'

export class ApiError extends Error {
  code: string
  details: unknown
  constructor(message: string, code: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.details = details
  }
}

async function checked(response: Response): Promise<Response> {
  if (response.ok) return response
  let body: { error?: { code?: string; message?: string; details?: unknown }; detail?: unknown } = {}
  try { body = await response.json() } catch { /* response may be HTML when proxy is unavailable */ }
  throw new ApiError(body.error?.message || `请求失败（HTTP ${response.status}）`, body.error?.code || 'HTTP_ERROR', body.error?.details || body.detail)
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(`${BASE}${path}`, init) } catch {
    throw new ApiError('暂时无法连接本地服务，请确认后端已启动后重试。', 'NETWORK_ERROR')
  }
  return (await checked(response)).json() as Promise<T>
}

export async function downloadReport(id: string, format: 'json' | 'html'): Promise<void> {
  const response = await checked(await fetch(`${BASE}/analyses/${encodeURIComponent(id)}/export?format=${format}`))
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `regresslab-${id}.${format}`
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
