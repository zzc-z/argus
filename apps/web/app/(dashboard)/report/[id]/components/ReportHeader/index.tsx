'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import styles from './index.module.css'

export interface ReportHeaderProps {
  /** 报告 id。面包屑里显示。 */
  reportId: number
  /** 报告标题——后端不另存标题，用原始提问当标题。 */
  question: string
  /** 复制 Markdown 的回调。传了才显示那个按钮。 */
  onCopyMarkdown?: () => void
}

/**
 * 顶栏：返回 + 面包屑 + 操作按钮组。
 *
 * ## 为什么「追踪链路」被删了
 *
 * 原设计稿有 4 个操作按钮，其中「追踪链路」对应的是 agent 执行图。
 * 后端不存逐节点的执行记录（node 事件只在 SSE 流里实时发，落盘后不存在），
 * 所以这个按钮没有数据可展示——留着就是个点了没反应的假 affordance。
 *
 * 「导出 PDF」同理：后端没有导出端点，导出要另做（浏览器端打印是另一套东西）。
 * 留着也行，但**不接功能**就是骗人，所以一并删掉。
 */
export function ReportHeader({ reportId, question, onCopyMarkdown }: ReportHeaderProps) {
  return (
    <div className={styles.row}>
      <div className={styles.left}>
        <a className={styles.backBtn} href="/reports" aria-label="返回报告列表">
          <IconSpan name="arrow_back" size={18} />
        </a>
        <nav className={cn(styles.crumbs, 'font-body-sm')}>
          <a className={styles.crumbLink} href="/reports">
            报告列表
          </a>
          <span className={styles.crumbSep}>/</span>
          <span className={styles.crumbCurrent} title={question}>
            {question}
          </span>
        </nav>
        <span className={cn(styles.idChip, 'font-code')}>#{reportId}</span>
      </div>

      <div className={styles.actions}>
        {onCopyMarkdown && (
          <button
            type="button"
            onClick={onCopyMarkdown}
            className={cn(styles.actionBtn, 'font-label-md')}
          >
            <IconSpan name="markdown" size={16} />
            <span>复制 Markdown</span>
          </button>
        )}
        <button type="button" className={styles.moreBtn} aria-label="更多操作">
          <IconSpan name="more_vert" size={18} />
        </button>
      </div>
    </div>
  )
}
