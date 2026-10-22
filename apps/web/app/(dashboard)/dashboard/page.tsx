'use client'

/**
 * Dashboard page (Research Dashboard) — body only.
 * Sidebar + TopBar are owned by (dashboard)/layout.tsx; this page renders
 * only the inner content via the shared PageLayout.
 *
 * Composition:
 *   1. PageLayout header — title + DAG Cluster chip + greeting + 3 actions
 *   2. KPI grid (4 cards) — KpiCard
 *   3. RecentActivity — 最近报告活动流
 *   4. Explore grid — 最近报告卡片，点进去进 /report/{id}
 *
 * ## 数据源
 *
 *   - `GET /api/v1/dashboard`        → KPI 数字、最近报告
 *   - `GET /api/v1/settings/status`  → 向量化完成率、外部能力就绪数
 *
 * 原先这里是 `mock.ts` 里的一整页假数据（4 张 KPI 磁贴 + 8 条活动 +
 * 5 条订阅 + 3 张报告卡），数字全是编的。假数据已删。
 *
 * ## 加载态 / 错误态
 *
 * 沿用 reports 页的「结果 + 它属于哪次请求」判别联合：加载中与否从
 * `state.loadedFor !== reloadToken` **推导**出来，而不是在 effect 里同步
 * `setState({loading})`——那个写法触发级联渲染
 * （React 的 `react-hooks/set-state-in-effect` 规则会报）。
 */

import * as React from 'react'

import { PageLayout } from '@/components/common/PageLayout'
import { useUser } from '@/lib/auth'
import {
  fetchDashboard,
  fetchSettingsStatus,
  type DashboardV,
  type SettingsStatusV,
} from '@/lib/api/dashboard'

import { KpiCard } from './components/KpiCard'
import { RecentActivity } from './components/RecentActivity'
import { ExploreGrid } from './components/ExploreGrid'
import { GREETING, formatToday, toActivities, toExploreReports, toKpis } from './view'
import styles from './page.module.css'

/**
 * 加载结果 + 它属于哪次请求。
 *
 * `loadedFor` 存的是发起请求时的 `reloadToken`；token 变了但结果还没回来
 * （或失败）时，页面显示加载态而不是旧数据。
 */
type LoadState =
  | { kind: 'error'; message: string; loadedFor: number }
  | {
      kind: 'ready'
      dashboard: DashboardV
      /** 系统状态拉不到时为 null——KPI 少了完成率，其余照常。 */
      settings: SettingsStatusV | null
      /** 客户端取到的当前时间，用于页头的日期。 */
      today: Date
      loadedFor: number
    }

export default function DashboardPage() {
  const { user } = useUser()
  const [state, setState] = React.useState<LoadState | null>(null)
  const [reloadToken, setReloadToken] = React.useState(0)

  React.useEffect(() => {
    const controller = new AbortController()

    void (async () => {
      try {
        const dashboard = await fetchDashboard(controller.signal)
        // 系统状态是锦上添花：拉不到不该让整页报错，缺的那块降级即可。
        const settings = await fetchSettingsStatus(controller.signal).catch(() => null)
        if (controller.signal.aborted) return
        setState({ kind: 'ready', dashboard, settings, today: new Date(), loadedFor: reloadToken })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setState({
          kind: 'error',
          message: err instanceof Error ? err.message : '加载失败',
          loadedFor: reloadToken,
        })
      }
    })()

    return () => controller.abort()
  }, [reloadToken])

  // 加载中：还没结果，或结果是上一次请求的。
  const loading = state === null || state.loadedFor !== reloadToken
  const ready = state?.kind === 'ready' && state.loadedFor === reloadToken ? state : null
  const failed = state?.kind === 'error' && state.loadedFor === reloadToken ? state : null

  const greeting = `${GREETING}，${user?.display_name ?? '研究员'}`

  return (
    <PageLayout
      header={{
        title: '研究看板 (Research Dashboard)',
        enLabel: 'DAG Cluster v2.4',
        meta: [
          { text: greeting, emphasis: true },
          { text: ready ? formatToday(ready.today) : '—' },
          { text: '推理拓扑已就绪', dot: 'success' },
        ],
        actions: [
          { icon: 'notifications', ariaLabel: '通知中心' },
          { label: '偏好配置', icon: 'tune', variant: 'secondary' },
          {
            label: '发起新研究',
            icon: 'add',
            variant: 'primary',
            href: '/explore',
            shortcut: '⌘N',
            shortcutTone: 'dark',
          },
        ],
      }}
    >
      {loading && <p className="text-body-sm text-secondary">正在加载看板数据…</p>}

      {failed && (
        <p role="alert" className="text-body-sm text-error">
          看板加载失败：{failed.message}
          <button
            type="button"
            className="ml-2 underline"
            onClick={() => setReloadToken((t) => t + 1)}
          >
            重试
          </button>
        </p>
      )}

      {ready && (
        <>
          <section className={styles.kpiGrid}>
            {toKpis(ready.dashboard, ready.settings).map((k) => (
              <KpiCard key={k.id} kpi={k} />
            ))}
          </section>

          <RecentActivity items={toActivities(ready.dashboard.recent_reports)} />

          <ExploreGrid reports={toExploreReports(ready.dashboard.recent_reports)} />
        </>
      )}
    </PageLayout>
  )
}
