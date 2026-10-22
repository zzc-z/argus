'use client'

import * as React from 'react'
import { IconSpan } from '@/components/common/IconSpan'
import type { TelemetrySnapshot } from '../../mock'
import styles from './index.module.css'

export interface TelemetryDrawerProps {
  snapshot: TelemetrySnapshot
}

/**
 * 可折叠的诊断抽屉。默认展开。
 *
 * ## 这里面装的是真东西
 *
 * 原设计稿里这个抽屉装的是一份**编造的集群故障快照**：活跃智能体列表、
 * 向量上下文长度、孤儿 token 数、DAG 检查点，还写着「已自动捕获客户端内存
 * 快照与网络流回执」——**这个页面根本没有捕获任何东西**，那句话是假的。
 * 「向工程团队提交诊断日志」也是死链（`ops@argus.ai` 这个邮箱不存在）。
 *
 * 现在装的是这一次访问真正知道的事：HTTP 状态码、路径、浏览器 UA、访问
 * 时间、后端 liveness 探测结果、trace id。没有��的字段就��写。
 */
export function TelemetryDrawer({ snapshot }: TelemetryDrawerProps) {
  const [open, setOpen] = React.useState(true)

  const handleDownload = React.useCallback(() => {
    if (typeof window === 'undefined') return
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `argus_diagnostics_${snapshot.status}_${snapshot.traceId}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [snapshot])

  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div
          className={styles.header}
          role="button"
          tabIndex={0}
          onClick={() => setOpen((v) => !v)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              setOpen((v) => !v)
            }
          }}
        >
          <div className={styles.headerLeft}>
            <IconSpan name="terminal" size={20} className="text-primary-container" />
            <div className={styles.headerTitleRow}>
              <span className={`${styles.headerTitle} font-headline-sm text-on-surface`}>
                访问诊断信息 (Diagnostics)
              </span>
              <span className={`${styles.severityChip} font-code`}>
                HTTP {snapshot.status}
              </span>
            </div>
          </div>
          <div className={styles.headerRight}>
            <span className={`${styles.headerMeta} font-label-sm text-secondary hidden sm:inline`}>
              JSON · 本次访问
            </span>
            <IconSpan
              name="expand_more"
              size={20}
              className={`text-secondary ${styles.chevron} ${open ? '' : styles.chevronClosed}`}
            />
          </div>
        </div>

        {open && (
          <div className={styles.body}>
            <pre className={`${styles.code} font-code text-on-surface`}>
              {`{`}
              {`  "status": `}
              <span className="text-error">{snapshot.status}</span>
              {`,`}
              {`  "path": "`}
              <span className="text-on-surface">{snapshot.path}</span>
              {`",`}
              {`  "occurred_at": "`}
              <span className="text-on-surface">{snapshot.occurredAt}</span>
              {`",`}
              {`  "user_agent": "`}
              <span className="text-on-surface">{snapshot.userAgent}</span>
              {`",`}
              {`  "backend_probe": `}
              {snapshot.backendProbe === null ? (
                <span className="text-error">null</span>
              ) : (
                <>
                  {`"`}
                  <span className="text-on-surface">{snapshot.backendProbe}</span>
                  {`"`}
                </>
              )}
              {`,`}
              {`  "trace_id": "`}
              <span className="text-primary">{snapshot.traceId}</span>
              {`",`}
              {`  "suggestion": "`}
              <span className="text-primary">{snapshot.suggestion}</span>
              {`"`}
              {`}`}
            </pre>

            <div className={styles.footer}>
              <div className={styles.footerLeft}>
                <IconSpan name="info" size={16} className="text-primary-container" />
                <span className={`${styles.footerNote} font-label-sm text-secondary`}>
                  以上信息由浏览器本地采集，未上报任何服务器
                </span>
              </div>
              <div className={styles.footerRight}>
                <button type="button" onClick={handleDownload} className={styles.downloadBtn}>
                  <IconSpan name="download" size={16} />
                  <span className="font-body-sm">导出 JSON</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
