import * as React from "react";
import styles from "./index.module.css";

export interface PaginationFooterProps {
  shownFrom: number;
  shownTo: number;
  total: number;
  currentPage: number;
  /** When true, the surrounding section uses a compact 1-row layout. */
  compact?: boolean;
}

/**
 * Pagination bar — "Showing X-Y of Z" + prev/1/2/3/next.
 * 1:1 extracted from argus_notifications/code.html lines 406-416.
 */
export function PaginationFooter({
  shownFrom,
  shownTo,
  total,
  currentPage,
  compact,
}: PaginationFooterProps) {
  const pages = [1, 2, 3];
  return (
    <div className={compact ? styles.rowCompact : styles.row}>
      <span className={styles.label}>
        显示 {shownFrom}-{shownTo} 条 / 共 {total} 条通知
      </span>
      <div className={styles.controls}>
        <button type="button" className={styles.pageBtn} disabled>
          上一页
        </button>
        {pages.map((p) => (
          <button
            key={p}
            type="button"
            className={p === currentPage ? styles.pageBtnActive : styles.pageBtn}
          >
            {p}
          </button>
        ))}
        <button type="button" className={styles.pageBtn}>
          下一页
        </button>
      </div>
    </div>
  );
}