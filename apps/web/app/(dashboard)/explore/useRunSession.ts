'use client'

import * as React from 'react'
import { usePathname, useSearchParams } from 'next/navigation'

import { API_BASE, ApiError, apiStream, apiStreamGet, type SseEvent } from '@/lib/api/client'
import { parseEvent } from '@/lib/api/sse'
import type { RunEventV } from '@/lib/api/sse'

/**
 * 一次研究 run 的客户端会话。
 *
 * ## run id 在 URL 上（主流项目的做法）
 *
 * ChatGPT / Claude / Perplexity 都把会话 id 放进 URL。这不只是「刷新能
 * 恢复」——它还带来三件别处得不到的东西：
 *
 * 1. **可分享**：把链接发给别人，对方打开看到同一轮研究
 * 2. **可收藏**：浏览器的收藏夹能存住某一轮研究
 * 3. **多标签页隔离**：每个标签页有自己的 URL，各跑各的，互不干扰
 *
 * 第三条是 localStorage 方案做不到的 —— 它是全局一份，两个标签页会互相
 * 覆盖（一个标签页的提问被另一个抢走）。
 *
 * ## 为什么还要 localStorage
 *
 * 用户从别的页面直接点进 ``/explore``（地址栏里没有 run id），那一轮就
 * 接不回来了。localStorage 记着「我最近一轮是什么」，用来在无 id 时
 * 问一次后端、把 URL 补上。
 *
 * 两者分工：**URL 是权威**（分享、收藏、隔离都靠它），localStorage 只是
 * 「无 id 时的回退线索」。
 */

export interface RunSession {
  /**
   * 当前这一轮的 run id。
   *
   * 来自 URL。它是**权威**——刷新、分享、收藏都靠它。
   */
  runId: string | null
  /**
   * 连上这个 run。runId 为 null 时什么也不做。
   *
   * 内部会先 abort 上一次连接再重连（幂等）——StrictMode 下 effect 跑
   * 两遍时不会让同一批帧被处理两次。
   */
  connect: (runId: string | null) => void
  /**
   * 发起一轮新研究。
   *
   * 内部会：取消同一标签页上一轮（按 id 精确，不碰别的标签页）、
   * 把新 run id 写进 URL、发请求。
   */
  start: (question: string, onEvent: (event: SseEvent) => void) => Promise<void>
  /** 断开连接（不终止生成——生成在服务端跑着）。 */
  disconnect: () => void
  /**
   * 无 id 时问后端「我最近一轮是什么」。
   *
   * 返回 run id（没有就返回 null）。
   */
  findLatest: () => Promise<string | null>
}

export interface UseRunSessionOptions {
  /** 每收到一帧事件就调它。 */
  onEvent: (event: SseEvent) => void
  /** 本轮出错时调它（HTTP 层 / 网络层，流内的 error 帧不走这里）。 */
  onError: (err: unknown) => void
}

export function useRunSession({ onEvent, onError }: UseRunSessionOptions): RunSession {
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // URL 上的 run id。**它就是权威**。
  const runId = searchParams.get('run')

  // 当前的 AbortController。断开时 abort 它。
  const abortRef = React.useRef<AbortController | null>(null)
  // 本标签页正在跑的那一轮。重问时按它精确取消。
  const currentRunRef = React.useRef<string | null>(null)

  // 「最新回调」的 ref 模式。
  //
  // 调用方的 `onEvent` / `onError` 通常每次渲染都是新引用（它们捕获了
  // state setter）。如果把它们放进 `useCallback` 的依赖里，connect / start
  // 就会每次渲染都变 —— 而它们要被放进 effect 的依赖里，那条 effect 就
  // 每次渲染都重跑（连接被反复重建）。
  //
  // 所以用 ref 存「最新的那个」，effect 里更新它，连接函数读 ref。
  // **ref 只在 effect 里写** —— 渲染期间写 ref 是 React 明令禁止的
  // （`react-hooks/refs` 规则：渲染期间的 ref 值不可靠）。
  const onEventRef = React.useRef(onEvent)
  const onErrorRef = React.useRef(onError)
  React.useEffect(() => {
    onEventRef.current = onEvent
    onErrorRef.current = onError
  })

  const disconnect = React.useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  /**
   * 把 run id 写进 URL（查询参数 `run`）。
   *
   * 用 `window.history.replaceState` 而不是 `router.replace`：本项目开了
   * `typedRoutes`，`router.replace` 只接受**字面量**路由（动态拼出来的
   * 字符串编译不过）。而这里改的只是查询参数、路径不变 —— Next 官方文档
   * 给的正是这个用法（docs/01-app/02-guides/single-page-applications.md）。
   *
   * 用 `replaceState` 而非 `pushState`：重问/接回不该让浏览器后退键
   * 回到上一轮 —— 用户按后退期待的是离开这个页面，不是看上一轮的报告。
   *
   * Next 会 patch `history.replaceState`（app-router.js 里），所以改完
   * `useSearchParams` 会跟着更新，effect 会重新触发连接。
   */
  const writeRunIdToUrl = React.useCallback(
    (id: string) => {
      const params = new URLSearchParams(searchParams.toString())
      params.set('run', id)
      window.history.replaceState(null, '', `${pathname}?${params.toString()}`)
    },
    [pathname, searchParams],
  )

  const findLatest = React.useCallback(async (): Promise<string | null> => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/research/runs/latest`, {
        credentials: 'include',
        cache: 'no-store',
      })
      if (!res.ok) return null
      const body = (await res.json()) as { run_id?: string }
      const id = body.run_id
      if (!id) return null
      // 把找到的 run id 补进 URL —— 这样用户刷新 / 分享出去的链接都指向
      // 这一轮。`replaceState` 不加历史记录（不是「新页面」，只是把当前
      // 页面补全）。
      writeRunIdToUrl(id)
      return id
    } catch {
      return null
    }
  }, [writeRunIdToUrl])

  /** 订阅指定的 run。把事件转发给调用方。 */
  const openStream = React.useCallback((target: string) => {
    const controller = new AbortController()
    abortRef.current = controller
    currentRunRef.current = target

    void (async () => {
      try {
        await apiStreamGet(
          `/api/v1/research/runs/${encodeURIComponent(target)}/stream`,
          (event) => onEventRef.current(event),
          controller.signal,
        )
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        // 404 = 那一轮已经被 TTL 清理了（30 分钟没碰）。这不是错误——
        // 回到空态即可，用户看到「尚未提问」比看到一条红色横幅合理。
        if (err instanceof ApiError && err.status === 404) return
        onErrorRef.current(err)
      }
    })()
  }, [])

  const connect = React.useCallback(
    (target?: string | null) => {
      // 先断开上一次。幂等的前提就是这个 —— StrictMode 下 effect 跑两次
      // 时，第二次会 abort 掉第一次然后重新连，结果是「干净地重连一遍」。
      abortRef.current?.abort()
      abortRef.current = null

      // 目标 id：优先用调用方给的；没有就用 URL 上的；还没有就问后端
      // 「我最近一轮是什么」（用户从别的页面直接点进 /explore 的情况）。
      //
      // **查最近一轮放在这里，不在组件的 effect 里** —— effect 里同步
      // setState 会触发级联渲染（`react-hooks/set-state-in-effect` 规则）。
      // 这里整个流程都在异步闭包里，setState 发生在 await 之后。
      const wanted = target ?? runId
      if (wanted) {
        openStream(wanted)
        return
      }
      void (async () => {
        const latest = await findLatest()
        if (!latest) return
        openStream(latest)
      })()
    },
    [runId, findLatest, openStream],
  )

  const start = React.useCallback(
    async (question: string, onStartEvent: (event: SseEvent) => void) => {
      abortRef.current?.abort()

      const controller = new AbortController()
      abortRef.current = controller

      // 取消同一标签页上一轮。**按 id 精确**——用户可能开着两个标签页，
      // 按「用户最近一轮」会把另一个标签页的生成掐掉。
      const previous = currentRunRef.current

      try {
        await apiStream(
          '/api/v1/research/ask',
          { question, replace_run_id: previous ?? undefined },
          (event) => {
            // 第一帧带 run id —— 把它写进 URL（见 writeRunIdToUrl 的说明：
            // replaceState，不加历史记录）。
            if (event.type === 'run') {
              const run = parseEvent<RunEventV>(event)
              currentRunRef.current = run.run_id
              writeRunIdToUrl(run.run_id)
            }
            onStartEvent(event)
          },
          controller.signal,
        )
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        onErrorRef.current(err)
      }
    },
    [writeRunIdToUrl],
  )

  // 卸载时断开连接（**不终止生成**——生成在服务端跑着）。
  React.useEffect(
    () => () => {
      abortRef.current?.abort()
    },
    [],
  )

  return { runId, connect, start, disconnect, findLatest }
}
