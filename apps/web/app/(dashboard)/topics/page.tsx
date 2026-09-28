'use client'

import * as React from 'react'
import { PageLayout } from '@/components/common/PageLayout'
import { MetricsGrid } from './components/MetricsGrid'
import { FilterBar } from './components/FilterBar'
import { TopicTable } from './components/TopicTable'
import { TemplateCard } from './components/TemplateCard'
import { AgentLogCard } from './components/AgentLogCard'
import { NewSubscriptionDrawer } from './components/NewSubscriptionDrawer'
import { TEMPLATES, AGENT_LOG } from './mock'
import styles from './page.module.css'

const OPEN_DRAWER_EVENT = 'argus:topics:open-drawer'
const CLOSE_DRAWER_EVENT = 'argus:topics:close-drawer'

/**
 * 主题订阅管理 (Topic Subscriptions) page.
 *
 * Composition (top → bottom):
 *   - PageLayout header: eyebrow + title + subtitle + Cmd-N CTA + success pill
 *   - MetricsGrid, FilterBar, TopicTable, recommendSection (templates + agent log)
 *   - NewSubscriptionDrawer (mounted always, controlled via custom events)
 */
export default function TopicsPage() {
  const [drawerOpen, setDrawerOpen] = React.useState(false)

  const openDrawer = React.useCallback(() => {
    window.dispatchEvent(new CustomEvent(OPEN_DRAWER_EVENT))
  }, [])

  React.useEffect(() => {
    const open = () => setDrawerOpen(true)
    const close = () => setDrawerOpen(false)
    window.addEventListener(OPEN_DRAWER_EVENT, open)
    window.addEventListener(CLOSE_DRAWER_EVENT, close)

    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if ((e.metaKey || e.ctrlKey) && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault()
        openDrawer()
      }
    }
    window.addEventListener('keydown', onKey)

    return () => {
      window.removeEventListener(OPEN_DRAWER_EVENT, open)
      window.removeEventListener(CLOSE_DRAWER_EVENT, close)
      window.removeEventListener('keydown', onKey)
    }
  }, [openDrawer])

  return (
    <PageLayout
      header={{
        eyebrow: { tag: 'AGENT WORKSPACE // DAEMON-SUBS', note: 'DAG Cluster 巡检引擎已联机' },
        title: '主题订阅管理 (Topic Subscriptions)',
        subtitle:
          '当前已配置 7 个研究课题监控，已接入 847 个全网权威数据源与 RSS 高置信度流',
        actions: [
          {
            label: '新建研究订阅',
            icon: 'add',
            variant: 'primary',
            shortcut: '⌘N',
            onClick: openDrawer,
          },
        ],
      }}
    >
      <MetricsGrid />
      <FilterBar />
      <TopicTable />
      <section className={styles.recommendSection}>
        {TEMPLATES.map((tpl) => (
          <TemplateCard
            key={tpl.id}
            icon={tpl.icon}
            title={tpl.title}
            description={tpl.description}
            sourceCount={tpl.sourceCount}
          />
        ))}
        <AgentLogCard log={AGENT_LOG} />
      </section>

      <NewSubscriptionDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </PageLayout>
  )
}
