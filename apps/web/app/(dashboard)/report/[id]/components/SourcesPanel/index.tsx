'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { ReportCitationV } from '@/lib/api/reports'
import { cn } from '@/lib/utils'
import styles from './index.module.css'

export interface SourcesPanelProps {
  /** 后端返回的引用表，顺序即角标顺序。 */
  citations: ReportCitationV[]
  /** 引用总条数——可能大于 `citations.length`（分页/截断时）。 */
  totalCount: number
  /** 当前高亮的角标编号（点击正文角标时由父组件传入）。 */
  highlightedN?: number
  /** 点击某条引用。 */
  onSelect?: (c: ReportCitationV) => void
}

/**
 * 「引用源溯源」面板。纯展示——引用表由父组件从接口取。
 *
 * 列表项是 button 而不是 `<a href="#">`：条目没有可跳转的外部地址，
 * 点击的含义是「在正文里定位这条引用」，由父组件的 `onSelect` 决定。
 */
export function SourcesPanel({ citations, totalCount, highlightedN, onSelect }: SourcesPanelProps) {
  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <IconSpan name="fact_check" size={20} className="text-primary" />
          <span className={cn(styles.title, 'font-headline-sm')}>引用源溯源 (Cited Sources)</span>
        </div>
        <span className={cn(styles.countChip, 'font-code')}>{totalCount} 条已收录</span>
      </header>

      <p className={cn(styles.lead, 'font-body-sm')}>
        以下条目与正文中的引用角标一一对应，点击可定位对应位置：
      </p>

      <div className={styles.list}>
        {citations.map((c) => (
          <button
            key={c.n}
            type="button"
            onClick={() => onSelect?.(c)}
            className={cn(styles.item, 'group', highlightedN === c.n && styles.itemHighlighted)}
          >
            <div className={styles.itemTop}>
              <span className={cn(styles.itemIndex, 'font-code')}>[{c.n}]</span>
              <span className={cn(styles.itemCiteCount, 'font-label-sm')}>
                被引 {c.cite_count} 次
              </span>
            </div>
            <span className={cn(styles.itemTitle, 'font-body-sm')}>{c.title}</span>
            {c.excerpt && (
              <span className={cn(styles.itemExcerpt, 'font-body-sm')}>{c.excerpt}</span>
            )}
            <div className={cn(styles.itemFoot, 'font-label-sm')}>
              <span>{formatPosition(c)}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * 切片位置。后端 `chunk_index` 是 0-based，展示时 +1；`page` 为 null = 非 PDF。
 */
function formatPosition(c: ReportCitationV): string {
  const chunk = `第 ${c.chunk_index + 1} 块`
  return c.page != null ? `${chunk} · 第 ${c.page} 页` : chunk
}
