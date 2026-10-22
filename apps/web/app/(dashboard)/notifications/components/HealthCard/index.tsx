'use client'

import * as React from 'react'
import { apiFetch } from '@/lib/api/client'
import styles from './index.module.css'

/** `GET /api/v1/healthz` 的响应体（见 apps/api/app/schemas/health.py）。 */
interface HealthPayload {
  status: string
  service: string
  version: string
  detail: string | null
}

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: HealthPayload }
  | { kind: 'error'; message: string }

/**
 * 右侧栏卡片 —— 后端服务健康状态。
 *
 * 数据源：真实的 `GET /api/v1/healthz`（存活探针，不查外部依赖，
 * 所以只要进程在就返回 200）。
 *
 * 原版这张卡展示的是"3 个信源的心跳 + 自动恢复 + 手动全量轮询"——
 * 后端既没有信源心跳接口，也没有恢复 / 轮询接口，那些是编的，已删除。
 * 现在只显示探针真正返回的四个字段。
 */
export function HealthCard() {
  const [state, setState] = React.useState<HealthState>({ kind: 'loading' })

  React.useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const data = await apiFetch<HealthPayload>('/api/v1/healthz', {
          signal: controller.signal,
        })
        setState({ kind: 'ready', data })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setState({
          kind: 'error',
          message: err instanceof Error ? err.message : '健康检查请求失败',
        })
      }
    })()
    return () => controller.abort()
  }, [])

  return (
    <section className={styles.card}>
      <header className={styles.header}>
        <h3 className={styles.title}>后端服务健康</h3>
        <span className={styles.score}>{statusLabel(state)}</span>
      </header>

      <div className={styles.sources}>
        {state.kind === 'loading' && <span className={styles.sourceLabel}>检查中…</span>}
        {state.kind === 'error' && <span className={styles.valueWarn}>{state.message}</span>}
        {state.kind === 'ready' && (
          <>
            <div className={styles.sourceRow}>
              <span className={styles.sourceLabel}>服务</span>
              <span className={styles.valueOk}>{state.data.service}</span>
            </div>
            <div className={styles.sourceRow}>
              <span className={styles.sourceLabel}>版本</span>
              <span className={styles.valueOk}>{state.data.version}</span>
            </div>
            {state.data.detail && (
              <div className={styles.sourceRow}>
                <span className={styles.sourceLabel}>详情</span>
                <span className={styles.valueWarn}>{state.data.detail}</span>
              </div>
            )}
          </>
        )}
      </div>

      <div className={styles.recovery}>
        <span className={styles.recoveryLabel}>探针：/api/v1/healthz</span>
      </div>
    </section>
  )
}

function statusLabel(state: HealthState): string {
  if (state.kind === 'loading') return '…'
  if (state.kind === 'error') return 'UNREACHABLE'
  return state.data.status.toUpperCase()
}
