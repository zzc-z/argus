'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { SegmentedTab, type SegmentedTabItem } from '@/components/common/SegmentedTab'
import styles from './index.module.css'

const SOURCE_TABS: SegmentedTabItem[] = [
  { id: 'all', label: '全部', count: 847 },
  { id: 'docs', label: '文档 Documents', count: 412 },
  { id: 'urls', label: '网页 URLs', count: 287 },
  { id: 'rss', label: '订阅源 RSS', count: 148 },
]

/**
 * Filter & control sub-bar — category tabs + search + sort.
 * Category state is local (visual only — the design lists counts per tab).
 */
export function SourceFilterBar() {
  const [activeTabId, setActiveTabId] = React.useState<string>('all')

  return (
    <section className={styles.bar}>
      <SegmentedTab
        items={SOURCE_TABS}
        activeId={activeTabId}
        onChange={setActiveTabId}
        ariaLabel="资料库分类筛选"
      />

      <div className={styles.controls}>
        <label className={styles.search}>
          <IconSpan name="search" size={18} className="text-secondary" />
          <input
            type="text"
            placeholder="按名称、Hash值或标签检索..."
            className={`${styles.searchInput} font-body-sm`}
          />
          <span className={`${styles.kbd} font-code`}>⌘K</span>
        </label>

        <button type="button" className={`${styles.sortBtn} font-body-sm`}>
          <IconSpan name="sort" size={16} className="text-secondary" />
          <span className="text-[12px]">排序: 最近添加</span>
          <IconSpan name="expand_more" size={16} className="text-secondary" />
        </button>
      </div>
    </section>
  )
}
