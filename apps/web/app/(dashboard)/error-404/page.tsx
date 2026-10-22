'use client'

/**
 * 404 页。
 *
 * ## 删掉了什么
 *
 * 原设计稿给这一页配了整套「集群故障」布景：节点拓扑图、遥测 JSON 抽屉
 * （`cluster-ops/ingest-42`、队列深度 1,284、时序曲线）、「探针降级巡检
 * 中 / 14 节点活跃 / Cluster 99.4% Healthy」。**后端一个都没有**——404 是
 * 路由没匹配上，跟集群健康毫无关系。挂着这些只会让人以为出了生产事故。
 *
 * 现在这一页只说真话：没有资源、给你两条路回去、附一个可复制的追踪号
 * 方便用户在 issue 里引用。追踪号是**前端本地生成**的——它不是后端
 * 分配的，所以它唯一的作用就是给这次页面访问一个唯一标识。
 */

import * as React from 'react'
import { usePathname } from 'next/navigation'

import { ActionGroup } from './components/ActionGroup'
import { ErrorDisplay } from './components/ErrorDisplay'
import { ErrorHeader } from './components/ErrorHeader'
import { StatusFooter } from './components/StatusFooter'
import { TelemetryDrawer } from './components/TelemetryDrawer'
import { TraceIdBar } from './components/TraceIdBar'
import { useHealthProbe, healthStatusText } from '@/lib/api/health'
import type { TelemetrySnapshot } from './mock'
import styles from './page.module.css'

/**
 * 生成本次页面访问的追踪号。
 *
 * **不是后端分配的**——404 是路由没匹配上，请求根本没到后端。所以这个
 * 号只能在前端生成，它的用途是「让用户能在 issue 里唯一指认这次访问」。
 */
function makeTraceId(): string {
  const bytes = new Uint8Array(4)
  crypto.getRandomValues(bytes)
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `argus-404-${hex}`
}

export default function Error404Page() {
  const pathname = usePathname()
  const [traceId] = React.useState(makeTraceId)
  // 时间戳同样固定在首次渲染——render 期间读时钟会拿到不同的值。
  const [epoch] = React.useState(() => Date.now())
  const health = useHealthProbe()

  // 诊断抽屉里的内容：全部是**这一次访问的真实信息**。
  //
  // 原来这里塞的是一份编造的集群故障快照（活跃智能体、孤儿 token、集群
  // 健康百分比）——404 是路由没匹配上，那些东西与本次访问毫无关系。
  const snapshot = React.useMemo<TelemetrySnapshot>(
    () => ({
      status: 404,
      targetUri: pathname,
      epoch,
      occurredAt: new Date(epoch).toISOString(),
      path: pathname,
      userAgent: typeof navigator === 'undefined' ? '未知' : navigator.userAgent,
      backendProbe: health.kind === 'ready' ? healthStatusText(health) : null,
      traceId,
      suggestion: '确认地址拼写；若从站内其它页面跳转，可能是该路径已调整。',
      summary: '路由未匹配到任何页面',
    }),
    [epoch, health, pathname, traceId],
  )

  return (
    <div className={styles.page}>
      <div className={styles.bgGrid} />
      <div className={styles.bgGlow} />

      <ErrorHeader serviceStatus={healthStatusText(health)} />

      <main className={styles.main}>
        <div className={styles.displayBlock}>
          <ErrorDisplay
            title="页面不存在"
            subtitle="你访问的地址没有对应的页面。它可能已被移动、链接有误，或者地址拼写有误。"
          />
          <ActionGroup />
        </div>
      </main>

      <div className={styles.drawerSlot}>
        <TelemetryDrawer snapshot={snapshot} />
      </div>

      <footer className={styles.footer}>
        <TraceIdBar traceId={traceId} path={pathname} />
        <StatusFooter serviceStatus={healthStatusText(health)} />
      </footer>
    </div>
  )
}
