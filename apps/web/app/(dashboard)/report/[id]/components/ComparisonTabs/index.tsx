'use client'

/**
 * Comparison view — `/report/[id]` (viewKey: 'comparison')
 *
 * Reuses SpecTable + BenchmarkBars as the primary comparison surface.
 * Above the table sits a 3-tab scope switcher (H100 / B200 / Rack) that
 * highlights the active column in SpecTable. BenchmarkBars already shows
 * both devices side-by-side; we leave its legend intact.
 */

import * as React from 'react'
import { useState } from 'react'

import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'

import { SpecTable } from '../SpecTable'
import { BenchmarkBars } from '../BenchmarkBars'
import type { BenchmarkCard, SpecRow } from '../../mock'

import styles from './index.module.css'

export interface ComparisonTabsProps {
  specRows: SpecRow[]
  benchmarks: BenchmarkCard[]
}

type Scope = 'h100' | 'b200' | 'rack'

const SCOPES: ReadonlyArray<{ key: Scope; label: string; icon: string }> = [
  { key: 'h100', label: 'H100 (Hopper)', icon: 'memory' },
  { key: 'b200', label: 'B200 (Blackwell)', icon: 'developer_board' },
  { key: 'rack', label: 'GB200 NVL72 (机架)', icon: 'dns' },
]

export function ComparisonTabs({ specRows, benchmarks }: ComparisonTabsProps) {
  const [scope, setScope] = useState<Scope>('b200')

  return (
    <section className={styles.wrap}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={cn(styles.badge, 'font-code')}>VIEW · COMPARISON</span>
          <h2 className={cn(styles.title, 'font-headline-lg')}>
            横向对比矩阵 (Comparison Table)
          </h2>
        </div>
        <span className={cn(styles.meta, 'font-label-sm')}>
          高亮选中设备列 · 跨代际并列
        </span>
      </header>

      {/* Scope tabs — flips which column SpecTable tints. */}
      <div className={cn(styles.scopeTabs, 'font-headline-sm')} role="tablist">
        {SCOPES.map((s) => {
          const active = scope === s.key
          return (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setScope(s.key)}
              className={cn(styles.scopeTab, active && styles.scopeTabActive)}
            >
              <IconSpan name={s.icon} size={18} className={active ? 'text-primary' : ''} />
              <span>{s.label}</span>
            </button>
          )
        })}
      </div>

      {/* Spec table — scope-aware column highlight. */}
      <div className={styles.scopeStage}>
        <SpecTable rows={specRows} scope={scope} />
      </div>

      {/* Benchmarks — showLegend=true to retain device legend above the bars. */}
      <BenchmarkBars cards={benchmarks} showLegend />

      {/* Tiny footnote summarizing which view is "primary". */}
      <p className={cn(styles.footnote, 'font-label-sm')}>
        当前对比主角：
        <strong>{SCOPES.find((s) => s.key === scope)?.label}</strong>。表格中该列被加粗 + 浅紫底色高亮。
      </p>
    </section>
  )
}