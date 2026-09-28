'use client'

import * as React from 'react'
import { TopicsHeader } from './components/TopicsHeader'
import { MetricsGrid } from './components/MetricsGrid'
import { FilterBar } from './components/FilterBar'
import { TopicTable } from './components/TopicTable'
import { TemplateCard } from './components/TemplateCard'
import { AgentLogCard } from './components/AgentLogCard'
import { NewSubscriptionDrawer } from './components/NewSubscriptionDrawer'

const OPEN_DRAWER_EVENT = 'argus:topics:open-drawer'
const CLOSE_DRAWER_EVENT = 'argus:topics:close-drawer'

import { TEMPLATES, AGENT_LOG } from './mock'

import styles from './page.module.css'

/**
 * 主题订阅管理 (Topic Subscriptions) page — 1:1 with argus_topics/code.html.
 *
 * Composition (top → bottom, identical to the source):
 *   1. TopicsHeader  — title + new-subscription CTA
 *   2. MetricsGrid   — 4 stat tiles
 *   3. FilterBar     — tabs + search + frequency + sort
 *   4. TopicTable    — main subscription table + footer / pagination
 *   5. Bottom row    — 2 preset templates + 1 live agent daemon card
 *   6. NewSubscriptionDrawer — right slide-over (mounted always, controlled by FilterBar / TopicsHeader)
 *
 * Server component — interactive state lives inside the client sub-components.
 */
export default function TopicsPage() {
  const [drawerOpen, setDrawerOpen] = React.useState(false)

  React.useEffect(() => {
    const open = () => setDrawerOpen(true)
    const close = () => setDrawerOpen(false)
    window.addEventListener(OPEN_DRAWER_EVENT, open)
    window.addEventListener(CLOSE_DRAWER_EVENT, close)
    return () => {
      window.removeEventListener(OPEN_DRAWER_EVENT, open)
      window.removeEventListener(CLOSE_DRAWER_EVENT, close)
    }
  }, [])

  return (
    <main className="px-space-lg pt-space-lg pb-space-xl bg-surface min-h-screen w-full">
      <div className="flex w-full flex-col">
        <TopicsHeader />

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
      </div>
    </main>
  )
}
