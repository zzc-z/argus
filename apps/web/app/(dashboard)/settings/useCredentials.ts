'use client'

import * as React from 'react'

import { fetchCredentials, type CredentialsV } from '@/lib/api/settings'

/**
 * 凭据配置的面板状态。
 *
 * 三态要分清（异步数据的硬要求）：
 * - `loading` —— 还没拿到过数据
 * - `error`   —— 拿过且失败了
 * - `ready`   —— 有数据
 *
 * **重拉期间保持 `ready`（继续显示旧值），不回落到 `loading`。**
 * 保存成功要触发重拉（刷新「值来自哪一层」），若重拉期间面板闪回
 * 加载态，挂在面板里的提示会跟着被卸载——用户刚点保存，提示就没了。
 */
export type CredentialsState =
  { kind: 'loading' } | { kind: 'error'; message: string } | { kind: 'ready'; data: CredentialsV }

export interface CredentialsLoad {
  /** 面板该渲染的状态。 */
  state: CredentialsState
  /** 重新拉取。 */
  reload: () => void
}

/**
 * 拉 `GET /api/v1/settings/credentials`。
 *
 * `requestId` 是 state：它同时是 effect 的依赖和「结果属于哪次请求」的
 * 判别依据。重拉时编号变了，旧结果立刻作废，新结果带着新编号回来才认。
 *
 * 但**对外的状态不跟着 requestId 作废**——`data` 单独存着，重拉期间
 * 继续对外报 `ready`（见 `CredentialsState` 的注释）。
 */
export function useCredentials(): CredentialsLoad {
  const [requestId, setRequestId] = React.useState(1)
  const [result, setResult] = React.useState<
    { kind: 'error'; message: string; requestId: number } | { kind: 'ready'; requestId: number }
  >({ kind: 'ready', requestId: 1 })
  // 最近一次成功的数据。与 `result` 分开存——重拉时 result 作废，
  // 但这份数据要留着给面板显示。
  const [data, setData] = React.useState<CredentialsV | null>(null)

  React.useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const loaded = await fetchCredentials(controller.signal)
        setResult({ kind: 'ready', requestId })
        setData(loaded)
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

  const state = React.useMemo<CredentialsState>(() => {
    // **最新的请求失败了 → 先报错误。**
    //
    // ⚠️ 顺序要紧：若把「有过数据就用它」放在前面，一旦首屏加载成功，
    // 之后的**每一次重拉失败**都被永久吞掉——面板停在旧值、无任何提示，
    // 而页面上还挂着「配置已保存」的绿色提示。用户在骗自己。
    //
    // 旧的请求的失败不算数（已被新一轮取代）。
    if (result.kind === 'error' && result.requestId === requestId) {
      return { kind: 'error', message: result.message }
    }
    // 有过数据就一直用它——**重拉期间**不闪回加载态。
    if (data) return { kind: 'ready', data }
    return { kind: 'loading' }
  }, [data, result, requestId])

  return { state, reload }
}
