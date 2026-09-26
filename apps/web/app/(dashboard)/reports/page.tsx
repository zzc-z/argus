"use client";

/**
 * /reports — research repository list view.
 *
 * 1:1 with argus_reports/code.html: top app bar, left sidebar, page title +
 * CTAs, 4 KPI tiles, filter tabs + search + sort + view switcher, filter
 * drawer (timeframe / topics / citation / status / confidence), main view
 * stage (table default, grid toggle), pagination footer, floating bulk
 * action bar.
 *
 * State ownership:
 *   - selection set, view mode, active tab, search, sort, drawer toggle,
 *     pagination, all topic / status / timeframe / citation filter state —
 *     lives here in page.tsx. Sub-components are fully controlled.
 */

import * as React from "react";

import { ReportsHeader } from "./components/ReportsHeader";
import { MetricStrip } from "./components/MetricStrip";
import { FilterBar, type SortId, type ViewMode } from "./components/FilterBar";
import { FilterDrawer } from "./components/FilterDrawer";
import { ReportTable } from "./components/ReportTable";
import { ReportGrid } from "./components/ReportGrid";
import { Pagination } from "./components/Pagination";
import { BulkActionBar } from "./components/BulkActionBar";

import {
  PAGE_SIZE,
  REPORTS,
  TOTAL_PAGES,
  TOTAL_REPORTS,
  type TopicFilterId,
} from "./mock";

import styles from "./page.module.css";

export default function ReportsPage() {
  // ── Selection ───────────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = React.useState<ReadonlySet<string>>(
    () => new Set<string>()
  );

  const toggleOne = React.useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = React.useCallback(() => {
    setSelectedIds((prev) => {
      const allSelectedNow = REPORTS.every((r) => prev.has(r.id));
      if (allSelectedNow) return new Set();
      return new Set(REPORTS.map((r) => r.id));
    });
  }, []);

  const cancelSelection = React.useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const allSelected = REPORTS.every((r) => selectedIds.has(r.id));
  const partiallySelected =
    !allSelected && REPORTS.some((r) => selectedIds.has(r.id));

  // ── View / tab / search / sort / page ───────────────────────────
  const [view, setView] = React.useState<ViewMode>("table");
  const [activeTabId, setActiveTabId] = React.useState<string>("all");
  const [search, setSearch] = React.useState<string>("");
  const [sortId, setSortId] = React.useState<SortId>("newest");
  const [currentPage, setCurrentPage] = React.useState<number>(1);
  const [showFilters, setShowFilters] = React.useState<boolean>(true);

  // ── Drawer filter state ─────────────────────────────────────────
  const [activeTimeframeId, setActiveTimeframeId] =
    React.useState<string>("all");
  const [checkedTopicIds, setCheckedTopicIds] = React.useState<
    ReadonlySet<TopicFilterId>
  >(() => new Set<TopicFilterId>(["ai-hardware", "frontier-model"]));
  const [activeCitationId, setActiveCitationId] = React.useState<string>("10-30");
  const [checkedStatusIds, setCheckedStatusIds] = React.useState<
    ReadonlySet<string>
  >(() => new Set(["verified", "running"]));

  const toggleTopic = React.useCallback((id: string) => {
    setCheckedTopicIds((prev) => {
      const next = new Set(prev);
      const tId = id as TopicFilterId;
      if (next.has(tId)) next.delete(tId);
      else next.add(tId);
      return next;
    });
  }, []);

  const toggleStatus = React.useCallback((id: string) => {
    setCheckedStatusIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const resetDrawer = React.useCallback(() => {
    setActiveTimeframeId("all");
    setCheckedTopicIds(new Set());
    setActiveCitationId("10-30");
    setCheckedStatusIds(new Set());
  }, []);

  const filterBadgeVisible =
    activeTimeframeId !== "all" ||
    checkedTopicIds.size > 0 ||
    activeCitationId !== "10-30" ||
    checkedStatusIds.size > 0;

  const onBulkAction = React.useCallback(
    (actionId: string) => {
      // Mock-only — log intent, leave selection intact for follow-up.
      if (typeof window !== "undefined") {
        // eslint-disable-next-line no-console
        console.info("[bulk-action]", actionId, Array.from(selectedIds));
      }
    },
    [selectedIds]
  );

  const onNewResearch = React.useCallback(() => {
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.info("[new-research] ⌘N stub");
    }
  }, []);

  // ── Render ──────────────────────────────────────────────────────
  return (
    <div className={styles.shell}>
      <div className={`${styles.main} ${styles.collapseMainInnerPadding}`}>
        <div className={styles.content}>
          <ReportsHeader
            filterBadgeVisible={filterBadgeVisible}
            onToggleFilters={() => setShowFilters((v) => !v)}
            onNewResearch={onNewResearch}
          />

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
              {view === "table" ? (
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
        </div>
      </div>

      <BulkActionBar
        visible={selectedIds.size > 0}
        count={selectedIds.size}
        onCancel={cancelSelection}
        onAction={onBulkAction}
      />
    </div>
  );
}