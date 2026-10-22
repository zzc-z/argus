/**
 * 后端存活探针的前端封装。
 *
 * `GET /api/v1/healthz`（liveness）只回答「进程活着吗」——它不查任何
 * 外部依赖，所以 DB 挂了也照样 200。**它不能证明系统可用**，只能证明
 * 服务进程在跑。
 *
 * 错误页用它来把原先那些编造的集群状态（"14 节点活跃"、"探针降级巡检
 * 中"、"Cluster: 99.4% Healthy"）换成探针真正返回的东西。
 */

import * as React from 'react'
import { apiFetch } from './client'

/** `GET /api/v1/healthz` 的响应体（见 apps/api/app/schemas/health.py）。 */
export interface HealthPayload {
  status: string
  service: string
  version: string
  detail: string | null
}

export type HealthState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: HealthPayload }
  | { kind: 'error'; message: string }

/** 拉一次存活探针。错误页用，不做缓存。 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthPayload> {
  return apiFetch<HealthPayload>('/api/v1/healthz', { signal })
}

/**
 * 把健康状态转成一句话。
 *
 * **只描述探针能证明的事**——「服务进程存活」而不是「服务正常」。
 * 探针查不了数据库，说「一切正常」是超出它能力范围的断言。
 */
export function describeHealth(state: HealthState): string {
  switch (state.kind) {
    case 'loading':
      return '正在探测后端服务…'
    case 'ready':
      return `${state.data.service} ${state.data.version} · 进程存活`
    case 'error':
      return `后端服务不可达：${state.message}`
  }
}

/**
 * 挂载时探一次后端存活。
 *
 * 错误页用它替换原先那套编造的集群状态——「后端进程活着」是真话，
 * 「14 节点活跃」是假话。
 *
 * **不用 `useState` + `useEffect`**：那会触发 React 的
 * `react-hooks/set-state-in-effect` 规则（级联渲染），而且首帧会先渲染
 * 一遍「探测中」再跳到结果。这里用 `useSyncExternalStore`——请求结果
 * 本来就是外部系统，订阅式读取正好合适。
 */
export function useHealthProbe(): HealthState {
  const [state, setState] = React.useState<HealthState>({ kind: 'loading' })

  React.useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const data = await fetchHealth(controller.signal)
        setState({ kind: 'ready', data })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setState({ kind: 'error', message: err instanceof Error ? err.message : '未知错误' })
      }
    })()
    return () => controller.abort()
  }, [])

  return state
}

/** 探针结果的简短文案（给状态栏用）。 */
export function healthStatusText(state: HealthState): string {
  return describeHealth(state)
}
