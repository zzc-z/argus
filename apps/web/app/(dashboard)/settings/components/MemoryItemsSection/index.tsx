'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import { IconSpan } from '@/components/common/IconSpan'
import { Input } from '@/components/ui'
import { memoryFilters, type MemoryFilter, type MemoryItem, type MemoryItemKind } from '../../mock'
import styles from './index.module.css'

export interface MemoryItemsSectionProps {
  total: number
  countsByFilter: Record<MemoryFilter['id'], number>
  activeFilter: MemoryFilter['id']
  onFilterChange: (id: MemoryFilter['id']) => void
  searchQuery: string
  onSearchChange: (q: string) => void
  items: MemoryItem[]
  onAddItem: () => void
  onEditItem: (id: string) => void
  onDeleteItem: (id: string) => void
  onExportJson: () => void
  onClearAll: () => void
}

const kindLabelMap: Record<
  MemoryItemKind,
  { label: string; tone: 'primary' | 'secondary' | 'tertiary' }
> = {
  reflection: { label: '事实反思 Reflection', tone: 'primary' },
  preference: { label: '偏好规则 Preference', tone: 'primary' },
  definition: { label: '术语定义 Definition', tone: 'secondary' },
  correction: { label: '事实修正 Correction', tone: 'tertiary' },
}

/**
 * Active Memory Vector Items (design §253-424).
 * Filter tabs + search + 4 item cards + bottom export/clear-all actions.
 * All destructive actions gated by window.confirm.
 */
export function MemoryItemsSection({
  total,
  countsByFilter,
  activeFilter,
  onFilterChange,
  searchQuery,
  onSearchChange,
  items,
  onAddItem,
  onEditItem,
  onDeleteItem,
  onExportJson,
  onClearAll,
}: MemoryItemsSectionProps) {
  const handleDelete = (item: MemoryItem) => {
    if (typeof window === 'undefined') return
    const ok = window.confirm(`确认删除该记忆项？\n\n${item.body}\n\nID: ${item.memId}`)
    if (ok) onDeleteItem(item.id)
  }

  const handleClearAll = () => {
    if (typeof window === 'undefined') return
    const ok = window.confirm(
      `确认清空全部记忆项？\n\n此操作不可撤销，将清除 ${items.length} 条记忆记录。`,
    )
    if (ok) onClearAll()
  }

  const handleExport = () => {
    if (typeof window === 'undefined') {
      onExportJson()
      return
    }
    const ok = window.confirm('导出当前记忆图谱为 JSON？')
    if (ok) onExportJson()
  }

  const handleAdd = () => {
    if (typeof window === 'undefined') {
      onAddItem()
      return
    }
    const ok = window.confirm('手动添加一条新的记忆项？')
    if (ok) onAddItem()
  }

  return (
    <section className={styles.section}>
      {/* Header */}
      <div className={styles.head}>
        <div className={styles.headTitleRow}>
          <IconSpan name="dataset" size={22} className="text-primary-container" />
          <h2 className={`${styles.title} font-headline-md text-on-surface font-semibold`}>
            活跃记忆向量项管理
          </h2>
          <span className={`${styles.totalChip} font-code text-secondary`}>Total: {total}</span>
        </div>
        <button type="button" className={styles.addBtn} onClick={handleAdd}>
          <IconSpan name="add" size={16} className="text-on-primary" />
          <span className={`${styles.addLabel} font-body-sm text-on-primary`}>
            + 手动添加记忆项
          </span>
        </button>
      </div>

      {/* Filter bar + search */}
      <div className={styles.filterBar}>
        <div className={styles.tabs} role="tablist" aria-label="记忆项分类">
          {memoryFilters.map((f) => {
            const isActive = f.id === activeFilter
            const count = countsByFilter[f.id] ?? 0
            return (
              <button
                key={f.id}
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => onFilterChange(f.id)}
                className={cn(
                  styles.tab,
                  'font-label-sm',
                  isActive ? styles.tabActive : styles.tabInactive,
                )}
              >
                {f.label} {count}
              </button>
            )
          })}
        </div>
        <div className={styles.searchWrap}>
          <IconSpan name="search" size={16} className={styles.searchIcon} />
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="快速检索记忆文本或上下文向量..."
            className={styles.searchInput}
            aria-label="搜索记忆项"
          />
        </div>
      </div>

      {/* Item list */}
      <div className={styles.list}>
        {items.length === 0 ? (
          <div className={styles.empty}>
            <span className={`${styles.emptyText} font-body-sm text-secondary`}>
              没有匹配的记忆项
            </span>
          </div>
        ) : (
          items.map((item) => {
            const meta = kindLabelMap[item.kind]
            return (
              <article key={item.id} className={styles.item}>
                <div className={styles.itemHead}>
                  <div className={styles.itemTags}>
                    <span
                      className={cn(
                        styles.itemTag,
                        'font-label-sm',
                        meta.tone === 'primary' && styles.itemTagPrimary,
                        meta.tone === 'secondary' && styles.itemTagSecondary,
                        meta.tone === 'tertiary' && styles.itemTagTertiary,
                      )}
                    >
                      {meta.label}
                    </span>
                    <span className={`${styles.itemId} font-code text-secondary`}>
                      ID: {item.memId}
                    </span>
                  </div>
                  <div className={styles.itemActions}>
                    <button
                      type="button"
                      onClick={() => onEditItem(item.id)}
                      className={`${styles.linkBtn} font-label-sm text-secondary`}
                    >
                      编辑
                    </button>
                    <span className={styles.dotSep} aria-hidden="true">
                      ·
                    </span>
                    <button
                      type="button"
                      onClick={() => handleDelete(item)}
                      className={`${styles.linkBtnDanger} font-label-sm text-secondary`}
                    >
                      删除
                    </button>
                  </div>
                </div>
                <p className={`${styles.itemBody} font-body-md text-on-surface`}>{item.body}</p>
                <div className={`${styles.itemMeta} font-code text-secondary`}>
                  <span className={styles.metaItem}>
                    <IconSpan name="calendar_today" size={14} />
                    <span>记录于 {item.recordedAt}</span>
                  </span>
                  {item.relatedReports !== undefined && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span className={cn(styles.metaItem, styles.metaItemPrimary)}>
                        <IconSpan name="description" size={14} />
                        <span>关联报告 {item.relatedReports} 篇</span>
                      </span>
                    </>
                  )}
                  {item.similarityThreshold !== undefined && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>向量相似度阈值 {item.similarityThreshold}</span>
                    </>
                  )}
                  {item.highPriority && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>全局高优先级注入</span>
                    </>
                  )}
                  {item.scopeLabel && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>{item.scopeLabel}</span>
                    </>
                  )}
                  {item.sourceLabel && (
                    <>
                      <span aria-hidden="true">·</span>
                      <span>{item.sourceLabel}</span>
                    </>
                  )}
                </div>
              </article>
            )
          })
        )}
      </div>

      {/* Bottom actions */}
      <div className={styles.bottom}>
        <button type="button" className={styles.bottomBtn} onClick={handleExport}>
          <IconSpan name="file_download" size={16} className="text-on-surface" />
          <span className={`${styles.bottomBtnLabel} font-body-sm text-on-surface`}>
            导出记忆图谱 JSON
          </span>
        </button>
        <button type="button" className={styles.bottomBtnDanger} onClick={handleClearAll}>
          <IconSpan name="delete_sweep" size={16} className="text-error" />
          <span className={`${styles.bottomBtnLabel} font-body-sm text-error`}>
            清空全部记忆项 (危险)
          </span>
        </button>
      </div>
    </section>
  )
}
