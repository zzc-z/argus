'use client'

import { TopicsHeader } from './components/TopicsHeader'
import { MetricsGrid } from './components/MetricsGrid'
import { FilterBar } from './components/FilterBar'
import { TopicTable } from './components/TopicTable'
import { TemplateCard } from './components/TemplateCard'
import { AgentLogCard } from './components/AgentLogCard'
import { NewSubscriptionDrawer } from './components/NewSubscriptionDrawer'

import { TEMPLATES, AGENT_LOG } from './mock'

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
  return (
    <main className="px-space-lg pt-space-lg pb-space-xl bg-surface min-h-screen w-full">
      <div className="flex w-full flex-col">
        <TopicsHeader />

        <MetricsGrid />

        <FilterBar />

        <TopicTable />

        <section className="gap-space-md mt-space-lg grid grid-cols-1 lg:grid-cols-3">
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

        <NewSubscriptionDrawer />
      </div>
    </main>
  )
}
