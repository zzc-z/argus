'use client'

import * as React from 'react'
import { useHealthProbe } from '@/lib/api/health'
import styles from './index.module.css'

/**
 * 侧栏底部的「服务状态」卡片。
 *
 * ## 原来这里是什么
 *
 * 一张「Agent Run Cluster」卡：`Active`、一条写死 66.66% 的进度条、
 * 「DAG: 14 Nodes」、「99.4% Latency」，再加一个 `Session #AR-882`。
 *
 * **全是编的**——后端没有「集群」概念（agent 是串行跑的，不是 14 节点
 * 并行 DAG），也没有 99.4% 延迟这个指标，`#AR-882` 是个不存在的会话号。
 * 它挂在所有页面的侧栏上，用户每开一页都看一次假数据。
 *
 * ## 现在是什么
 *
 * 后端 `GET /api/v1/healthz` 的**真实**探测结果：服务名、版本、进程是否存
 * 活。探测失败就把真实错误显示出来，而不是假装一切正常。
 */
export function ServiceStatusCard() {
  const health = useHealthProbe()

  const { label, tone, version } = React.useMemo(() => {
    switch (health.kind) {
      case 'loading':
        return { label: '探测中…', tone: 'pending', version: '' }
      case 'ready':
        return { label: '存活', tone: 'ok', version: `${health.data.service} ${health.data.version}` }
      case 'error':
        return { label: '不可达', tone: 'error', version: health.message }
    }
  }, [health])

  return (
    <div className={styles.card}>
      <div className={styles.top}>
        <span className="font-label-sm text-secondary">后端服务</span>
        <span className={`${styles.state} ${styles[tone]} font-code`}>{label}</span>
      </div>
      <div className={`${styles.meta} font-code`}>{version}</div>
    </div>
  )
}
