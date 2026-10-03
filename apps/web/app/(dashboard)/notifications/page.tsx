'use client'

import * as React from 'react'
import { useMemo, useState, useCallback } from 'react'

import { PageLayout } from '@/components/common/PageLayout'
import { IconSpan } from '@/components/common/IconSpan'
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
  type TypeFilterValue,
  type ViewMode,
  type NotificationWithMeta,
} from './mock'

import styles from './page.module.css'

/**
 * /notifications — composition root for the notifications page.
 *
 * Owns:  selection / marked-read / status & type filter / view-mode / earlier-expand.
 * Passes derived data and handlers down to leaf components.
 */
export default function NotificationsPage() {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(['n1', 'n2']))
  const [markedReadIds, setMarkedReadIds] = useState<Set<string>>(new Set())
  const [statusFilter, setStatusFilter] = useState<'unread' | 'all'>('unread')
  const [typeFilter, setTypeFilter] = useState<TypeFilterValue>('all')
  const [viewMode, setViewMode] = useState<ViewMode>('time')
  const [earlierExpanded, setEarlierExpanded] = useState(false)

  const isDerivedUnread = useCallback(
    (item: NotificationWithMeta): boolean => item.unread && !markedReadIds.has(item.id),
    [markedReadIds],
  )

  const totalVisible = useMemo(() => {
    return allSections.reduce((sum, s) => {
      return (
        sum +
        s.items.filter((it) => {
          if (statusFilter === 'unread' && !isDerivedUnread(it)) return false
          if (typeFilter !== 'all' && it.category !== typeFilter) return false
          return true
        }).length
      )
    }, 0)
  }, [statusFilter, typeFilter, isDerivedUnread])

  const visibleIds = useMemo(() => {
    const ids: string[] = []
    for (const s of allSections) {
      for (const it of s.items) {
        if (statusFilter === 'unread' && !isDerivedUnread(it)) continue
        if (typeFilter !== 'all' && it.category !== typeFilter) continue
        ids.push(it.id)
      }
    }
    return ids
  }, [statusFilter, typeFilter, isDerivedUnread])

  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id))

  const derivedUnreadCount = useMemo(() => {
    let n = 0
    for (const s of allSections) {
      for (const it of s.items) {
        if (isDerivedUnread(it)) n += 1
      }
    }
    return n
  }, [isDerivedUnread])

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
    setSelectedIds((prev) => {
      if (allVisibleSelected) return new Set()
      return new Set(visibleIds)
    })
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
    <PageLayout
      header={null}
    >
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
          {allSections.map((section) => (
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
