'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import type { SpecRow } from '../../mock'
import styles from './index.module.css'

export interface SpecTableProps {
  rows: SpecRow[]
}

/**
 * SECTION 02 hardware spec matrix (H100 / B200 / GB200 NVL72).
 * Pure presentation; rows come from mock.
 */
export function SpecTable({ rows }: SpecTableProps) {
  return (
    <>
      <div className={styles.tableWrap}>
        <table className={cn(styles.table, 'font-body-sm')}>
          <thead>
            <tr className={cn(styles.thead, 'font-label-md')}>
              <th className={styles.th}>硬件指标维度</th>
              <th className={styles.th}>H100 SXM (Hopper)</th>
              <th className={cn(styles.th, styles.thTinted)}>B200 (Blackwell)</th>
              <th className={cn(styles.th, styles.thPrimary)}>GB200 NVL72 (机架)</th>
            </tr>
          </thead>
          <tbody className={cn(styles.tbody)}>
            {rows.map((r) => (
              <tr key={r.metric} className={styles.row}>
                <td className={cn(styles.td, styles.metricCell)}>{r.metric}</td>
                <td className={cn(styles.td, 'font-code')}>{r.h100}</td>
                <td className={cn(styles.td, 'font-code', r.b200Tinted && styles.tdTinted)}>
                  {r.b200}
                </td>
                <td
                  className={cn(
                    styles.td,
                    'font-code',
                    styles.tdPrimary,
                    r.rackHighlight && styles.tdPrimaryStrong,
                  )}
                >
                  {r.rack}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={cn(styles.note, 'font-label-sm')}>
        <IconSpan name="info" size={16} className="text-primary" />
        <span>
          注：数据整合自 NVIDIA GTC Technical Keynote 及 AnandTech 显存控制器拆解文档。原生 FP4
          依赖第二代 NV-Microscaling 精度无损转换压缩引擎。
        </span>
      </div>
    </>
  )
}
