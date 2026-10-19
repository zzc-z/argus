'use client'

import * as React from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'

import { API_BASE, ApiError, apiFetch } from '@/lib/api/client'
import { clearChunkCache } from '@/lib/api/sources'

/** 与后端 `app/schemas/user.py` 的 MeResponse 对齐。 */
export interface CurrentUser {
  id: number
  email: string | null
  display_name: string | null
  avatar_url: string | null
}

/** `/me` 的三种结果，**必须区分**「没登录」与「问不到」。 */
export type AuthStatus = 'loading' | 'authenticated' | 'anonymous' | 'unreachable'

interface UserContextValue {
  user: CurrentUser | null
  /** 首次 /me 请求是否还在飞。用于避免刷新页面时闪一下「未登录」。 */
  loading: boolean
  /**
   * 为什么需要它：只有 401 能证明「用户没登录」。网络失败、后端 500、
   * 后端发版重启——这些都**不能**。三年前把它们和 401 一起归零的写法，
   * 会让后端抖一下就把全站用户踢去走 OAuth。
   *
   * 守卫据此区分：`anonymous` 才跳登录页，`unreachable` 该显示「连不上」，
   * 让用户重试，而不是逼他重新授权。
   */
  status: AuthStatus
  refresh: () => Promise<void>
  logout: () => Promise<void>
  /** OAuth 登录入口——整页跳转到后端，由后端 307 到 GitHub。 */
  loginWithGithub: (next?: string) => void
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
  const [status, setStatus] = useState<AuthStatus>('loading')
  const router = useRouter()

  const refresh = useCallback(async () => {
    try {
      setUser(await apiFetch<CurrentUser>('/api/v1/me'))
      setStatus('authenticated')
    } catch (err) {
      // **只有 401 能证明「没登录」**。其余（网络挂、后端 500、发版重启）
      // 归 unreachable —— 守卫看到它不会把用户踢去 OAuth。
      if (err instanceof ApiError && err.status === 401) {
        setUser(null)
        setStatus('anonymous')
      } else {
        console.error('[auth] 拉取当前用户失败', err)
        setUser(null)
        setStatus('unreachable')
      }
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
    // 模块级缓存不会因客户端导航而重置（logout 走 router.push，不重载页面）。
    // 不清的话上一个用户的私有资料全文留在 JS 堆里，且下次命中缓存连一次
    // 鉴权请求都不发——「资料已删除」「权限已撤销」都感知不到。
    clearChunkCache()
    setUser(null)
    setStatus('anonymous')
    router.push('/login')
  }, [router])

  const loginWithGithub = useCallback((next?: string) => {
    // 整页跳转而非 fetch：OAuth 流程要经过 GitHub 页面，必须走浏览器导航。
    // 必须整页跳转，不能用 router.push：OAuth 要经过 GitHub 的授权页、
    // 再 307 回后端 callback，这是一条跨站链路，客户端路由接管不了。
    //
    // `next` 让登录完成后回到用户原本要去的页面——后端把它存进**签名**
    // cookie（app/gateway/auth.py 的 OAuthFlowState.next_path），所以中间人
    // 改不了目标。不传就落 /dashboard。
    // @next/next/no-location-assign-relative-destination 禁的是站内路由，
    // 这里是站外 API，规则误报。
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `${API_BASE}/api/v1/auth/github/login${
      next ? `?next=${encodeURIComponent(next)}` : ''
    }`
  }, [])

  // loading 保留是为了兼容既有调用方；语义上就是 status === 'loading'。
  const value = useMemo(
    () => ({
      user,
      loading: status === 'loading',
      status,
      refresh,
      logout,
      loginWithGithub,
    }),
    [user, status, refresh, logout, loginWithGithub],
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
