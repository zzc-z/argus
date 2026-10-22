'use client'

/**
 * /error-500 — server-fault diagnostics page.
 *
 * 与 /error-404 共用同一套组件（不另起一套布局），但换成 500 的文案与
 * 真实诊断信息。
 *
 * ## 原来这里是什么
 *
 * 一整套编造的集群故障叙事：「DAG 集群：14 节点活跃 · 探针降级巡检中」、
 * 「Argus 已暂停写入并准备回滚」、拓扑图，以及 ⌘K 时弹一个
 * `window.alert('正在呼出全局命令面板')` ——那个命令面板**根本不存在**，
 * 弹出来只有一句话。
 *
 * 现在只保留两件真事：
 * 1. 后端 liveness 探针的结果（`/api/v1/healthz`）
 * 2. 这次访问的真实运行时信息（路径、UA、时间、trace id）
 */

import * as React from 'react'
import { usePathname } from 'next/navigation'

import { ErrorHeader } from '../../(dashboard)/error-404/components/ErrorHeader'
import { ErrorDisplay } from '../../(dashboard)/error-404/components/ErrorDisplay'
import { TraceIdBar } from '../../(dashboard)/error-404/components/TraceIdBar'
import { ActionGroup } from '../../(dashboard)/error-404/components/ActionGroup'
import { TelemetryDrawer } from '../../(dashboard)/error-404/components/TelemetryDrawer'
import { StatusFooter } from '../../(dashboard)/error-404/components/StatusFooter'
import type { TelemetrySnapshot } from '../../(dashboard)/error-404/mock'

import { useHealthProbe, healthStatusText } from '@/lib/api/health'
import { ERROR_500_SUBTITLE, ERROR_500_TITLE } from './mock'
import styles from './page.module.css'

/** trace id：页面加载时生成一次，之后保持不变。 */
function makeTraceId(): string {
  const rand = Math.random().toString(16).slice(2, 10)
  return `argus_err_500_${rand}`
}

export default function Error500Page() {
  const pathname = usePathname()
  const [traceId] = React.useState(makeTraceId)
  // 时间戳同样固定在首次渲染——render 期间读时钟会拿到不同的值。
  const [epoch] = React.useState(() => Date.now())
  const health = useHealthProbe()

  const snapshot = React.useMemo<TelemetrySnapshot>(
    () => ({
      status: 500,
      targetUri: pathname,
      epoch,
      occurredAt: new Date(epoch).toISOString(),
      path: pathname,
      userAgent: typeof navigator === 'undefined' ? '未知' : navigator.userAgent,
      backendProbe: health.kind === 'ready' ? healthStatusText(health) : null,
      traceId,
      suggestion: '稍后重试；若持续出现，请把上面的 trace id 提供给工程团队。',
      summary: '服务端处理请求时发生错误',
    }),
    [epoch, health, pathname, traceId],
  )

  return (
    <div className={styles.shell}>
      <ErrorHeader serviceStatus={healthStatusText(health)} />

      <div className={styles.center}>
        <ErrorDisplay title={ERROR_500_TITLE} subtitle={ERROR_500_SUBTITLE} />
        <TraceIdBar traceId={traceId} path={pathname} />
        <ActionGroup />
      </div>

      <TelemetryDrawer snapshot={snapshot} />

      <StatusFooter serviceStatus={healthStatusText(health)} />
    </div>
  )
}
