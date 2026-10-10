'use client'

import * as React from 'react'
import { useMemo, useState, useCallback } from 'react'

import { PageLayout } from '@/components/common/PageLayout'
import { useNotifications } from '@/lib/notifications'
import { FilterToolbar } from './components/FilterToolbar'
import { BulkActionToolbar } from './components/BulkActionToolbar'
import { NotificationSection } from './components/NotificationSection'
import { PaginationFooter } from './components/PaginationFooter'
import { PushSettingsCard } from './components/PushSettingsCard'
import { HealthCard } from './components/HealthCard'
import { CtaCard } from './components/CtaCard'

import {
  allSections,
  totalCount,
  healthSnapshot,
  pushSettings,
  todaySection,
  type TypeFilterValue,
  type ViewMode,
  type NotificationWithMeta,
} from './mock'

import styles from './page.module.css'

/**
 * /notifications — 通知页面组合根。
 *
 * 持有：选中 / 标已读 / 状态与类型筛选 / 视图模式 / earlier 展开。
 * 把派生数据和 handler 下传到底层组件。
 */
export default function NotificationsPage() {
  const { extras: pushedItems, markedReadIds: storeReadIds } = useNotifications()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(['n1', 'n2']))
  const [markedReadIds, setMarkedReadIds] = useState<Set<string>>(new Set())
  const [statusFilter, setStatusFilter] = useState<'unread' | 'all'>('unread')
  const [typeFilter, setTypeFilter] = useState<TypeFilterValue>('all')
  const [viewMode, setViewMode] = useState<ViewMode>('time')
  const [earlierExpanded, setEarlierExpanded] = useState(false)

  // Compose sections: prepend pushed items to todaySection so fresh
  // notifications (subscriptions, ingestion, etc.) appear at the top.
  const sections = useMemo(() => {
    if (pushedItems.length === 0) return allSections
    const mergedToday = { ...todaySection, items: [...pushedItems, ...todaySection.items] }
    return [mergedToday, ...allSections.filter((s) => s.title !== todaySection.title)]
  }, [pushedItems])

  const isDerivedUnread = useCallback(
    (item: NotificationWithMeta): boolean =>
      item.unread && !markedReadIds.has(item.id) && !storeReadIds.has(item.id),
    [markedReadIds, storeReadIds],
  )

  const totalVisible = useMemo(() => {
    return sections.reduce((sum, s) => {
      return (
        sum +
        s.items.filter((it) => {
          if (statusFilter === 'unread' && !isDerivedUnread(it)) return false
          if (typeFilter !== 'all' && it.category !== typeFilter) return false
          return true
        }).length
      )
    }, 0)
  }, [sections, statusFilter, typeFilter, isDerivedUnread])

  const visibleIds = useMemo(() => {
    const ids: string[] = []
    for (const s of sections) {
      for (const it of s.items) {
        if (statusFilter === 'unread' && !isDerivedUnread(it)) continue
        if (typeFilter !== 'all' && it.category !== typeFilter) continue
        ids.push(it.id)
      }
    }
    return ids
  }, [sections, statusFilter, typeFilter, isDerivedUnread])

  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id))

  const derivedUnreadCount = useMemo(() => {
    let n = 0
    for (const s of sections) {
      for (const it of s.items) {
        if (isDerivedUnread(it)) n += 1
      }
    }
    return n
  }, [sections, isDerivedUnread])

  const toggleItem = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const markAll = useCallback(() => {
    setMarkedReadIds((prev) => {
      const next = new Set(prev)
      for (const s of allSections) {
        for (const it of s.items) {
          if (it.unread) next.add(it.id)
        }
      }
      return next
    })
  }, [])

  const markOneAsRead = useCallback((id: string) => {
    setMarkedReadIds((prev) => {
      if (prev.has(id)) return prev
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    // 全选/取消全选只关心「当前是否已全选」，不读上一次的 selectedIds
    setSelectedIds(allVisibleSelected ? new Set<string>() : new Set(visibleIds))
  }, [allVisibleSelected, visibleIds])

  const bulkMarkAsRead = useCallback(() => {
    if (selectedIds.size === 0) return
    setMarkedReadIds((prev) => {
      const next = new Set(prev)
      selectedIds.forEach((id) => next.add(id))
      return next
    })
    setSelectedIds(new Set())
  }, [selectedIds])

  const clearSelection = useCallback(() => setSelectedIds(new Set()), [])
  const mute = useCallback(() => {}, [])

  const filterItem = useCallback(
    (item: NotificationWithMeta): boolean => {
      if (statusFilter === 'unread' && !isDerivedUnread(item)) return false
      if (typeFilter !== 'all' && item.category !== typeFilter) return false
      return true
    },
    [statusFilter, typeFilter, isDerivedUnread],
  )

  const markAllAction = useCallback(() => markAll(), [markAll])

  return (
    // 本页自带面包屑头部，不走 PageLayout 的默认 PageHeader，
    // 所以不传 header（PageLayout 内部按 `header ?` 判断，传 null 也能跑，
    // 但类型声明是可选而非 nullable，传 null 过不了 tsc）。
    <PageLayout>
      {/* Top Breadcrumb & Metadata Header — 1:1 from argus_notifications/code.html */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 pt-[8px] pb-2">
        <div className="flex flex-col">
          <div className="flex items-center gap-1 text-secondary font-label-sm text-label-sm mb-1">
            <span>控制台</span>
            <span className="material-symbols-outlined text-[14px]">chevron_right</span>
            <span className="text-primary font-code">/notifications</span>
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-code text-[10px] ml-2"
              id="realtime-stream-pill"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              REALTIME_STREAM: ACTIVE
            </span>
          </div>
          <div className="flex items-baseline gap-2">
            <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight">
              通知中心 / Notifications
            </h1>
            <span className="font-label-md text-label-md text-secondary font-code">
              [{derivedUnreadCount} 新事件待处理]
            </span>
          </div>
          <p className="font-body-sm text-body-sm text-secondary mt-1">
            查看主题监控动态、智能体研报交付与知识图谱演进通知
          </p>
        </div>
        <div className="flex items-center gap-1 self-start md:self-auto">
          <button
            type="button"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-container-lowest hover:bg-surface-container text-on-surface transition-colors shadow-sm text-body-sm font-body-sm"
            id="markAllBtn"
            onClick={markAllAction}
          >
            <span className="material-symbols-outlined text-[16px] text-primary">done_all</span>
            <span>全部标为已读</span>
          </button>
          <button
            type="button"
            className="p-1.5 rounded-lg bg-surface-container-lowest hover:bg-surface-container text-secondary hover:text-on-surface transition-colors shadow-sm"
            title="通知设置"
            aria-label="通知设置"
          >
            <span className="material-symbols-outlined text-[18px]">tune</span>
          </button>
          <button
            type="button"
            className="p-1.5 rounded-lg bg-surface-container-lowest hover:bg-surface-container text-secondary hover:text-on-surface transition-colors shadow-sm"
            title="导出日志"
            aria-label="导出日志"
          >
            <span className="material-symbols-outlined text-[18px]">download</span>
          </button>
        </div>
      </div>
      <FilterToolbar
        unreadCount={derivedUnreadCount}
        totalCount={totalCount}
        statusFilter={statusFilter}
        typeFilter={typeFilter}
        viewMode={viewMode}
        onStatusChange={setStatusFilter}
        onTypeChange={setTypeFilter}
        onViewModeChange={setViewMode}
      />

      <BulkActionToolbar
        selectedCount={selectedIds.size}
        totalVisible={totalVisible}
        allVisibleSelected={allVisibleSelected}
        onToggleSelectAll={toggleSelectAll}
        onMarkAsRead={bulkMarkAsRead}
        onMute={mute}
        onClear={clearSelection}
      />

      <div className={styles.grid}>
        <div className={styles.streamCol}>
          {sections.map((section) => (
            <NotificationSection
              key={section.title}
              section={{
                ...section,
                items: section.items.map((it) =>
                  isDerivedUnread(it) === it.unread ? it : { ...it, unread: isDerivedUnread(it) },
                ),
              }}
              expanded={earlierExpanded}
              onToggleExpand={() => setEarlierExpanded((v) => !v)}
              selectedIds={selectedIds}
              onToggleItem={toggleItem}
              onMarkRead={markOneAsRead}
              filterItem={filterItem}
            />
          ))}
          <PaginationFooter
            shownFrom={1}
            shownTo={totalVisible}
            total={totalCount}
            currentPage={1}
          />
        </div>

        <aside className={styles.sideCol}>
          <PushSettingsCard push={pushSettings} />
          <HealthCard health={healthSnapshot} />
          <CtaCard />
        </aside>
      </div>
    </PageLayout>
  )
}
