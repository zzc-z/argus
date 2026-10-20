'use client'

import * as React from 'react'
import { PAGINATION_RANGE_FROM, PAGINATION_RANGE_TO } from '../../view'
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
 * 页码槽位按 totalPages 动态生成。Renders "..." between
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

        {pageSlots(totalPages, currentPage).map((p, i, arr) => {
          const prev = arr[i - 1]
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

// Re-export defaults from view to keep page.tsx imports centralized.
export { PAGINATION_RANGE_FROM, PAGINATION_RANGE_TO }

/**
 * 生成页码槽位。
 *
 * 首页、末页、当前页及其邻页始终显示，中间用 `...` 折叠。总页数 ≤ 7 时
 * 全部列出——再折叠反而看不清。
 */
function pageSlots(totalPages: number, currentPage: number): ReadonlyArray<number> {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1)
  }
  const slots = new Set<number>([1, totalPages, currentPage])
  for (const d of [-1, 1]) {
    const p = currentPage + d
    if (p >= 1 && p <= totalPages) slots.add(p)
  }
  return [...slots].sort((a, b) => a - b)
}
