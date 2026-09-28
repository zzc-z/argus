'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import { PageHeader } from '@/components/common/PageHeader'
import styles from './index.module.css'

export interface TopicsHeaderProps {
  /** Total topics configured (subtitle: "已配置 N 个研究课题监控"). */
  totalTopics?: number
  /** Total sources ingested (subtitle: "已接入 N 个全网权威数据源"). */
  totalSources?: number
  /** Probe success rate printed in the quick-peek pill. */
  successRate?: string
}

/**
 * Page header for the topic subscriptions page — eyebrow tag + title +
 * subtitle + Cmd-N CTA + success rate pill. The CTA dispatches a custom event
 * that `FilterBar` and `NewSubscriptionDrawer` listen for to open the drawer
 * (lets multiple triggers share one modal without prop-drilling).
 */
export function TopicsHeader({
  totalTopics = 7,
  totalSources = 847,
  successRate = '99.82%',
}: TopicsHeaderProps) {
  const openDrawer = React.useCallback(() => {
    window.dispatchEvent(new CustomEvent('argus:topics:open-drawer'))
  }, [])

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if ((e.metaKey || e.ctrlKey) && (e.key === 'n' || e.key === 'N')) {
        e.preventDefault()
        openDrawer()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openDrawer])

  return (
    <PageHeader
      eyebrow={{ tag: 'AGENT WORKSPACE // DAEMON-SUBS', note: 'DAG Cluster 巡检引擎已联机' }}
      title="主题订阅管理 (Topic Subscriptions)"
      subtitle={`当前已配置 ${totalTopics} 个研究课题监控，已接入 ${totalSources} 个全网权威数据源与 RSS 高置信度流`}
      actions={[
        {
          label: '新建研究订阅',
          icon: 'add',
          variant: 'primary',
          shortcut: '⌘N',
          onClick: openDrawer,
          className: styles.cta,
        },
      ]}
      extra={
        <div className={styles.successPill}>
          <div className={styles.successText}>
            <span className={styles.successLabel}>巡检成功率</span>
            <span className={styles.successValue}>{successRate}</span>
          </div>
          <div className={styles.successIcon}>
            <IconSpan name="verified" size={18} />
          </div>
        </div>
      }
    />
  )
}
