/**
 * Dashboard page (Research Dashboard) — body only.
 * Sidebar + TopBar are owned by (dashboard)/layout.tsx; this page renders
 * only the inner content via the shared PageLayout.
 *
 * Composition:
 *   1. PageLayout header — title + DAG Cluster chip + greeting + 3 actions
 *   2. KPI grid (4 cards) — KpiCard
 *   3. Dual panel — RecentActivity (7 cols) | Subscriptions (5 cols)
 *   4. Explore grid — 3 report cards with cover image + CTA
 */

import { PageLayout } from '@/components/common/PageLayout'
import { KpiCard } from './components/KpiCard'
import { RecentActivity } from './components/RecentActivity'
import { Subscriptions } from './components/Subscriptions'
import { ExploreGrid } from './components/ExploreGrid'
import { KPIS, ACTIVITIES, SUBSCRIPTIONS, REPORTS } from './mock'
import styles from './page.module.css'

export default function DashboardPage() {
  return (
    <PageLayout
      header={{
        title: '研究看板 (Research Dashboard)',
        enLabel: 'DAG Cluster v2.4',
        meta: [
          { text: '早上好，Tony', emphasis: true },
          { text: '2026年9月19日 · 星期六' },
          { text: '推理拓扑已就绪', dot: 'success' },
        ],
        actions: [
          { icon: 'notifications', ariaLabel: '通知中心', badgeCount: 3 },
          { label: '偏好配置', icon: 'tune', variant: 'secondary' },
          {
            label: '发起新研究',
            icon: 'add',
            variant: 'primary',
            shortcut: '⌘N',
            shortcutTone: 'dark',
          },
        ],
      }}
    >
      <section className={styles.kpiGrid}>
        {KPIS.map((k) => (
          <KpiCard key={k.id} kpi={k} />
        ))}
      </section>

      <section className={styles.dualGrid}>
        <RecentActivity items={ACTIVITIES} />
        <Subscriptions items={SUBSCRIPTIONS} />
      </section>

      <ExploreGrid reports={REPORTS} />
    </PageLayout>
  )
}
