import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import styles from './index.module.css'

export interface StatusFooterProps {
  /** 后端服务状态文案——来自真实的 /api/v1/healthz 探测结果。 */
  serviceStatus: string
}

/**
 * 底部状态行。
 *
 * ## 原来那三个数字去哪了
 *
 * 原版显示「Latency: 47ms · Cluster: 99.40% Healthy · 数据状态：本地草稿
 * 已同步至分布式容灾缓存」——三个都是编的：
 *
 * - **Latency** 是一次模拟的请求耗时，没有任何真实测量
 * - **Cluster 健康度** 假造了一个集群概念；本仓是单进程部署，没有集群
 * - **数据状态** 写的是「已同步至分布式容灾缓存」——本仓没有容灾缓存，
 *   数据就在一个 SQLite 文件里
 *
 * 现在只显示后端探针**真正**返回的状态。
 */
export function StatusFooter({ serviceStatus }: StatusFooterProps) {
  return (
    <div className={styles.row}>
      <div className={styles.left}>
        <span className={styles.dataState}>
          <IconSpan name="dns" size={14} />
          <span>{serviceStatus}</span>
        </span>
      </div>
      <div className={`${styles.right} font-code`}>
        <a className={styles.statusLink} href="/dashboard">
          返回研究看板
        </a>
      </div>
    </div>
  )
}
