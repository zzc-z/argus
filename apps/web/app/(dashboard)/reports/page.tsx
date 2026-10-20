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
 *
 * ## 数据源
 *
 * `GET /api/v1/reports` —— 自己的报告列表。原先这里是 `view.ts` 里 6 条
 * 假数据（假 id `rpt-001`，点进去 404）。
 *
 * **页面结构与样式一律没动**：后端数据经 `toReportRow`（view.ts 里）
 * 映射成组件原本消费的 `Report` 形状，所以表格列、卡片、筛选、分页
 * 全部照旧——变的只有「数据从哪来」。
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

import { PAGE_SIZE, toReportRow, type Report, type TopicFilterId } from './view'
import { fetchReports, type ReportListV } from '@/lib/api/reports'

import styles from './page.module.css'

/**
 * 加载结果 + 它属于哪一页。
 *
 * 刻意不用 `loading | error | ready` 三态 + 在 effect 里 setState——
 * 那个写法触发级联渲染（React 的 `react-hooks/set-state-in-effect` 规则
 * 会报）。改成「结果 + 页码」：加载中与否从 `loadedFor !== currentPage`
 * 推导，页码变了旧数据还在，但页码对不上，页面照样显示加载态。
 */
type LoadResult =
  | { kind: 'error'; message: string; loadedFor: number }
  | { kind: 'ready'; data: ReportListV; loadedFor: number }

export default function ReportsPage() {
  // ── Data ────────────────────────────────────────────────────────
  const [result, setResult] = React.useState<LoadResult | null>(null)
  const [currentPage, setCurrentPage] = React.useState<number>(1)

  React.useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const data = await fetchReports(
          { limit: PAGE_SIZE, offset: (currentPage - 1) * PAGE_SIZE },
          controller.signal,
        )
        setResult({ kind: 'ready', data, loadedFor: currentPage })
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setResult({
          kind: 'error',
          message: err instanceof Error ? err.message : '加载失败',
          loadedFor: currentPage,
        })
      }
    })()
    return () => controller.abort()
  }, [currentPage])

  // 后端数据 → 组件消费的形状。空数组也让组件照常渲染（空表头 + 空态）。
  const REPORTS: ReadonlyArray<Report> = React.useMemo(() => {
    if (result?.kind !== 'ready') return []
    return result.data.items.map(toReportRow)
  }, [result])

  const TOTAL_REPORTS = result?.kind === 'ready' ? result.data.total : 0
  const TOTAL_PAGES = Math.max(1, Math.ceil(TOTAL_REPORTS / PAGE_SIZE))

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
  }, [REPORTS])

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
          {result && result.loadedFor !== currentPage && (
            <p className={styles.stateText}>正在加载报告…</p>
          )}
          {result?.kind === 'error' && result.loadedFor === currentPage && (
            <p role="alert" className={styles.stateError}>
              报告加载失败：{result.message}
            </p>
          )}
          {result?.kind === 'ready' && result.loadedFor === currentPage && REPORTS.length === 0 && (
            <p className={styles.stateText}>还没有生成过报告</p>
          )}

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
            rangeFrom={TOTAL_REPORTS === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1}
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
