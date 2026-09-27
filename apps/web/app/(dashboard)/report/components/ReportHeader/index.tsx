'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import { reportMeta } from '../../mock'
import styles from './index.module.css'

/**
 * Top breadcrumb + quick action bar for the report detail page.
 * Pure presentation; parent owns navigation.
 */
export function ReportHeader() {
  return (
    <div className={styles.row}>
      <div className={styles.left}>
        <a className={styles.backBtn} href="#" aria-label="返回报告列表">
          <IconSpan name="arrow_back" size={18} />
        </a>
        <nav className={cn(styles.crumbs, 'font-body-sm')}>
          <a className={styles.crumbLink} href="#">
            报告列表
          </a>
          <span className={styles.crumbSep}>/</span>
          <span className={styles.crumbCurrent} title={reportMeta.title}>
            {reportMeta.title}
          </span>
        </nav>
        <span className={cn(styles.idChip, 'font-code')}>#{reportMeta.id}</span>
      </div>

      <div className={styles.actions}>
        <ActionButton icon="share" label="分享" />
        <ActionButton icon="picture_as_pdf" label="导出 PDF" />
        <ActionButton icon="markdown" label="复制 Markdown" />
        <ActionButton icon="account_tree" label="追踪链路" />
        <button type="button" className={styles.moreBtn} aria-label="更多操作">
          <IconSpan name="more_vert" size={18} />
        </button>
      </div>
    </div>
  )
}

interface ActionButtonProps {
  icon: string
  label: string
}

function ActionButton({ icon, label }: ActionButtonProps) {
  return (
    <button type="button" className={cn(styles.actionBtn, 'font-label-md')}>
      <IconSpan name={icon} size={16} />
      <span>{label}</span>
    </button>
  )
}
