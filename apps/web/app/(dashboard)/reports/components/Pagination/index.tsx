'use client'

import * as React from 'react'
import {
  PAGINATION_PAGES,
  PAGINATION_RANGE_FROM,
  PAGINATION_RANGE_TO,
  TOTAL_PAGES,
  TOTAL_REPORTS,
} from '../../mock'
import styles from './index.module.css'

export interface PaginationProps {
  currentPage: number
  totalPages: number
  totalItems: number
  rangeFrom: number
  rangeTo: number
  pageSize: number
  onPageChange: (page: number) => void
}

/**
 * Pagination footer — "显示 1-6 条, 共 47 篇研报" + numbered controls.
 * Pure presentation; page state lives in page.tsx.
 *
 * Visible page slots: from `pages` prop (mock). Renders "..." between
 * consecutive gaps > 1 (e.g. 1 2 3 ... 8).
 */
export function Pagination({
  currentPage,
  totalPages,
  totalItems,
  rangeFrom,
  rangeTo,
  onPageChange,
}: PaginationProps) {
  return (
    <footer className={styles.root}>
      <div className={styles.summary}>
        <span>显示</span>
        <span className={styles.summaryNum}>
          {rangeFrom} - {rangeTo}
        </span>
        <span>条，共</span>
        <span className={styles.summaryNum}>{totalItems}</span>
        <span>篇研报</span>
      </div>

      <div className={styles.controls}>
        <button
          type="button"
          className={styles.stepBtn}
          disabled={currentPage === 1}
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        >
          上一页
        </button>

        {PAGINATION_PAGES.map((p, i) => {
          const prev = PAGINATION_PAGES[i - 1]
          const showEllipsis = prev !== undefined && p - prev > 1
          const active = p === currentPage
          return (
            <React.Fragment key={p}>
              {showEllipsis && <span className={styles.ellipsis}>...</span>}
              <button
                type="button"
                className={`${styles.pageBtn} ${active ? styles.pageBtnActive : ''}`}
                onClick={() => onPageChange(p)}
                aria-current={active ? 'page' : undefined}
              >
                {p}
              </button>
            </React.Fragment>
          )
        })}

        <button
          type="button"
          className={styles.stepBtn}
          disabled={currentPage === totalPages}
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        >
          下一页
        </button>
      </div>
    </footer>
  )
}

// Re-export defaults from mock to keep page.tsx imports centralized.
export { PAGINATION_PAGES, PAGINATION_RANGE_FROM, PAGINATION_RANGE_TO, TOTAL_PAGES, TOTAL_REPORTS }
