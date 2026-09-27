'use client'

import * as React from 'react'
import { useEffect } from 'react'

import { ErrorHeader } from './components/ErrorHeader'
import { TopologyDiagram } from './components/TopologyDiagram'
import { ErrorDisplay } from './components/ErrorDisplay'
import { TraceIdBar } from './components/TraceIdBar'
import { ActionGroup } from './components/ActionGroup'
import { TelemetryDrawer } from './components/TelemetryDrawer'
import { StatusFooter } from './components/StatusFooter'

import { telemetrySnapshot, traceId, clusterNode, reportTitle, reportSubtitle } from './mock'

import styles from './page.module.css'

const clusterStatus = 'DAG 集群：14 节点活跃 · 探针降级巡检中'

/**
 * /error-404 — full 404/500 diagnostics page.
 * Owns top-level keyboard shortcuts (⌘K → search, ⌘H → back to dashboard).
 */
export default function ErrorPage() {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey
      if (!isMod) return
      const key = e.key.toLowerCase()
      if (key === 'k') {
        e.preventDefault()
        // Placeholder for global command palette — design uses an alert.
        window.alert('正在呼出全局命令面板 (⌘K)...')
      } else if (key === 'h') {
        e.preventDefault()
        // Navigate to dashboard anchor (no real router wired yet).
        window.location.href = '#dashboard'
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  return (
    <main className={styles.main}>
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
    </main>
  )
}
