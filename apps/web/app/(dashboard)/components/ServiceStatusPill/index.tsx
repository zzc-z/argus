'use client'

import * as React from 'react'
import { useHealthProbe } from '@/lib/api/health'
import styles from './index.module.css'

/**
 * 顶栏右侧的服务状态胶囊。
 *
 * ## 原来这里是什么
 *
 * `就绪 · 8.2k tokens/s`——那个吞吐率是**编的**。后端没有任何地方统计过
 * 「每秒多少 token」，也没有对外暴露。它长得像一个真指标（所以用户会
 * 当真），但它是假的。
 *
 * 现在显示的是 `/api/v1/healthz` 探测回来的**服务名与版本**——真能查证
 * 的东西。探测失败时显示「不可达」，不假装就绪。
 */
export function ServiceStatusPill() {
  const health = useHealthProbe()

  const { label, detail, tone } =
    health.kind === 'ready'
      ? { label: '就绪', detail: `${health.data.service} ${health.data.version}`, tone: 'ok' }
      : health.kind === 'loading'
        ? { label: '探测中', detail: '…', tone: 'pending' }
        : { label: '不可达', detail: '后端服务', tone: 'error' }

  return (
    <div className={styles.pill}>
      <span className={`${styles.dot} ${styles[tone]}`} aria-hidden="true" />
      <span className={`${styles.text} font-label-sm`}>{label}</span>
      <span className={styles.sep}>·</span>
      <span className={`${styles.rate} font-code`}>{detail}</span>
    </div>
  )
}
