'use client'

import * as React from 'react'

import { fetchSettingsStatus, type SettingsStatusV } from '@/lib/api/settings'

/**
 * 系统状态的加载结果 + 它属于哪一次请求。
 *
 * 刻意不用 `loading | error | ready` 三态 + 在 effect 里同步 setState——
 * 那个写法触发级联渲染（React 的 `react-hooks/set-state-in-effect` 规则
 * 会报）。改成「结果 + 请求编号」：加载中与否从
 * `result.requestId !== requestId` 推导，与报告列表页的
 * `loadedFor !== currentPage` 同一套写法。
 */
export type SettingsResult =
  | { kind: 'loading'; requestId: number }
  | { kind: 'error'; message: string; requestId: number }
  | { kind: 'ready'; data: SettingsStatusV; requestId: number }

export interface SettingsStatusState {
  /** 当前请求编号。递增一次 = 重拉一次。 */
  requestId: number
  /** 最近一次请求的结果（可能属于更早的请求）。 */
  result: SettingsResult
  /** 重新拉取。 */
  reload: () => void
}

/**
 * 拉 `GET /api/v1/settings/status`。
 *
 * `requestId` 是 state：它同时是 effect 的依赖和「结果属于哪次请求」的
 * 判别依据。重拉时编号变了，旧结果立刻作废（页面回到加载态），
 * 新结果带着新编号回来才认。
 */
export function useSettingsStatus(): SettingsStatusState {
  const [requestId, setRequestId] = React.useState(1)
  const [result, setResult] = React.useState<SettingsResult>({ kind: 'loading', requestId: 1 })

  React.useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const data = await fetchSettingsStatus(controller.signal)
        setResult({ kind: 'ready', data, requestId })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setResult({
          kind: 'error',
          message: err instanceof Error ? err.message : '加载失败',
          requestId,
        })
      }
    })()
    return () => controller.abort()
  }, [requestId])

  const reload = React.useCallback(() => {
    setRequestId((prev) => prev + 1)
  }, [])

  return { requestId, result, reload }
}
