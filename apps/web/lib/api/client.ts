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
