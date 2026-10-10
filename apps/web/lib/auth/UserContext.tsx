'use client'

import * as React from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'

import { API_BASE, ApiError, apiFetch } from '@/lib/api/client'

/** 与后端 `app/schemas/user.py` 的 MeResponse 对齐。 */
export interface CurrentUser {
  id: number
  email: string | null
  display_name: string | null
  avatar_url: string | null
}

interface UserContextValue {
  user: CurrentUser | null
  /** 首次 /me 请求是否还在飞。用于避免刷新页面时闪一下「未登录」。 */
  loading: boolean
  refresh: () => Promise<void>
  logout: () => Promise<void>
  /** OAuth 登录入口——整页跳转到后端，由后端 307 到 GitHub。 */
  loginWithGithub: () => void
}

const UserContext = createContext<UserContextValue | null>(null)

/**
 * 登录态 Provider。
 *
 * 挂载时打一次 /api/v1/me：200 就是登录着，401 就是没登录。
 * 这个接口既是「取资料」也是「探活」——后端 JWT 过期后它会立刻 401，
 * 前端不需要额外的 token 过期判断逻辑。
 */
export function UserProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  const refresh = useCallback(async () => {
    try {
      setUser(await apiFetch<CurrentUser>('/api/v1/me'))
    } catch (err) {
      // 401 是「没登录」的正常状态，不是错误——静默归零即可。
      if (err instanceof ApiError && err.status === 401) {
        setUser(null)
      } else {
        // 网络挂了之类。同样归零，但保留 console 便于排查。
        console.error('[auth] 拉取当前用户失败', err)
        setUser(null)
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    // react-hooks/set-state-in-effect 的误报：setUser 发生在**异步网络请求的
    // 回调里**（await 之后），不是 effect body 里的同步调用。规则按语法位置
    // 判断，分不出同步/异步。拉远程数据进 state 只有两条路：effect 或框架的
    // 缓存层（React Query / SWR）。本项目不引数据层，effect 是唯一选择。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
  }, [refresh])

  const logout = useCallback(async () => {
    try {
      await apiFetch<void>('/api/v1/auth/logout', { method: 'POST' })
    } catch (err) {
      // 登出失败也要清本地状态：cookie 删不掉时，用户看到「已登出」
      // 但刷新又登录上，比报错更糟。
      console.error('[auth] 登出请求失败，仍按已登出处理', err)
    }
    setUser(null)
    router.push('/login')
  }, [router])

  const loginWithGithub = useCallback(() => {
    // 整页跳转而非 fetch：OAuth 流程要经过 GitHub 页面，必须走浏览器导航。
    // 后端 callback 成功后 307 到 /dashboard，所以这里不用管后续路由。
    // 必须整页跳转，不能用 router.push：OAuth 要经过 GitHub 的授权页、
    // 再 307 回后端 callback，这是一条跨站链路，客户端路由接管不了。
    // @next/next/no-location-assign-relative-destination 禁的是站内路由，
    // 这里是站外 API，规则误报。
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `${API_BASE}/api/v1/auth/github/login`
  }, [])

  const value = useMemo(
    () => ({ user, loading, refresh, logout, loginWithGithub }),
    [user, loading, refresh, logout, loginWithGithub],
  )

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>
}

export function useUser(): UserContextValue {
  const ctx = useContext(UserContext)
  if (!ctx) {
    throw new Error('useUser 必须在 <UserProvider> 内部使用')
  }
  return ctx
}
