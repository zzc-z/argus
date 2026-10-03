'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { PlainTable, type PlainTableColumnDef } from '@/components/common/PlainTable'
import type { SpecRow } from '../../mock'
import styles from './index.module.css'

export interface SpecTableProps {
  rows: SpecRow[]
  /** Comparison view — tints the matching column. undefined = no highlight. */
  scope?: 'h100' | 'b200' | 'rack'
}

const columns: ReadonlyArray<PlainTableColumnDef<SpecRow>> = [
  {
    id: 'metric',
    cell: (row) => <span className={styles.metricCell}>{row.metric}</span>,
    header: '硬件指标维度',
    width: '280px',
  },
  {
    id: 'h100',
    cell: (row) => <span className="font-code">{row.h100}</span>,
    header: 'H100 SXM (Hopper)',
    width: '180px',
  },
  {
    id: 'b200',
    cell: (row) => (
      <span className={`font-code ${row.b200Tinted ? styles.tdTinted : ''}`}>{row.b200}</span>
    ),
    header: 'B200 (Blackwell)',
    headerAlign: 'left',
    width: '220px',
  },
  {
    id: 'rack',
    cell: (row) => (
      <span
        className={`font-code ${styles.tdPrimary} ${
          row.rackHighlight ? styles.tdPrimaryStrong : ''
        }`}
      >
        {row.rack}
      </span>
    ),
    header: 'GB200 NVL72 (机架)',
    headerAlign: 'left',
    width: '220px',
  },
]

/**
 * SECTION 02 hardware spec matrix (H100 / B200 / GB200 NVL72).
 * Pure presentation; rows come from mock. No selection.
 */
export function SpecTable({ rows, scope }: SpecTableProps) {
  // scope-aware column tinting — applied via wrapper row className.
  const scopedColumns = columns.map((c) => {
    if (!scope) return c
    const scopeMatch = c.id === scope
    const extra = scopeMatch ? styles.colScoped : ''
    return {
      ...c,
      cell: (row: SpecRow) => {
        const rendered = c.cell(row) as React.ReactElement<{ className?: string }>
        const merged = extra ? `${rendered.props.className ?? ''} ${extra}` : rendered.props.className
        return React.cloneElement(rendered, { className: merged })
      },
    } as PlainTableColumnDef<SpecRow>
  })
  return (
    <>
      <div className={styles.tableWrap}>
        <PlainTable<SpecRow>
          columns={scopedColumns}
          data={rows}
          getRowId={(r) => r.metric}
          className={`${styles.table} font-body-sm`}
        />
      </div>
      <div className={`${styles.note} font-label-sm`}>
        <IconSpan name="info" size={16} className="text-primary" />
        <span>
          注：数据整合自 NVIDIA GTC Technical Keynote 及 AnandTech 显存控制器拆解文档。原生 FP4
          依赖第二代 NV-Microscaling 精度无损转换压缩引擎。
        </span>
      </div>
    </>
  )
}