'use client'

import * as React from 'react'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

import { ErrorHeader } from '../../(dashboard)/error-404/components/ErrorHeader'
import { TopologyDiagram } from '../../(dashboard)/error-404/components/TopologyDiagram'
import { ErrorDisplay } from '../../(dashboard)/error-404/components/ErrorDisplay'
import { TraceIdBar } from '../../(dashboard)/error-404/components/TraceIdBar'
import { ActionGroup } from '../../(dashboard)/error-404/components/ActionGroup'
import { TelemetryDrawer } from '../../(dashboard)/error-404/components/TelemetryDrawer'
import { StatusFooter } from '../../(dashboard)/error-404/components/StatusFooter'

import { telemetrySnapshot, traceId, clusterNode } from './mock'

import styles from './page.module.css'

const clusterStatus = 'DAG 集群：14 节点活跃 · 探针降级巡检中'

/**
 * 500-focused copy — derived from argus_error_404_500/code.html. The design
 * intentionally merges 404 + 500 into one layout; this page specializes the
 * 500 path with a server-fault narrative. /error-500 keeps the same component
 * set as /error-404 so we don't fork the layout.
 */
const reportTitle = '研报调度链路发生严重故障，Argus 已暂停写入并准备回滚'
const reportSubtitle =
  '多智能体执行过程中触发了上游推理网关的 5xx 上游异常或本地向量缓存一致性错误。本次会话草稿已冻结，下游订阅不会再读到不一致快照。请联系工程团队或触发巡检以恢复写入。'

/**
 * /error-500 — server-fault diagnostics page.
 * Reuses the /error-404 component set with 500-focused copy.
 * Top-level keyboard shortcuts: ⌘K → search, ⌘H → back to dashboard.
 */
export default function Error500Page() {
  const router = useRouter()
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey
      if (!isMod) return
      const key = e.key.toLowerCase()
      if (key === 'k') {
        e.preventDefault()
        window.alert('正在呼出全局命令面板 (⌘K)...')
      } else if (key === 'h') {
        e.preventDefault()
        router.push('/dashboard')
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [router])

  return (
    <div className={styles.shell}>
      <ErrorHeader clusterStatus={clusterStatus} />

      <div className={styles.center}>
        <TopologyDiagram />
        <ErrorDisplay title={reportTitle} subtitle={reportSubtitle} />
        <TraceIdBar traceId={traceId} clusterNode={clusterNode} />
        <ActionGroup />
      </div>

      <TelemetryDrawer snapshot={telemetrySnapshot} />

      <StatusFooter
        latencyMs={telemetrySnapshot.summary.latencyMs}
        clusterHealthPct={telemetrySnapshot.summary.clusterHealthPct}
        dataStateNote={telemetrySnapshot.summary.dataStateNote}
      />
    </div>
  )
}