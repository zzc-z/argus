'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { FILTER_TABS, TOPICS } from '../../mock'
import styles from './index.module.css'

export type TopicsFilter = (typeof FILTER_TABS)[number]['id']

export interface FilterBarProps {
  /** Available topics — used by the refresh button's "force run all" hook later. */
  topics?: typeof TOPICS
}

/**
 * Filter, segmented tabs, search, frequency & sort. Pure presentational —
 * internal state is local. The "refresh" button only animates an icon; force
 * rescan is a future backend concern.
 *
 * Owns one piece of cross-cutting wiring: it listens for the
 * `argus:topics:open-drawer` CustomEvent dispatched by TopicsHeader and forwards
 * a second event to the drawer (single source of truth = the event channel).
 */
export function FilterBar(_props: FilterBarProps) {
  const [activeTab, setActiveTab] = React.useState<TopicsFilter>('all')
  const [search, setSearch] = React.useState('')
  const [refreshing, setRefreshing] = React.useState(false)

  const onRefresh = () => {
    setRefreshing(true)
    window.setTimeout(() => setRefreshing(false), 700)
  }

  return (
    <section className={styles.bar}>
      <div className={styles.tabs} role="tablist" aria-label="订阅状态筛选">
        {FILTER_TABS.map((tab) => {
          const isActive = tab.id === activeTab
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveTab(tab.id)}
              className={`${styles.tab} ${isActive ? styles.tabActive : ''} font-body-sm`}
            >
              <span>{tab.label}</span>
              <span
                className={`${styles.tabCount} font-code ${isActive ? styles.tabCountActive : ''}`}
              >
                {tab.count}
              </span>
            </button>
          )
        })}
      </div>

      <div className={styles.controls}>
        <div className={styles.search}>
          <IconSpan name="search" size={18} className="text-secondary absolute left-3" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索课题名称、监控关键词或信源..."
            className={`${styles.searchInput} font-body-sm`}
          />
          <kbd className={`${styles.searchKbd} font-code`}>/</kbd>
        </div>

        <button type="button" className={`${styles.dropdown} font-body-sm`}>
          <IconSpan name="schedule" size={16} className="text-secondary" />
          <span>更新频率: 全部</span>
          <IconSpan name="expand_more" size={16} className="text-secondary" />
        </button>

        <button type="button" className={`${styles.dropdown} font-body-sm`}>
          <IconSpan name="sort" size={16} className="text-secondary" />
          <span>最近更新优先</span>
          <IconSpan name="expand_more" size={16} className="text-secondary" />
        </button>

        <button type="button" title="强制全量探测" className={styles.refresh} onClick={onRefresh}>
          <IconSpan
            name="sync"
            size={20}
            className={`text-secondary ${refreshing ? styles.refreshSpin : ''}`}
          />
        </button>
      </div>
    </section>
  )
}
