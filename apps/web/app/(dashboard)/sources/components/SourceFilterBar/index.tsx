'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

/**
 * Filter & control sub-bar — category tabs + search + view switcher + sort.
 * Category state is local (visual only — the design lists counts per tab).
 */
export function SourceFilterBar() {
  const tabs = [
    { label: '全部', count: 847, active: true },
    { label: '文档 Documents', count: 412, active: false },
    { label: '网页 URLs', count: 287, active: false },
    { label: '订阅源 RSS', count: 148, active: false },
  ]

  return (
    <section className={styles.bar}>
      <div className={styles.tabs}>
        {tabs.map((tab) => (
          <button
            key={tab.label}
            type="button"
            className={`${styles.tab} ${tab.active ? styles.tabActive : ''} font-body-sm`}
          >
            <span>{tab.label}</span>
            <span
              className={`${styles.tabCount} font-code ${tab.active ? styles.tabCountActive : ''}`}
            >
              {tab.count}
            </span>
          </button>
        ))}
      </div>

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

        <div className={styles.viewSwitch} role="tablist" aria-label="视图切换">
          <button
            type="button"
            className={`${styles.viewBtn} ${styles.viewBtnActive} text-primary`}
            title="表格视图"
            aria-label="表格视图"
          >
            <IconSpan name="table_rows" size={18} />
          </button>
          <button type="button" className={styles.viewBtn} title="卡片视图" aria-label="卡片视图">
            <IconSpan name="grid_view" size={18} />
          </button>
        </div>

        <button type="button" className={`${styles.sortBtn} font-body-sm`}>
          <IconSpan name="sort" size={16} className="text-secondary" />
          <span className="text-[12px]">排序: 最近添加</span>
          <IconSpan name="expand_more" size={16} className="text-secondary" />
        </button>
      </div>
    </section>
  )
}
