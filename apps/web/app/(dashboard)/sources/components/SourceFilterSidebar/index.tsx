'use client'

import * as React from 'react'
import styles from './index.module.css'
import {
  ROW_STATUS_FILTERS,
  SOURCE_TYPE_FILTERS,
  type RowStatus,
  type RowStatusFilter,
  type SourceTypeFilter,
} from '../../lib/sourceTypes'

/** 类型筛选的选中态。空集合 = 全选（与设计稿的「5 类全勾」一致）。 */
export type TypeSelection = ReadonlySet<SourceTypeFilter['key']>

/** 索引状态的选中态，key 是后端 `SourceStatus` 的原值。 */
export type StatusSelection = ReadonlySet<RowStatusFilter['key']>

export interface SourceFilterSidebarProps {
  /** 每种类型的资料条数，由列表数据现算。 */
  /** 条数允许缺失：某个类型 0 条时就不该显示这一行。 */
  typeCounts: Record<SourceTypeFilter['key'], number | undefined>
  /** 每个状态（`indexed` / `processing` / `failed`）的条数，现算。 */
  statusCounts: Record<RowStatusFilter['key'], number | undefined>
  selectedTypes: TypeSelection
  onToggleType: (key: SourceTypeFilter['key']) => void
  selectedStatuses: StatusSelection
  onToggleStatus: (key: RowStatusFilter['key']) => void
}

/**
 * 左侧筛选栏 —— 类型 / 索引状态。
 *
 * ## 勾选语义：空集合 = 全选
 *
 * 「不勾任何类型」= 显示全部，**不是**显示零条。原因：初次进入页面时选中态
 * 是空的，若把它解释成「什么都不显示」，用户会看到一个空列表加一句「没有
 * 匹配的资料」，而实际上他什么都没排除。
 *
 * ## 删掉的设计稿区块
 *
 * 这些不是「忘了接」，是**后端没有对应概念**，接不了也不该编：
 *   - 时间跨度：`Source.created_at` 有，但列表端点不接筛选参数，要真做得
 *     先给 `GET /sources` 加 `?since=`。
 *   - 课题与标签：`Source` 模型里**没有** tags / topic 字段。
 *   - 向量库配额：后端没有配额概念。
 */
/**
 * 状态点的 CSS Module 类名。放在组件里而不是 lib——lib 不该 import 组件的
 * 样式表（反向依赖），颜色也确实是纯展示的事。
 */
const DOT_CLASS: Record<RowStatus, string | undefined> = {
  ready: styles.dotEmerald,
  processing: styles.dotPrimary,
  failed: styles.dotError,
}

export function SourceFilterSidebar({
  typeCounts,
  statusCounts,
  selectedTypes,
  onToggleType,
  selectedStatuses,
  onToggleStatus,
}: SourceFilterSidebarProps) {
  return (
    <aside className={styles.sidebar}>
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <span className={`${styles.sectionTitle} font-label-sm uppercase tracking-wider`}>
            类型筛选 Type
          </span>
          <span className={`${styles.sectionMeta} font-code`}>{SOURCE_TYPE_FILTERS.length} 类</span>
        </div>
        <div className={styles.checkList}>
          {SOURCE_TYPE_FILTERS.map((f) => (
            <label key={f.key} className={styles.checkRow}>
              <div className={styles.checkText}>
                <input
                  type="checkbox"
                  checked={selectedTypes.has(f.key)}
                  onChange={() => onToggleType(f.key)}
                  className={`${styles.checkbox} accent-primary-container`}
                />
                <span className={`${styles.checkLabel} font-body-sm`}>{f.label}</span>
              </div>
              <span className={`${styles.checkCount} font-code`}>{typeCounts[f.key] ?? 0}</span>
            </label>
          ))}
        </div>
      </section>

      <div className={styles.divider} />

      <section className={styles.section}>
        <span className={`${styles.sectionTitle} font-label-sm uppercase tracking-wider`}>
          索引状态 Status
        </span>
        <div className={styles.checkList}>
          {ROW_STATUS_FILTERS.map((f) => (
            <label key={f.key} className={styles.checkRow}>
              <div className={styles.checkText}>
                <input
                  type="checkbox"
                  checked={selectedStatuses.has(f.key)}
                  onChange={() => onToggleStatus(f.key)}
                  className={`${styles.checkbox} accent-primary-container`}
                />
                <span className={`${styles.checkLabel} font-body-sm`}>
                  <span className={DOT_CLASS[f.key]} /> {f.label}
                </span>
              </div>
              <span
                className={`${
                  f.key === 'failed'
                    ? styles.checkCountErr
                    : f.key === 'processing'
                      ? styles.checkCountActive
                      : styles.checkCount
                } font-code`}
              >
                {statusCounts[f.key] ?? 0}
              </span>
            </label>
          ))}
        </div>
      </section>
    </aside>
  )
}
