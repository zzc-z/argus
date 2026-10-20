'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import type { ReportSummaryV } from '@/lib/api/reports'
import styles from './index.module.css'

export interface RelatedReportsProps {
  reports: ReportSummaryV[]
  onViewAll?: () => void
}

/**
 * 「我的其它报告」列表。
 *
 * ## 从「关联研报」改成「我的其它报告」
 *
 * 原设计稿这里是**相关报告推荐**，带「匹配率 %」——那需要后端有推荐接口
 * 和相似度计算，两者都没有。后端只有 `GET /api/v1/reports`（我自己的报告
 * 列表），所以这里退化成真实存在的东西：同一账号下的其它报告。
 *
 * 删掉匹配率与分类标签（`category`）——前者是编的，后者后端没有字段。
 */
export function RelatedReports({ reports, onViewAll }: RelatedReportsProps) {
  return (
    <div className={styles.card}>
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <IconSpan name="dataset" size={20} className="text-primary" />
          <span className={cn(styles.title, 'font-headline-sm')}>我的其它报告</span>
        </div>
        <a
          href="/reports"
          className={cn(styles.viewAll, 'font-label-sm')}
          onClick={(e) => {
            e.preventDefault()
            onViewAll?.()
          }}
        >
          查看全部
        </a>
      </header>

      <div className={styles.list}>
        {reports.map((r) => (
          <a key={r.id} href={`/report/${r.id}`} className={styles.item}>
            <div className={cn(styles.itemTop, 'font-label-sm')}>
              <span>{formatDate(r.created_at)}</span>
            </div>
            <span className={cn(styles.itemTitle, 'font-body-md')}>{r.question}</span>
            <span className={cn(styles.itemMeta, 'font-label-sm')}>
              {r.input_tokens + r.output_tokens} tokens
            </span>
          </a>
        ))}
      </div>
    </div>
  )
}

/** ISO 时间串 → 「2026-10-19」这种短格式。 */
function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`
}
