'use client'

import * as React from 'react'
import { PageLayout } from '@/components/common/PageLayout'
import { useNotifications, type NewNotificationInput } from '@/lib/notifications'
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
 * 主题订阅管理 (Topic Subscriptions) 页面。
 *
 * 自上而下组合：
 *   - PageLayout header：eyebrow + 标题 + 副标题 + Cmd-N CTA + success pill
 *   - MetricsGrid / FilterBar / TopicTable / recommendSection（模板 + agent 日志）
 *   - NewSubscriptionDrawer（始终挂载，通过自定义事件控制开关）
 *
 * drawer 提交时，向跨页 Notifications store push 一条订阅通知，
 * /notifications 页面就会把它作为新未读项显示在顶部。
 */
export default function TopicsPage() {
  const [drawerOpen, setDrawerOpen] = React.useState(false)
  const { pushNotification } = useNotifications()

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

  const handleActivate = React.useCallback(
    (input: NewNotificationInput) => {
      pushNotification(input)
      setDrawerOpen(false)
    },
    [pushNotification],
  )

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

      <NewSubscriptionDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onActivate={handleActivate}
      />
    </PageLayout>
  )
}
