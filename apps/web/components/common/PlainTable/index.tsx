'use client'

import * as React from 'react'
import { cn } from '@/lib/utils'
import type { PlainTableColumnDef, PlainTableProps } from './types'
import styles from './index.module.css'

/**
 * 通用 PlainTable —— 裸 <table> 形态。
 *  - 列定义通过 props 传入；cell / header 完全由调用方组装
 *  - selection 受控；传 selection 时自动加 checkbox 列
 *  - 视觉对齐设计稿（argus_topics / argus_sources / argus_report_detail）：
 *    裸 table 平铺、thead 浅灰底、row hover surface-low/60、row 间 divide-y 边框
 *  - 与 DataTable 区别：无外层圆角容器、无斑马纹、无固定行高、无内置空态
 */
export function PlainTable<TData>({
  columns,
  data,
  getRowId,
  selection,
  className,
}: PlainTableProps<TData>) {
  const masterRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    if (masterRef.current && selection) {
      masterRef.current.indeterminate =
        selection.partiallySelected && !selection.allSelected
    }
  }, [selection?.partiallySelected, selection?.allSelected])

  const renderHeader = (
    content: PlainTableColumnDef<TData>['header'],
  ): React.ReactNode => (typeof content === 'function' ? content() : content)

  const checkboxThWidth = '2.5rem'

  return (
    <div className={styles.scroll}>
      <table className={cn(styles.table, className)}>
        <thead>
          <tr className={styles.theadRow}>
            {selection && (
              <th className={styles.thCheck} style={{ width: checkboxThWidth }}>
                <input
                  ref={masterRef}
                  type="checkbox"
                  aria-label="全选"
                  checked={selection.allSelected}
                  onChange={selection.onToggleAll}
                  className={styles.checkbox}
                />
              </th>
            )}
            {columns.map((col) => {
              const align = col.headerAlign ?? col.align ?? 'left'
              return (
                <th
                  key={col.id}
                  className={cn(
                    styles.th,
                    align === 'right' && styles.alignRight,
                    align === 'center' && styles.alignCenter,
                  )}
                  style={col.width ? { minWidth: col.width, width: col.width } : undefined}
                >
                  {renderHeader(col.header)}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {data.map((row, rowIndex) => {
            const id = getRowId(row, rowIndex)
            const checked = selection
              ? selection.isSelected
                ? selection.isSelected(row)
                : selection.selectedIds.has(id)
              : false
            return (
              <tr key={id} className={styles.row}>
                {selection && (
                  <td className={styles.tdCheck}>
                    <input
                      type="checkbox"
                      aria-label="选择行"
                      checked={checked}
                      onChange={() => selection.onToggle(id)}
                      className={styles.checkbox}
                    />
                  </td>
                )}
                {columns.map((col) => {
                  const align = col.align ?? 'left'
                  return (
                    <td
                      key={col.id}
                      className={cn(
                        styles.td,
                        align === 'right' && styles.alignRight,
                        align === 'center' && styles.alignCenter,
                        col.cellClassName,
                      )}
                    >
                      {col.cell(row)}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export type {
  PlainTableColumnDef,
  PlainTableProps,
  PlainTableSelection,
  PlainTableAlign,
} from './types'