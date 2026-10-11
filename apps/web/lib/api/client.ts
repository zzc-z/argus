/**
 * 后端 API 客户端。
 *
 * 前端跑在 3000，后端在 8000，跨域，所以每个请求都必须带
 * `credentials: 'include'`——不然浏览器的 cookie jar 不会带上 argus_session，
 * 后端一律回 401。这是跨域 + cookie 认证最容易踩的坑。
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000'

/** 后端错误响应体（FastAPI HTTPException 的形状）。 */
interface ApiErrorBody {
  detail?: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * 发一个带 cookie 的 JSON 请求。
 *
 * 401 单独抛出 ApiError（status 401），让调用方决定跳登录页还是弹提示——
 * 不在这里自动跳，因为 /me 这类接口在登录页刷新时被调用是正常的，
 * 自动跳会造成「刷新即跳转」的循环。
 */
export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  })

  if (!res.ok) {
    let message = `请求失败（${res.status}）`
    try {
      const body = (await res.json()) as ApiErrorBody
      if (body.detail) message = body.detail
    } catch {
      // 响应体不是 JSON（比如网关返回的 HTML 错误页），保留默认文案
    }
    throw new ApiError(res.status, message)
  }

  // 204 No Content 没有响应体，json() 会抛错
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/**
 * SSE 单帧的形状。后端 `app/services/stream.py::encode_frame` 产出：
 *
 *     data: {"type": "delta", "v": {"node_id": "writer", "text": "…"}}\n\n
 *
 * 事件类别放在 JSON 里的 `type` 字段而不是 SSE 原生的 `event:` 行——
 * 这样消费端只有一条解析路径：`split('\n\n')` → 去掉前缀 → JSON.parse
 * → switch (type)。`v` 是该类别自己的字段集。
 */
export type SseEvent = { type: string; v: Record<string, unknown> }

/**
 * 消费 SSE 流，逐帧回调。
 *
 * **不能用 EventSource**：它只支持 GET，且 withCredentials 默认 false。
 * 我们的端点是 POST + JSON body，而且必须带 argus_session cookie，
 * 两条都不满足。fetch + ReadableStream 是唯一可行组合。
 *
 * 错误分两层：HTTP 层（开流之前的 401 / 503 / 422，抛 ApiError，能读到
 * 后端的 detail）与流内层（开流之后的服务端错误，只能从 error 事件的
 * v.message 拿）。这是 SSE 的固有约束——响应头一旦发出就改不了状态码。
 */
export async function apiStream(
  path: string,
  body: unknown,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    let message = `请求失败（${res.status}）`
    try {
      const parsed = (await res.json()) as ApiErrorBody
      if (parsed.detail) message = parsed.detail
    } catch {
      // 网关返回的 HTML 错误页，保留默认文案
    }
    throw new ApiError(res.status, message)
  }

  if (!res.body) {
    throw new ApiError(500, '浏览器不支持流式响应')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  // SSE 以空行分帧，但一个 TCP 块可能只含半帧——必须自己按 \n\n 攒。
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        emitFrame(raw, onEvent)
        boundary = buffer.indexOf('\n\n')
      }
    }
    // 服务端可能在最后一帧后没再发 \n\n，把尾巴也处理掉
    if (buffer.trim()) emitFrame(buffer, onEvent)
  } finally {
    reader.releaseLock()
  }
}

/** 解析单帧。格式不对就跳过——一帧坏数据不该中断整个流。 */
function emitFrame(raw: string, onEvent: (event: SseEvent) => void): void {
  for (const line of raw.split('\n')) {
    if (!line.startsWith('data: ')) continue
    try {
      onEvent(JSON.parse(line.slice(6)) as SseEvent)
    } catch {
      // 非 JSON 的 data 行——忽略即可
    }
  }
}
