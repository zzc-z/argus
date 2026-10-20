'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { cn } from '@/lib/utils'
import styles from './index.module.css'

export interface TitleHeroProps {
  /** 报告标题——后端不另存标题，用原始提问当标题。 */
  question: string
  /** ISO 时间串。 */
  createdAt: string
  inputTokens: number
  outputTokens: number
  elapsedMs: number
  /** 引用条目数。 */
  citationCount: number
}

/**
 * 报告标题区：原始提问 + 生成元信息。
 *
 * 纯展示，不自己取数——数据由页面层从 `GET /api/v1/reports/{id}` 拿。
 */
export function TitleHero({
  question,
  createdAt,
  inputTokens,
  outputTokens,
  elapsedMs,
  citationCount,
}: TitleHeroProps) {
  return (
    <section className={styles.card}>
      <h1 className={cn(styles.title, 'font-headline-xl')}>{question}</h1>

      <div className={cn(styles.metaRow, 'font-label-sm')}>
        <MetaItem icon="schedule" label={`生成于 ${formatDateTime(createdAt)}`} />
        <Sep />
        <MetaItem icon="menu_book" label={`${citationCount} 条引用`} />
        <Sep />
        <MetaItem icon="memory" label={formatTokens(inputTokens, outputTokens)} />
        <Sep />
        <MetaItem icon="timer" label={`耗时 ${formatDuration(elapsedMs)}`} />
      </div>
    </section>
  )
}

interface MetaItemProps {
  icon: string
  label: string
}

function MetaItem({ icon, label }: MetaItemProps) {
  return (
    <span className={styles.metaItem}>
      <IconSpan name={icon} size={15} />
      {label}
    </span>
  )
}

function Sep() {
  return <span className={styles.metaSep}>·</span>
}

/**
 * ISO → `2026-10-20 14:32`（本地时区）。
 *
 * 非法时间戳原样返回：坏数据不该让整个标题区白屏。
 */
function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  return `${date} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** token 用量。输入输出都留着——只给总数看不出是检索还是成稿烧的。 */
function formatTokens(inputTokens: number, outputTokens: number): string {
  return `${inputTokens.toLocaleString('zh-CN')} 输入 / ${outputTokens.toLocaleString('zh-CN')} 输出 Token`
}

/** 耗时。毫秒级保留整数，秒级一位小数，再长就用分秒。 */
function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '未知'
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes} 分 ${seconds} 秒`
}
