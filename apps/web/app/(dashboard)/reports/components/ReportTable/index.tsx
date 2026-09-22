"use client";

import * as React from "react";
import { TABLE_HEADER } from "../../mock";
import { ReportRow } from "../ReportRow";
import type { Report } from "../../mock";
import styles from "./index.module.css";

export interface ReportTableProps {
  reports: ReadonlyArray<Report>;
  selectedIds: ReadonlySet<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  allSelected: boolean;
  /** Some-but-not-all-selected renders the master checkbox as indeterminate. */
  partiallySelected: boolean;
}

/**
 * Reports table — sticky header row + N data rows.
 * Pure presentation; selection state lives in page.tsx.
 */
export function ReportTable({
  reports,
  selectedIds,
  onToggle,
  onToggleAll,
  allSelected,
  partiallySelected,
}: ReportTableProps) {
  const masterRef = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    if (masterRef.current) {
      masterRef.current.indeterminate = partiallySelected && !allSelected;
    }
  }, [partiallySelected, allSelected]);

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <div className={`${styles.headerCell} ${styles.headerTitle}`}>
          <input
            ref={masterRef}
            type="checkbox"
            className={styles.headerCheckbox}
            checked={allSelected}
            onChange={onToggleAll}
            aria-label="全选"
          />
          <button type="button" className={styles.headerBtn}>
            <span>{TABLE_HEADER.title}</span>
            <span className={styles.headerSortIcon} aria-hidden="true">
              ↓
            </span>
          </button>
        </div>
        <div className={`${styles.headerCell} ${styles.headerTopic}`}>
          <button type="button" className={styles.headerBtn}>
            <span>{TABLE_HEADER.topic}</span>
          </button>
        </div>
        <div className={`${styles.headerCell} ${styles.headerTime}`}>
          <button type="button" className={styles.headerBtn}>
            <span>{TABLE_HEADER.generatedAt}</span>
          </button>
        </div>
        <div className={`${styles.headerCell} ${styles.headerSources}`}>
          <button type="button" className={styles.headerBtn}>
            <span>{TABLE_HEADER.sources}</span>
          </button>
        </div>
        <div className={`${styles.headerCell} ${styles.headerActions}`}>
          <span>{TABLE_HEADER.status}</span>
        </div>
      </div>

      <div className={styles.body}>
        {reports.map((r, i) => (
          <ReportRow
            key={r.id}
            report={r}
            selected={selectedIds.has(r.id)}
            onToggle={onToggle}
            banded={i % 2 === 1}
          />
        ))}
      </div>
    </div>
  );
}