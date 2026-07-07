export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    const code = extractErrorCode(detail)
    super(code || `Request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

type JsonBody = Record<string, unknown> | unknown[]

export interface RequestOptions extends Omit<RequestInit, 'body' | 'headers'> {
  body?: BodyInit | JsonBody | null
  headers?: Record<string, string>
}

export async function request<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const init = buildRequestInit(options)
  const response = await fetch(path, init)

  if (!response.ok) {
    throw new ApiError(response.status, await parseResponseBody(response))
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await parseResponseBody(response)) as T
}

export async function downloadBlob(path: string): Promise<Blob> {
  const response = await fetch(path, {credentials: 'include'})
  if (!response.ok) {
    throw new ApiError(response.status, await parseResponseBody(response))
  }
  return response.blob()
}

function buildRequestInit(options: RequestOptions): RequestInit {
  const headers = {...options.headers}
  let body = options.body as BodyInit | null | undefined

  if (body !== undefined && body !== null && isJsonBody(body)) {
    headers['Content-Type'] = headers['Content-Type'] || 'application/json'
    body = JSON.stringify(body)
  }

  headers['Cache-Control'] = 'no-cache'
 
  return {
    ...options,
    credentials: 'include',
    cache: 'no-store',
    headers,
    body,
  }
}

function isJsonBody(body: RequestOptions['body']): body is JsonBody {
  return (
    typeof body === 'object' &&
    body !== null &&
    !(body instanceof Blob) &&
    !(body instanceof FormData) &&
    !(body instanceof URLSearchParams) &&
    !(body instanceof ArrayBuffer)
  )
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('Content-Type') || ''
  if (contentType.includes('application/json')) {
    return response.json()
  }
  const text = await response.text()
  return text.length > 0 ? text : undefined
}

function extractErrorCode(detail: unknown): string | undefined {
  if (!detail || typeof detail !== 'object') {
    return undefined
  }
  const maybeDetail = 'detail' in detail ? (detail as {detail?: unknown}).detail : detail
  if (maybeDetail && typeof maybeDetail === 'object' && 'code' in maybeDetail) {
    const code = (maybeDetail as {code?: unknown}).code
    return typeof code === 'string' ? code : undefined
  }
  return undefined
}
