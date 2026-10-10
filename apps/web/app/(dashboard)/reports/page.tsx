'use client'

/**
 * /reports — research repository list view.
 *
 * Layout (top → bottom):
 *   - PageLayout header (title + en chip + subtitle + 2 CTAs)
 *   - MetricStrip (4 KPI tiles)
 *   - FilterBar (tabs + search + sort + view switcher)
 *   - Stage: FilterDrawer (collapsible) + viewStage (table or grid + pagination)
 *   - BulkActionBar (floating, controlled by selection)
 *
 * State ownership:
 *   selection set, view mode, active tab, search, sort, drawer toggle,
 *   pagination, all topic / status / timeframe / citation filter state —
 *   lives here in page.tsx. Sub-components are fully controlled.
 */

import * as React from 'react'

import { PageLayout } from '@/components/common/PageLayout'
import { MetricStrip } from './components/MetricStrip'
import { FilterBar, type SortId, type ViewMode } from './components/FilterBar'
import { FilterDrawer } from './components/FilterDrawer'
import { ReportTable } from './components/ReportTable'
import { ReportGrid } from './components/ReportGrid'
import { Pagination } from './components/Pagination'
import { BulkActionBar } from './components/BulkActionBar'

import { PAGE_SIZE, REPORTS, TOTAL_PAGES, TOTAL_REPORTS, type TopicFilterId } from './mock'

import styles from './page.module.css'

export default function ReportsPage() {
  // ── Selection ───────────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = React.useState<ReadonlySet<string>>(() => new Set<string>())

  const toggleOne = React.useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleAll = React.useCallback(() => {
    setSelectedIds((prev) => {
      const allSelectedNow = REPORTS.every((r) => prev.has(r.id))
      if (allSelectedNow) return new Set()
      return new Set(REPORTS.map((r) => r.id))
    })
  }, [])

  const cancelSelection = React.useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  const allSelected = REPORTS.every((r) => selectedIds.has(r.id))
  const partiallySelected = !allSelected && REPORTS.some((r) => selectedIds.has(r.id))

  // ── View / tab / search / sort / page ───────────────────────────
  const [view, setView] = React.useState<ViewMode>('table')
  const [activeTabId, setActiveTabId] = React.useState<string>('all')
  const [search, setSearch] = React.useState<string>('')
  const [sortId, setSortId] = React.useState<SortId>('newest')
  const [currentPage, setCurrentPage] = React.useState<number>(1)
  const [showFilters, setShowFilters] = React.useState<boolean>(true)

  // ── Drawer filter state ─────────────────────────────────────────
  const [activeTimeframeId, setActiveTimeframeId] = React.useState<string>('all')
  const [checkedTopicIds, setCheckedTopicIds] = React.useState<ReadonlySet<TopicFilterId>>(
    () => new Set<TopicFilterId>(['ai-hardware', 'frontier-model']),
  )
  const [activeCitationId, setActiveCitationId] = React.useState<string>('10-30')
  const [checkedStatusIds, setCheckedStatusIds] = React.useState<ReadonlySet<string>>(
    () => new Set(['verified', 'running']),
  )

  const toggleTopic = React.useCallback((id: string) => {
    setCheckedTopicIds((prev) => {
      const next = new Set(prev)
      const tId = id as TopicFilterId
      if (next.has(tId)) next.delete(tId)
      else next.add(tId)
      return next
    })
  }, [])

  const toggleStatus = React.useCallback((id: string) => {
    setCheckedStatusIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const resetDrawer = React.useCallback(() => {
    setActiveTimeframeId('all')
    setCheckedTopicIds(new Set())
    setActiveCitationId('10-30')
    setCheckedStatusIds(new Set())
  }, [])

  const filterBadgeVisible =
    activeTimeframeId !== 'all' ||
    checkedTopicIds.size > 0 ||
    activeCitationId !== '10-30' ||
    checkedStatusIds.size > 0

  const onBulkAction = React.useCallback(
    (actionId: string) => {
      if (typeof window !== 'undefined') {
        console.info('[bulk-action]', actionId, Array.from(selectedIds))
      }
    },
    [selectedIds],
  )

  const onNewResearch = React.useCallback(() => {
    if (typeof window !== 'undefined') {
      console.info('[new-research] ⌘N stub')
    }
  }, [])

  return (
    <PageLayout
      header={{
        title: '研究报告库',
        enLabel: 'Research Repository',
        subtitle: '本季度已生成 142 篇研究报告 · 监控 38 个研究赛道 · 推理拓扑已就绪',
        actions: [
          {
            label: '多维筛选',
            icon: 'tune',
            variant: 'secondary',
            badge: filterBadgeVisible,
            onClick: () => setShowFilters((v) => !v),
          },
          {
            label: '发起新研究',
            icon: 'add',
            variant: 'primary',
            shortcut: '⌘N',
            onClick: onNewResearch,
          },
        ],
      }}
    >
      <MetricStrip />
      <FilterBar
        activeTabId={activeTabId}
        onTabChange={setActiveTabId}
        search={search}
        onSearchChange={setSearch}
        sortId={sortId}
        onSortChange={setSortId}
        view={view}
        onViewChange={setView}
      />
      <div className={styles.stage}>
        {showFilters && (
          <FilterDrawer
            activeTimeframeId={activeTimeframeId}
            onTimeframeChange={setActiveTimeframeId}
            checkedTopicIds={checkedTopicIds}
            onTopicToggle={toggleTopic}
            activeCitationId={activeCitationId}
            onCitationChange={setActiveCitationId}
            checkedStatusIds={checkedStatusIds}
            onStatusToggle={toggleStatus}
            onReset={resetDrawer}
          />
        )}

        <div className={styles.viewStage}>
          {view === 'table' ? (
            <ReportTable
              reports={REPORTS}
              selectedIds={selectedIds}
              onToggle={toggleOne}
              onToggleAll={toggleAll}
              allSelected={allSelected}
              partiallySelected={partiallySelected}
            />
          ) : (
            <ReportGrid reports={REPORTS} />
          )}

          <Pagination
            currentPage={currentPage}
            totalPages={TOTAL_PAGES}
            totalItems={TOTAL_REPORTS}
            rangeFrom={(currentPage - 1) * PAGE_SIZE + 1}
            rangeTo={Math.min(currentPage * PAGE_SIZE, TOTAL_REPORTS)}
            pageSize={PAGE_SIZE}
            onPageChange={setCurrentPage}
          />
        </div>
      </div>

      <BulkActionBar
        visible={selectedIds.size > 0}
        count={selectedIds.size}
        onCancel={cancelSelection}
        onAction={onBulkAction}
      />
    </PageLayout>
  )
}
