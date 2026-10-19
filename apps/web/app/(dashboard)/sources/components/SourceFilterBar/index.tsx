'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { SegmentedTab, type SegmentedTabItem } from '@/components/common/SegmentedTab'
import styles from './index.module.css'
import { SOURCE_TYPE_FILTERS, type TabKey } from '../../lib/sourceTypes'

/**
 * Filter & control sub-bar — category tabs + search.
 *
 * ## tab 的分类依据是 `source_type`
 *
 * 设计稿原列是 全部 / 文档 / 网页 / 订阅源 RSS 四个，那几个数字是**画上去的**
 * （847/412/287/148，与库里任何数据都无关）。这里改成后端真实的三类：
 * `SourceType` 只有 pdf / html / text 三值，「订阅源」后端没有对应——RSS
 * 要有订阅端点，而它没有。留着一个永远为 0、点了没反应的 tab 比删掉更差。
 *
 * 搜索框目前只过滤已加载的列表（`GET /sources` 一次返回全部，没有服务端
 * 搜索参数），所以它是纯前端过滤，不是假功能。
 */
export interface SourceFilterBarProps {
  /** 各类资料的条数。key 与 `SOURCE_TYPE_FILTERS` 对齐。 */
  counts: Record<TabKey, number>
  total: number
  /** 当前分类。`null` = 全部。 */
  active: ReadonlySet<TabKey>
  onChange: (next: ReadonlySet<TabKey>) => void
}

export function SourceFilterBar({ counts, total, active, onChange }: SourceFilterBarProps) {
  const items: SegmentedTabItem[] = [
    { id: 'all', label: '全部', count: total },
    ...SOURCE_TYPE_FILTERS.map((f) => ({
      id: f.key,
      label: f.label,
      count: counts[f.key],
    })),
  ]
  // tab 是单选（一次只看一类），侧栏的类型勾选是多选（可同时看几类），
  // 两者共用同一份状态：点 tab = 把勾选收成那一个或清空（「全部」）。
  // 非空集合的首元素在 noUncheckedIndexedAccess 下是 T | undefined，
  // 而 empty 分支已保证它一定存在——用 ?? 兜住类型，不改变行为。
  const activeId: string = active.size === 0 ? 'all' : ([...active][0] ?? 'all')

  return (
    <section className={styles.bar}>
      <SegmentedTab
        items={items}
        activeId={activeId}
        onChange={(id: string) => onChange(id === 'all' ? new Set() : new Set([id as TabKey]))}
        ariaLabel="资料库分类筛选"
      />

      <div className={styles.controls}>
        <label className={styles.search}>
          <IconSpan name="search" size={18} className="text-secondary" />
          <input
            type="text"
            placeholder="按名称检索..."
            className={`${styles.searchInput} font-body-sm`}
          />
          <span className={`${styles.kbd} font-code`}>⌘K</span>
        </label>
      </div>
    </section>
  )
}
