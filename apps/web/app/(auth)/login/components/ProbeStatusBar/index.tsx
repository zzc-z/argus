import * as React from 'react'
import { StatusDot } from '@/components/common/StatusDot'
import styles from './index.module.css'

/**
 * Top live-system telemetry bar — 14 probes + uptime + cluster id.
 */
export function ProbeStatusBar() {
  return (
    <div className={styles.root}>
      <div className={styles.pill}>
        <StatusDot color="emerald" ping />
        <span className={`${styles.pillLabel} font-label-sm font-medium`}>
          14 个分布式探针节点就绪
        </span>
        <span className={styles.pillSep}>|</span>
        <span className={`${styles.pillUptime} font-code`}>99.98% 正常运行时间</span>
      </div>

      <div className={`${styles.cluster} font-code hidden sm:flex`}>
        <span className={styles.clusterLabel}>Cluster:</span>
        <span className={styles.clusterId}>us-west-2</span>
        <span className={styles.clusterDot}>·</span>
        <span>8.2k tokens/s</span>
      </div>
    </div>
  )
}
