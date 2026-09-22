"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import {
  FILTER_TABS,
  SEARCH_PLACEHOLDER,
  SEARCH_SHORTCUT,
  SORT_OPTIONS,
  VIEW_GRID_LABEL,
  VIEW_TABLE_LABEL,
} from "../../mock";
import styles from "./index.module.css";

export type ViewMode = "table" | "grid";
export type SortId = (typeof SORT_OPTIONS)[number]["id"];

export interface FilterBarProps {
  activeTabId: string;
  onTabChange: (id: string) => void;
  search: string;
  onSearchChange: (v: string) => void;
  sortId: SortId;
  onSortChange: (id: SortId) => void;
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;
}

/**
 * Combined filter bar — category tabs on the left, search + sort + view switcher on the right.
 * State lives in page.tsx; this component is fully controlled.
 */
export function FilterBar({
  activeTabId,
  onTabChange,
  search,
  onSearchChange,
  sortId,
  onSortChange,
  view,
  onViewChange,
}: FilterBarProps) {
  return (
    <div className={styles.root}>
      {/* Category tabs */}
      <div className={styles.tabs}>
        {FILTER_TABS.map((tab) => {
          const active = tab.id === activeTabId;
          return (
            <button
              key={tab.id}
              type="button"
              className={`${styles.tab} ${active ? styles.tabActive : ""}`}
              onClick={() => onTabChange(tab.id)}
              aria-pressed={active}
            >
              <span>{tab.label}</span>
              <span className={`${styles.tabCount} ${active ? styles.tabCountActive : ""}`}>
                {tab.count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Search + Sort + View */}
      <div className={styles.tools}>
        <div className={styles.search}>
          <IconSpan name="search" size={18} className={styles.searchIcon} />
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={SEARCH_PLACEHOLDER}
            className={styles.searchInput}
          />
          <kbd className={styles.kbd}>{SEARCH_SHORTCUT}</kbd>
        </div>

        <label className={styles.sort}>
          <IconSpan name="sort" size={18} className={styles.sortIcon} />
          <select
            className={styles.sortSelect}
            value={sortId}
            onChange={(e) => onSortChange(e.target.value as SortId)}
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <div className={styles.viewSwitcher}>
          <button
            type="button"
            className={`${styles.viewBtn} ${view === "table" ? styles.viewBtnActive : ""}`}
            onClick={() => onViewChange("table")}
            aria-label={VIEW_TABLE_LABEL}
            title={VIEW_TABLE_LABEL}
          >
            <IconSpan name="table_rows" size={18} />
          </button>
          <button
            type="button"
            className={`${styles.viewBtn} ${view === "grid" ? styles.viewBtnActive : ""}`}
            onClick={() => onViewChange("grid")}
            aria-label={VIEW_GRID_LABEL}
            title={VIEW_GRID_LABEL}
          >
            <IconSpan name="grid_view" size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}