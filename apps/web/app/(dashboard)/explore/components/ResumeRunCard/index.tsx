'use client'

import * as React from 'react'
import Link from 'next/link'
import { IconSpan } from '@/components/common/IconSpan'
import type { LastRun } from '../../lastRun'
import styles from './index.module.css'

export interface ResumeRunCardProps {
  run: LastRun
  /** 把上次的问题填回输入框。 */
  onReask: (question: string) => void
}

/**
 * 「上次的研究已保存」恢复条。
 *
 * ## 为什么需要它
 *
 * explore 页的运行态在组件 `useState` 里，切页即丢。但**报告是落盘的**
 * （后端 `reports` 表），所以内容找得回来——只是 explore 页自己不知道有。
 * 少了这个条，用户切回来看到一片空白，以为报告没生成。
 *
 * ## 为什么只给入口，不重建运行态
 *
 * 完整回放要存每一帧 SSE 事件（node / delta / tool_call / reference），
 * 那是「会话历史」级别的功能，不是一张卡片能承载的。这里给两个够用的
 * 出口：看已保存的报告、或把问题填回输入框重新问。
 */
export function ResumeRunCard({ run, onReask }: ResumeRunCardProps) {
  return (
    <section className={styles.card} aria-label="上次的研究">
      <div className={styles.header}>
        <IconSpan name="history" size={18} className={styles.icon} />
        <span className={styles.title}>上次的研究已保存</span>
      </div>

      <p className={styles.question} title={run.question}>
        {run.question}
      </p>

      <div className={styles.meta}>
        <span>会话 {run.sessionId.slice(0, 8)}</span>
        <span>保存于 {formatSavedAt(run.savedAt)}</span>
      </div>

      <div className={styles.actions}>
        <Link href={`/report/${run.reportId}`} className={styles.primaryBtn}>
          <IconSpan name="article" size={16} />
          <span>查看完整报告</span>
        </Link>
        <button type="button" className={styles.secondaryBtn} onClick={() => onReask(run.question)}>
          <IconSpan name="refresh" size={16} />
          <span>重新提问</span>
        </button>
      </div>
    </section>
  )
}

/** ISO 时间串 → 「3 分钟前」这种相对时间。跨天就显示日期。 */
function formatSavedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso

  const diffMs = Date.now() - d.getTime()
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`

  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
