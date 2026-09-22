"use client";

import * as React from "react";
import { IconSpan } from "@/components/common/IconSpan";
import type { TelemetrySnapshot } from "../../mock";
import styles from "./index.module.css";

export interface TelemetryDrawerProps {
  snapshot: TelemetrySnapshot;
}

/**
 * Collapsible diagnostics drawer. Open by default (design says "for engineering transparency").
 * Renders the JSON snapshot with token-colored syntax highlighting.
 */
export function TelemetryDrawer({ snapshot }: TelemetryDrawerProps) {
  const [open, setOpen] = React.useState(true);

  const handleDownload = React.useCallback(() => {
    if (typeof window === "undefined") return;
    const blob = new Blob(
      [JSON.stringify(snapshot, null, 2)],
      { type: "application/json" }
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `argus_trace_${snapshot.status}_${snapshot.epoch}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [snapshot]);

  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div
          className={styles.header}
          role="button"
          tabIndex={0}
          onClick={() => setOpen((v) => !v)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setOpen((v) => !v);
            }
          }}
        >
          <div className={styles.headerLeft}>
            <IconSpan
              name="terminal"
              size={20}
              className="text-primary-container"
            />
            <div className={styles.headerTitleRow}>
              <span className={`${styles.headerTitle} font-headline-sm text-on-surface`}>
                工程师遥测与调用栈明细 (Telemetry &amp; Stack Trace)
              </span>
              <span className={`${styles.severityChip} font-code`}>
                CRITICAL_FAILOVER
              </span>
            </div>
          </div>
          <div className={styles.headerRight}>
            <span className={`${styles.headerMeta} font-label-sm text-secondary hidden sm:inline`}>
              JSON Payload · Runtime Snapshot
            </span>
            <IconSpan
              name="expand_more"
              size={20}
              className={`text-secondary ${styles.chevron} ${
                open ? "" : styles.chevronClosed
              }`}
            />
          </div>
        </div>

        {open && (
          <div className={styles.body}>
            <pre className={`${styles.code} font-code text-on-surface`}>
{`// Argus Runtime Context Snapshot (Epoch: ${snapshot.epoch})`}
{`{`}
{`  "status": `}
<span className="text-error">{snapshot.status}</span>
{`,`}
{`  "error_code": "`}
<span className="text-primary">{snapshot.errorCode}</span>
{`",`}
{`  "cluster_region": "`}
<span className="text-on-surface">{snapshot.clusterRegion}</span>
{`",`}
{`  "target_uri": "`}
<span className="text-on-surface">{snapshot.targetUri}</span>
{`",`}
{`  "active_agents": [`}
{`    "`}
<span className="text-secondary">{snapshot.activeAgents[0]?.name}</span>
{`",`}
{`    "`}
<span className="text-secondary">{snapshot.activeAgents[1]?.name}</span>
{`",`}
{`    "`}
<span className="text-error font-medium">
  {snapshot.activeAgents[2]?.name}
  {snapshot.activeAgents[2]?.state === "terminated" && snapshot.activeAgents[2]?.note
    ? ` (Terminated: ${snapshot.activeAgents[2]?.note})`
    : ""}
</span>
{`"`}
{`  ],`}
{`  "dag_checkpoint": "`}
<span className="text-error">{snapshot.dagCheckpoint}</span>
{`",`}
{`  "memory_buffer_state": {`}
{`    "vector_context_length": `}
<span className="text-on-surface">{snapshot.memoryBuffer.vectorContextLength}</span>
{`,`}
{`    "cached_nodes": `}
<span className="text-on-surface">{snapshot.memoryBuffer.cachedNodes}</span>
{`,`}
{`    "orphan_tokens": `}
<span className="text-on-surface">{snapshot.memoryBuffer.orphanTokens}</span>
{`  },`}
{`  "suggestion": "`}
<span className="text-primary">{snapshot.suggestion}</span>
{`"`}
{`}`}
            </pre>

            <div className={styles.footer}>
              <div className={styles.footerLeft}>
                <IconSpan
                  name="verified"
                  size={16}
                  className="text-primary-container"
                />
                <span className={`${styles.footerNote} font-label-sm text-secondary`}>
                  已自动捕获客户端内存快照与网络流回执
                </span>
              </div>
              <div className={styles.footerRight}>
                <button
                  type="button"
                  onClick={handleDownload}
                  className={styles.downloadBtn}
                >
                  <IconSpan name="download" size={16} />
                  <span className="font-body-sm">导出 JSON 日志</span>
                </button>
                <a
                  className={styles.flagLink}
                  href={`mailto:ops@argus.ai?subject=Telemetry_Fault_Report_${snapshot.errorCode}`}
                >
                  <IconSpan name="flag" size={16} />
                  <span className="font-body-sm">
                    向工程团队提交诊断日志 (附带遥测快照)
                  </span>
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
